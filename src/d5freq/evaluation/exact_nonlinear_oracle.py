"""Evaluation-only simulator-exact nonlinear Oracle benchmark (B5).

B5 deliberately lives below :mod:`d5freq.evaluation` and is not constructed by
the ordinary controller factory.  It knows the current physical IBR mode and
its nonlinear parameters, but it receives the same :class:`Measurement` and
uses the same controller-side grid/load estimator as the runtime methods.
Future disturbances and future mode switches are not exposed to its planner.

The optimizer is a finite, auditable one-move direct-shooting approximation.
Every candidate is propagated with the exact nonlinear equations, RK4 step,
delay convention, saturation, deadband, and physical rate limits used by the
plant simulator.  A failed/empty/non-finite solve raises instead of silently
substituting LQI while continuing to call the result B5.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from numbers import Integral, Real
from time import perf_counter
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray

from d5freq.controllers.base import clip_with_rate_limit
from d5freq.estimation.grid_kalman_filter import GridKalmanFilter
from d5freq.interfaces import ControlAction, Measurement
from d5freq.models.grid_frequency import GRID_STATE_SIZE, GridFrequencyModel, GridStateIndex
from d5freq.models.hidden_mode_ibr import (
    CommandHistory,
    IBRModeParams,
    IBRState,
    resolve_delay_s,
)
from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator, Scenario


FloatArray = NDArray[np.float64]
EXACT_ORACLE_SCHEMA_VERSION = "d5freq.phase_b1.exact_nonlinear_oracle.v1"


def _finite(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _positive(value: object, name: str) -> float:
    result = _finite(value, name)
    if result <= 0.0:
        raise ValueError(f"{name} must be positive")
    return result


def _offsets(values: Sequence[float], name: str) -> tuple[float, ...]:
    result = tuple(_finite(value, name) for value in values)
    if not result or tuple(sorted(set(result))) != result:
        raise ValueError(f"{name} must be non-empty, unique, and increasing")
    if result[0] < -1.0 or result[-1] > 1.0 or 0.0 not in result:
        raise ValueError(f"{name} must lie in [-1, 1] and contain zero")
    return result


@dataclass(frozen=True, slots=True)
class ExactOracleBounds:
    sg_min_pu: float
    sg_max_pu: float
    sg_ramp_pu_per_s: float
    ibr_min_pu: float = -0.08
    ibr_max_pu: float = 0.08
    ibr_ramp_pu_per_s: float = 0.04
    frequency_limit_hz: float = 0.5
    rocof_limit_hz_per_s: float = 0.5

    def __post_init__(self) -> None:
        for name in (
            "sg_min_pu",
            "sg_max_pu",
            "sg_ramp_pu_per_s",
            "ibr_min_pu",
            "ibr_max_pu",
            "ibr_ramp_pu_per_s",
            "frequency_limit_hz",
            "rocof_limit_hz_per_s",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.sg_min_pu >= self.sg_max_pu or self.ibr_min_pu >= self.ibr_max_pu:
            raise ValueError("Oracle command lower bounds must be below upper bounds")
        if min(
            self.sg_ramp_pu_per_s,
            self.ibr_ramp_pu_per_s,
            self.frequency_limit_hz,
            self.rocof_limit_hz_per_s,
        ) <= 0.0:
            raise ValueError("Oracle rate and safety limits must be positive")


@dataclass(frozen=True, slots=True)
class ExactOracleWeights:
    q_freq: float = 3000.0
    q_integral: float = 50.0
    q_rocof: float = 50.0
    r_sg: float = 1.0
    r_ibr: float = 0.5
    s_delta_sg: float = 20.0
    s_delta_ibr: float = 10.0
    q_terminal_freq: float = 6000.0
    q_terminal_integral: float = 100.0
    safety_violation_penalty: float = 1.0e8

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = _finite(getattr(self, name), name)
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")
            object.__setattr__(self, name, value)
        if self.q_freq <= 0.0 or self.safety_violation_penalty <= 0.0:
            raise ValueError("frequency and safety weights must be positive")


@dataclass(frozen=True, slots=True)
class ExactOraclePlannerConfig:
    horizon_s: float
    integration_step_s: float = 0.02
    sg_normalized_ramp_offsets: tuple[float, ...] = (-1.0, 0.0, 1.0)
    ibr_normalized_ramp_offsets: tuple[float, ...] = (-1.0, -0.5, 0.0, 0.5, 1.0)
    terminal_cost_multiplier: float = 1.0
    idle_frequency_threshold_hz: float = 0.01
    idle_power_imbalance_threshold_pu: float = 0.002

    def __post_init__(self) -> None:
        horizon = _positive(self.horizon_s, "horizon_s")
        step = _positive(self.integration_step_s, "integration_step_s")
        terminal = _positive(self.terminal_cost_multiplier, "terminal_cost_multiplier")
        idle_frequency = _positive(
            self.idle_frequency_threshold_hz,
            "idle_frequency_threshold_hz",
        )
        idle_imbalance = _positive(
            self.idle_power_imbalance_threshold_pu,
            "idle_power_imbalance_threshold_pu",
        )
        if horizon + 1.0e-12 < step:
            raise ValueError("horizon_s must not be shorter than integration_step_s")
        object.__setattr__(self, "horizon_s", horizon)
        object.__setattr__(self, "integration_step_s", step)
        object.__setattr__(self, "terminal_cost_multiplier", terminal)
        object.__setattr__(self, "idle_frequency_threshold_hz", idle_frequency)
        object.__setattr__(
            self,
            "idle_power_imbalance_threshold_pu",
            idle_imbalance,
        )
        object.__setattr__(
            self,
            "sg_normalized_ramp_offsets",
            _offsets(self.sg_normalized_ramp_offsets, "sg_normalized_ramp_offsets"),
        )
        object.__setattr__(
            self,
            "ibr_normalized_ramp_offsets",
            _offsets(self.ibr_normalized_ramp_offsets, "ibr_normalized_ramp_offsets"),
        )


@dataclass(frozen=True, slots=True)
class ExactOracleContext:
    """Evaluator-owned truth context; never accepted by ordinary factories."""

    grid_model: GridFrequencyModel
    mode_params_eval_only: Mapping[str, IBRModeParams]
    scenario_eval_only: Scenario
    seed: int
    sg_level: str
    bounds: ExactOracleBounds
    planner: ExactOraclePlannerConfig
    weights: ExactOracleWeights = ExactOracleWeights()
    process_noise_diagonal: tuple[float, ...] = (
        1.0e-12,
        1.0e-10,
        1.0e-9,
        1.0e-12,
        0.0,
    )
    measurement_noise_diagonal: tuple[float, ...] = (1.0e-8, 4.0e-8)
    initial_covariance_diagonal: tuple[float, ...] = (
        1.0e-6,
        1.0e-5,
        1.0e-4,
        1.0e-3,
        1.0e-3,
    )
    load_random_walk_std_pu_per_s: float = 1.0e-4

    def __post_init__(self) -> None:
        if not isinstance(self.grid_model, GridFrequencyModel):
            raise TypeError("grid_model must be a GridFrequencyModel")
        if not isinstance(self.scenario_eval_only, Scenario):
            raise TypeError("scenario_eval_only must be a Scenario")
        modes = dict(self.mode_params_eval_only)
        if not modes or any(
            key != value.name or not isinstance(value, IBRModeParams)
            for key, value in modes.items()
        ):
            raise ValueError("mode_params_eval_only must be a non-empty keyed mode map")
        unknown = set(self.scenario_eval_only.mode_schedule.modes) - set(modes)
        if unknown:
            raise ValueError(f"scenario references unknown exact modes: {sorted(unknown)!r}")
        if isinstance(self.seed, bool) or not isinstance(self.seed, Integral) or self.seed < 0:
            raise ValueError("seed must be a non-negative integer")
        level = str(self.sg_level).strip()
        if level not in {"A", "B", "C"}:
            raise ValueError("sg_level must be A, B, or C")
        if not isinstance(self.bounds, ExactOracleBounds):
            raise TypeError("bounds must be ExactOracleBounds")
        if not isinstance(self.planner, ExactOraclePlannerConfig):
            raise TypeError("planner must be ExactOraclePlannerConfig")
        if not isinstance(self.weights, ExactOracleWeights):
            raise TypeError("weights must be ExactOracleWeights")
        for values, size, name in (
            (self.process_noise_diagonal, GRID_STATE_SIZE, "process_noise_diagonal"),
            (self.measurement_noise_diagonal, 2, "measurement_noise_diagonal"),
            (self.initial_covariance_diagonal, GRID_STATE_SIZE, "initial_covariance_diagonal"),
        ):
            normalized = tuple(_finite(value, name) for value in values)
            if len(normalized) != size or min(normalized) < 0.0:
                raise ValueError(f"{name} must have {size} non-negative values")
            object.__setattr__(self, name, normalized)
        load_std = _finite(
            self.load_random_walk_std_pu_per_s,
            "load_random_walk_std_pu_per_s",
        )
        if load_std < 0.0:
            raise ValueError("load_random_walk_std_pu_per_s must be non-negative")
        object.__setattr__(self, "load_random_walk_std_pu_per_s", load_std)
        object.__setattr__(self, "mode_params_eval_only", MappingProxyType(modes))
        object.__setattr__(self, "seed", int(self.seed))
        object.__setattr__(self, "sg_level", level)


@dataclass(frozen=True, slots=True)
class ExactOracleRolloutResult:
    objective: FloatArray
    max_abs_frequency_hz: FloatArray
    max_abs_rocof_hz_per_s: FloatArray
    terminal_state: FloatArray


@dataclass(frozen=True, slots=True)
class ExactOracleStepRecord:
    time_s: float
    true_mode_eval_only: str
    sg_level: str
    controller_state: str
    solver_status: str
    solver_outcome: str
    solver_name: str
    solver_version: str
    solve_time_s: float
    candidate_count: int
    safety_feasible_candidate_count: int
    selected_candidate_index: int
    selected_objective: float
    predicted_max_abs_frequency_hz: float
    predicted_max_abs_rocof_hz_per_s: float
    current_load_estimate_pu: float
    mirror_measurement_max_abs_error: float
    u_sg_pu: float
    u_ibr_pu: float
    max_freq_slack_hz: float
    max_rocof_slack_hz_s: float
    max_power_slack_pu: float = 0.0
    diagnostic_state: str = "TRUTH_MODE_EVALUATION_ONLY"
    mode_belief: tuple[float, ...] = (1.0,)
    map_mode: int = 0
    belief_entropy: float = 0.0
    ood_pvalue: float = 1.0

    def to_log_record(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }


class ExactOracleSolveError(RuntimeError):
    """Raised when B5 cannot produce an explicit exact-shooting solution."""


def _historical_delayed_values(
    history: CommandHistory,
    query_time_s: float,
    start_time_s: float,
    candidate_ibr: FloatArray,
) -> FloatArray:
    if query_time_s >= start_time_s:
        return candidate_ibr
    return np.full(candidate_ibr.shape, history.value_at(query_time_s), dtype=float)


def _segment_boundaries(
    *,
    start_time_s: float,
    horizon_s: float,
    integration_step_s: float,
    history: CommandHistory,
    params: IBRModeParams,
) -> tuple[float, ...]:
    end = start_time_s + horizon_s
    boundaries = {end}
    count = int(math.ceil(horizon_s / integration_step_s))
    boundaries.update(
        min(end, start_time_s + index * integration_step_s)
        for index in range(1, count + 1)
    )
    if params.delay_profile is None:
        boundaries.update(
            sample_time + params.delay_s
            for sample_time in history.times_s
            if start_time_s < sample_time + params.delay_s <= end
        )
    return tuple(sorted(boundary for boundary in boundaries if boundary > start_time_s))


def rollout_exact_current_mode_eval_only(
    *,
    grid_model: GridFrequencyModel,
    params_eval_only: IBRModeParams,
    start_time_s: float,
    initial_state: FloatArray,
    command_history: CommandHistory,
    candidate_u_sg_pu: FloatArray,
    candidate_u_ibr_pu: FloatArray,
    horizon_s: float,
    integration_step_s: float,
    bounds: ExactOracleBounds,
    weights: ExactOracleWeights,
    previous_u_sg_pu: float,
    previous_u_ibr_pu: float,
    terminal_cost_multiplier: float = 1.0,
) -> ExactOracleRolloutResult:
    """Batch exact nonlinear rollout conditional on the current true mode.

    The fifth grid state is the controller-side current load estimate and is
    held constant.  This is intentional: B5 has exact IBR physics, not advance
    knowledge of evaluator-owned load events.
    """

    if not isinstance(grid_model, GridFrequencyModel):
        raise TypeError("grid_model must be a GridFrequencyModel")
    if not isinstance(params_eval_only, IBRModeParams):
        raise TypeError("params_eval_only must be IBRModeParams")
    sg = np.asarray(candidate_u_sg_pu, dtype=float).reshape(-1)
    ibr = np.asarray(candidate_u_ibr_pu, dtype=float).reshape(-1)
    if sg.shape != ibr.shape or sg.size == 0 or not np.all(np.isfinite(sg + ibr)):
        raise ValueError("candidate action arrays must be aligned, finite, and non-empty")
    base_state = np.asarray(initial_state, dtype=float)
    if base_state.shape != (GRID_STATE_SIZE + 2,) or not np.all(np.isfinite(base_state)):
        raise ValueError("initial_state must contain seven finite exact-planning states")
    state = np.repeat(base_state[None, :], sg.size, axis=0)
    objective = (
        weights.s_delta_sg * np.square(sg - previous_u_sg_pu)
        + weights.s_delta_ibr * np.square(ibr - previous_u_ibr_pu)
    )
    max_freq = np.abs(grid_model.params.f0_hz * state[:, GridStateIndex.OMEGA_PU])
    load = state[:, GridStateIndex.LOAD_DISTURBANCE_PU].copy()
    initial_rocof = grid_model.params.f0_hz * (
        -grid_model.params.D_pu * state[:, GridStateIndex.OMEGA_PU]
        + state[:, GridStateIndex.P_MECH_PU]
        + state[:, GRID_STATE_SIZE + 1]
        - load
    ) / grid_model.params.M_s
    max_rocof = np.abs(initial_rocof)
    A = grid_model.A_c
    B = grid_model.B_c[:, 0]
    E = grid_model.E_c[:, 0]
    current_time = _finite(start_time_s, "start_time_s")
    horizon = _positive(horizon_s, "horizon_s")
    step = _positive(integration_step_s, "integration_step_s")

    def derivative(stage_time: float, values: FloatArray) -> FloatArray:
        grid = values[:, :GRID_STATE_SIZE]
        q = values[:, GRID_STATE_SIZE]
        power = values[:, GRID_STATE_SIZE + 1]
        delay = resolve_delay_s(params_eval_only, stage_time)
        delayed = _historical_delayed_values(
            command_history,
            stage_time - delay,
            start_time_s,
            ibr,
        )
        deadbanded = np.where(
            np.abs(delayed) <= params_eval_only.deadband_pu,
            0.0,
            delayed - np.copysign(params_eval_only.deadband_pu, delayed),
        )
        reference = (
            params_eval_only.command_gain * deadbanded
            - params_eval_only.frequency_gain * grid[:, GridStateIndex.OMEGA_PU]
        )
        q_dot = (reference - q) / params_eval_only.command_filter_time_s
        q_bar = np.clip(
            q,
            -params_eval_only.p_max_neg_pu,
            params_eval_only.p_max_pos_pu,
        )
        power_dot = np.clip(
            (q_bar - power) / params_eval_only.power_response_time_s,
            -params_eval_only.ramp_down_pu_per_s,
            params_eval_only.ramp_up_pu_per_s,
        )
        grid_dot = grid @ A.T + sg[:, None] * B + power[:, None] * E
        grid_dot[:, GridStateIndex.LOAD_DISTURBANCE_PU] = 0.0
        return np.column_stack((grid_dot, q_dot, power_dot))

    for boundary in _segment_boundaries(
        start_time_s=current_time,
        horizon_s=horizon,
        integration_step_s=step,
        history=command_history,
        params=params_eval_only,
    ):
        dt = boundary - current_time
        left_endpoint = np.nextafter(boundary, current_time)
        k1 = derivative(current_time, state)
        k2 = derivative(current_time + 0.5 * dt, state + 0.5 * dt * k1)
        k3 = derivative(current_time + 0.5 * dt, state + 0.5 * dt * k2)
        k4 = derivative(left_endpoint, state + dt * k3)
        state = state + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        if not np.all(np.isfinite(state)):
            raise ExactOracleSolveError("non-finite state during exact nonlinear rollout")
        state[:, GridStateIndex.LOAD_DISTURBANCE_PU] = load
        freq = grid_model.params.f0_hz * state[:, GridStateIndex.OMEGA_PU]
        rocof = grid_model.params.f0_hz * (
            -grid_model.params.D_pu * state[:, GridStateIndex.OMEGA_PU]
            + state[:, GridStateIndex.P_MECH_PU]
            + state[:, GRID_STATE_SIZE + 1]
            - load
        ) / grid_model.params.M_s
        max_freq = np.maximum(max_freq, np.abs(freq))
        max_rocof = np.maximum(max_rocof, np.abs(rocof))
        frequency_violation = np.maximum(np.abs(freq) - bounds.frequency_limit_hz, 0.0)
        rocof_violation = np.maximum(
            np.abs(rocof) - bounds.rocof_limit_hz_per_s,
            0.0,
        )
        objective += dt * (
            weights.q_freq * np.square(freq)
            + weights.q_integral * np.square(state[:, GridStateIndex.XI_PU_S])
            + weights.q_rocof * np.square(rocof)
            + weights.r_sg * np.square(sg)
            + weights.r_ibr * np.square(ibr)
            + weights.safety_violation_penalty
            * (np.square(frequency_violation) + np.square(rocof_violation))
        )
        current_time = boundary

    terminal_multiplier = _positive(
        terminal_cost_multiplier,
        "terminal_cost_multiplier",
    )
    terminal_freq = grid_model.params.f0_hz * state[:, GridStateIndex.OMEGA_PU]
    objective += terminal_multiplier * (
        weights.q_terminal_freq * np.square(terminal_freq)
        + weights.q_terminal_integral * np.square(state[:, GridStateIndex.XI_PU_S])
    )
    return ExactOracleRolloutResult(
        objective=objective,
        max_abs_frequency_hz=max_freq,
        max_abs_rocof_hz_per_s=max_rocof,
        terminal_state=state,
    )


class ExactNonlinearOracleController:
    """B5 evaluator Oracle; intentionally has no ordinary ``act`` method."""

    __slots__ = (
        "_context",
        "_mirror",
        "_estimator",
        "_estimated_grid_state",
        "_last_estimator_time_s",
        "_last_action",
        "_last_measurement",
        "_last_truth_mode",
        "_last_returned_action",
        "_records",
        "_is_reset",
        "_mirror_error",
    )

    def __init__(self, context: ExactOracleContext) -> None:
        if not isinstance(context, ExactOracleContext):
            raise TypeError("B5 requires an evaluator-owned ExactOracleContext")
        self._context = context
        self._mirror = HiddenModeFrequencySimulator(
            context.grid_model,
            context.mode_params_eval_only,
        )
        self._estimator = GridKalmanFilter(
            context.grid_model,
            process_noise_covariance=np.diag(context.process_noise_diagonal),
            measurement_noise_covariance=np.diag(context.measurement_noise_diagonal),
            initial_covariance=np.diag(context.initial_covariance_diagonal),
            load_random_walk_std_pu_per_s=context.load_random_walk_std_pu_per_s,
        )
        self._estimated_grid_state: FloatArray | None = None
        self._last_estimator_time_s: float | None = None
        self._last_action: ControlAction | None = None
        self._last_measurement: Measurement | None = None
        self._last_truth_mode: str | None = None
        self._last_returned_action: ControlAction | None = None
        self._records: list[ExactOracleStepRecord] = []
        self._is_reset = False
        self._mirror_error = 0.0

    @property
    def context(self) -> ExactOracleContext:
        return self._context

    @property
    def step_records(self) -> tuple[ExactOracleStepRecord, ...]:
        return tuple(self._records)

    def reset(self, initial_measurement: Measurement) -> None:
        if not isinstance(initial_measurement, Measurement):
            raise TypeError("initial_measurement must be Measurement")
        mirror_measurement = self._mirror.reset(
            self._context.seed,
            self._context.scenario_eval_only,
        )
        self._mirror_error = self._measurement_error(initial_measurement, mirror_measurement)
        if self._mirror_error > 1.0e-12:
            raise RuntimeError(
                "B5 exact mirror does not match the evaluator simulator at reset"
            )
        self._estimated_grid_state = self._estimator.reset_from_measurement(
            initial_measurement
        )
        self._last_estimator_time_s = initial_measurement.time_s
        self._last_action = None
        self._last_measurement = None
        self._last_truth_mode = None
        self._last_returned_action = None
        self._records.clear()
        self._is_reset = True

    @staticmethod
    def _measurement_error(first: Measurement, second: Measurement) -> float:
        return max(
            abs(first.time_s - second.time_s),
            abs(first.omega_pu - second.omega_pu),
            abs(first.p_mech_pu - second.p_mech_pu),
            abs(first.p_ibr_pu - second.p_ibr_pu),
            abs(first.u_sg_prev_pu - second.u_sg_prev_pu),
            abs(first.u_ibr_prev_pu - second.u_ibr_prev_pu),
        )

    def _synchronize_mirror(self, measurement: Measurement) -> None:
        if measurement.time_s < self._mirror.time_s - 1.0e-12:
            raise ValueError("B5 measurement time regressed behind its exact mirror")
        if measurement.time_s > self._mirror.time_s + 1.0e-12:
            if self._last_action is None:
                raise RuntimeError("B5 mirror cannot advance without its previous action")
            mirror_measurement, _ = self._mirror.step(self._last_action)
            if not math.isclose(
                mirror_measurement.time_s,
                measurement.time_s,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            ):
                raise RuntimeError("B5 mirror advanced to an unexpected control time")
            self._mirror_error = self._measurement_error(measurement, mirror_measurement)
            if self._mirror_error > 1.0e-11:
                raise RuntimeError(
                    "B5 exact mirror diverged from the evaluator simulator"
                )

    def _candidate_actions(self, measurement: Measurement) -> tuple[FloatArray, FloatArray]:
        dt = self._context.grid_model.params.control_period_s
        bounds = self._context.bounds
        sg_values = sorted(
            {
                clip_with_rate_limit(
                    measurement.u_sg_prev_pu + offset * bounds.sg_ramp_pu_per_s * dt,
                    measurement.u_sg_prev_pu,
                    bounds.sg_min_pu,
                    bounds.sg_max_pu,
                    bounds.sg_ramp_pu_per_s,
                    dt,
                )
                for offset in self._context.planner.sg_normalized_ramp_offsets
            }
        )
        ibr_values = sorted(
            {
                clip_with_rate_limit(
                    measurement.u_ibr_prev_pu + offset * bounds.ibr_ramp_pu_per_s * dt,
                    measurement.u_ibr_prev_pu,
                    bounds.ibr_min_pu,
                    bounds.ibr_max_pu,
                    bounds.ibr_ramp_pu_per_s,
                    dt,
                )
                for offset in self._context.planner.ibr_normalized_ramp_offsets
            }
        )
        sg, ibr = np.meshgrid(sg_values, ibr_values, indexing="ij")
        return sg.reshape(-1), ibr.reshape(-1)

    def _planning_state(self, measurement: Measurement) -> tuple[FloatArray, CommandHistory]:
        if self._estimated_grid_state is None:
            raise RuntimeError("B5 estimator state is unavailable")
        mirror_ibr = getattr(self._mirror, "_ibr_state", None)
        history = getattr(self._mirror, "_command_history", None)
        if not isinstance(mirror_ibr, IBRState) or not isinstance(history, CommandHistory):
            raise RuntimeError("B5 evaluator mirror lacks exact IBR state/history")
        # The internal filter state q is exactly reconstructible from the known
        # physical model and applied commands.  Measured output power is used
        # as the current p_b value so no unreported truth measurement is added.
        state = np.concatenate(
            (
                self._estimated_grid_state,
                np.array([mirror_ibr.q_pu, measurement.p_ibr_pu], dtype=float),
            )
        )
        return state, history

    def _validate_action(self, action: ControlAction, measurement: Measurement) -> None:
        bounds = self._context.bounds
        dt = self._context.grid_model.params.control_period_s
        checks = (
            bounds.sg_min_pu - 1.0e-12 <= action.u_sg_pu <= bounds.sg_max_pu + 1.0e-12,
            bounds.ibr_min_pu - 1.0e-12 <= action.u_ibr_pu <= bounds.ibr_max_pu + 1.0e-12,
            abs(action.u_sg_pu - measurement.u_sg_prev_pu)
            <= bounds.sg_ramp_pu_per_s * dt + 1.0e-12,
            abs(action.u_ibr_pu - measurement.u_ibr_prev_pu)
            <= bounds.ibr_ramp_pu_per_s * dt + 1.0e-12,
        )
        if not all(checks):
            raise ExactOracleSolveError("B5 selected first action violates a hard bound")

    def act_evaluation_only(
        self,
        measurement: Measurement,
        *,
        true_mode_eval_only: str,
    ) -> ControlAction:
        if not self._is_reset:
            raise RuntimeError("B5 reset must be called before act_evaluation_only")
        if not isinstance(measurement, Measurement):
            raise TypeError("measurement must be Measurement")
        mode = str(true_mode_eval_only).strip()
        expected_mode = self._context.scenario_eval_only.mode_schedule.mode_at(
            measurement.time_s
        )
        if mode != expected_mode or mode not in self._context.mode_params_eval_only:
            raise RuntimeError("B5 evaluator truth mode is inconsistent with its context")
        if self._last_measurement is not None:
            if measurement.time_s < self._last_measurement.time_s:
                raise ValueError("B5 measurement times must be nondecreasing")
            if measurement.time_s == self._last_measurement.time_s:
                if measurement != self._last_measurement or mode != self._last_truth_mode:
                    raise ValueError("B5 timestamp was reused with changed data")
                assert self._last_returned_action is not None
                return self._last_returned_action

        started = perf_counter()
        self._synchronize_mirror(measurement)
        assert self._last_estimator_time_s is not None
        if measurement.time_s > self._last_estimator_time_s:
            self._estimated_grid_state = self._estimator.update_from_measurement(
                measurement
            )
            self._last_estimator_time_s = measurement.time_s
        planning_state, history = self._planning_state(measurement)
        estimated_frequency_hz = (
            self._context.grid_model.params.f0_hz
            * planning_state[GridStateIndex.OMEGA_PU]
        )
        estimated_power_imbalance_pu = (
            -self._context.grid_model.params.D_pu
            * planning_state[GridStateIndex.OMEGA_PU]
            + planning_state[GridStateIndex.P_MECH_PU]
            + planning_state[GRID_STATE_SIZE + 1]
            - planning_state[GridStateIndex.LOAD_DISTURBANCE_PU]
        )
        idle = (
            abs(estimated_frequency_hz)
            <= self._context.planner.idle_frequency_threshold_hz
            and abs(estimated_power_imbalance_pu)
            <= self._context.planner.idle_power_imbalance_threshold_pu
        )
        if idle:
            candidate_sg = np.array([measurement.u_sg_prev_pu], dtype=float)
            candidate_ibr = np.array([measurement.u_ibr_prev_pu], dtype=float)
            estimated_rocof = (
                self._context.grid_model.params.f0_hz
                * estimated_power_imbalance_pu
                / self._context.grid_model.params.M_s
            )
            rollout = ExactOracleRolloutResult(
                objective=np.zeros(1, dtype=float),
                max_abs_frequency_hz=np.array(
                    [abs(estimated_frequency_hz)], dtype=float
                ),
                max_abs_rocof_hz_per_s=np.array(
                    [abs(estimated_rocof)], dtype=float
                ),
                terminal_state=planning_state[None, :].copy(),
            )
        else:
            candidate_sg, candidate_ibr = self._candidate_actions(measurement)
            rollout = rollout_exact_current_mode_eval_only(
                grid_model=self._context.grid_model,
                params_eval_only=self._context.mode_params_eval_only[mode],
                start_time_s=measurement.time_s,
                initial_state=planning_state,
                command_history=history,
                candidate_u_sg_pu=candidate_sg,
                candidate_u_ibr_pu=candidate_ibr,
                horizon_s=self._context.planner.horizon_s,
                integration_step_s=self._context.planner.integration_step_s,
                bounds=self._context.bounds,
                weights=self._context.weights,
                previous_u_sg_pu=measurement.u_sg_prev_pu,
                previous_u_ibr_pu=measurement.u_ibr_prev_pu,
                terminal_cost_multiplier=self._context.planner.terminal_cost_multiplier,
            )
        if not np.all(np.isfinite(rollout.objective)):
            raise ExactOracleSolveError("B5 produced non-finite candidate objectives")
        feasible = (
            rollout.max_abs_frequency_hz <= self._context.bounds.frequency_limit_hz + 1.0e-12
        ) & (
            rollout.max_abs_rocof_hz_per_s
            <= self._context.bounds.rocof_limit_hz_per_s + 1.0e-12
        )
        feasible_count = int(np.sum(feasible))
        ranked_objective = rollout.objective.copy()
        if feasible_count:
            ranked_objective[~feasible] = math.inf
        selected = int(np.argmin(ranked_objective))
        if not math.isfinite(float(ranked_objective[selected])):
            raise ExactOracleSolveError("B5 has no selectable exact-shooting candidate")
        status = (
            "optimal_idle_equilibrium_hold"
            if idle and feasible_count
            else (
                "optimal_discrete_shooting"
                if feasible_count
                else "infeasible_safety_candidate_set"
            )
        )
        outcome = "success" if feasible_count else "infeasible"
        solve_time = perf_counter() - started
        max_freq_slack = max(
            0.0,
            float(rollout.max_abs_frequency_hz[selected])
            - self._context.bounds.frequency_limit_hz,
        )
        max_rocof_slack = max(
            0.0,
            float(rollout.max_abs_rocof_hz_per_s[selected])
            - self._context.bounds.rocof_limit_hz_per_s,
        )
        action = ControlAction(
            u_sg_pu=float(candidate_sg[selected]),
            u_ibr_pu=float(candidate_ibr[selected]),
            controller_state="B5_EXACT_NONLINEAR_EVALUATION_ONLY",
            solver_status=status,
            solve_time_s=solve_time,
            max_freq_slack_hz=max_freq_slack,
        )
        self._validate_action(action, measurement)
        assert self._estimated_grid_state is not None
        self._records.append(
            ExactOracleStepRecord(
                time_s=measurement.time_s,
                true_mode_eval_only=mode,
                sg_level=self._context.sg_level,
                controller_state=action.controller_state,
                solver_status=status,
                solver_outcome=outcome,
                solver_name="B5_VECTORIZED_EXACT_RK4_SHOOTING",
                solver_version=EXACT_ORACLE_SCHEMA_VERSION,
                solve_time_s=solve_time,
                candidate_count=int(candidate_sg.size),
                safety_feasible_candidate_count=feasible_count,
                selected_candidate_index=selected,
                selected_objective=float(rollout.objective[selected]),
                predicted_max_abs_frequency_hz=float(
                    rollout.max_abs_frequency_hz[selected]
                ),
                predicted_max_abs_rocof_hz_per_s=float(
                    rollout.max_abs_rocof_hz_per_s[selected]
                ),
                current_load_estimate_pu=float(
                    self._estimated_grid_state[GridStateIndex.LOAD_DISTURBANCE_PU]
                ),
                mirror_measurement_max_abs_error=self._mirror_error,
                u_sg_pu=action.u_sg_pu,
                u_ibr_pu=action.u_ibr_pu,
                max_freq_slack_hz=max_freq_slack,
                max_rocof_slack_hz_s=max_rocof_slack,
            )
        )
        self._last_action = action
        self._last_measurement = measurement
        self._last_truth_mode = mode
        self._last_returned_action = action
        return action


def exact_oracle_action_from_truth(
    controller: object,
    measurement: Measurement,
    truth: Mapping[str, object],
) -> ControlAction:
    """Explicit runner bridge; no ordinary controller calls this function."""

    if not isinstance(controller, ExactNonlinearOracleController):
        raise TypeError("B5 callback requires ExactNonlinearOracleController")
    try:
        mode = str(truth["true_mode_eval_only"])
    except KeyError as exc:
        raise KeyError("B5 truth context lacks true_mode_eval_only") from exc
    return controller.act_evaluation_only(
        measurement,
        true_mode_eval_only=mode,
    )


__all__ = [
    "EXACT_ORACLE_SCHEMA_VERSION",
    "ExactNonlinearOracleController",
    "ExactOracleBounds",
    "ExactOracleContext",
    "ExactOraclePlannerConfig",
    "ExactOracleRolloutResult",
    "ExactOracleSolveError",
    "ExactOracleStepRecord",
    "ExactOracleWeights",
    "exact_oracle_action_from_truth",
    "rollout_exact_current_mode_eval_only",
]
