"""Self-diagnosing belief-space MPC with an auditable LQI fallback.

The runtime surface accepts only :class:`~d5freq.interfaces.Measurement`.
Mode-library component identifiers are label-free and no simulator metadata is
accepted by this module.  One online diagnostic update and one grid-estimator
update are shared by the MPC and fallback paths at each distinct timestamp.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import json
import math
from numbers import Integral, Real
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

import cvxpy as cp
import numpy as np
from numpy.typing import ArrayLike, NDArray

from d5freq.controllers.base import GridStateEstimator
from d5freq.controllers.lqi_fallback import (
    LQIFallbackConfig,
    LQIFallbackController,
)
from d5freq.estimation.grid_kalman_filter import GridKalmanFilter
from d5freq.estimation.mode_belief_filter import build_sticky_transition_matrix
from d5freq.estimation.online_diagnostic import DiagnosticOutput, OnlineModeDiagnostic
from d5freq.estimation.ood_detector import OODCalibrationArtifact, OODDetectorConfig
from d5freq.identification.model_library import ModeLibrary
from d5freq.interfaces import ControlAction, Measurement
from d5freq.models.grid_frequency import GRID_STATE_SIZE, GridFrequencyModel, GridParams
from d5freq.optimization.mpc_problem import (
    JOINT_ARX_STATE_SIZE,
    SDBMPCConfig,
    SDBMPCMode,
    SDBMPCProblem,
    SDBMPCProblemCache,
    SDBMPCBounds,
    SDBMPCWeights,
    modes_from_library,
)
from d5freq.optimization.solver_utils import (
    DEFAULT_SOLVER_PRIORITY,
    SolverOutcome,
    SolverResult,
    shift_warm_start_sequence,
    solve_cvxpy_problem,
)
from d5freq.utils.config import config_sha256, load_yaml
from d5freq.utils.hashing import sha256_file, sha256_json


FloatArray = NDArray[np.float64]


class SDControllerState(str, Enum):
    """The three executable states required by the control specification."""

    NORMAL_BELIEF_MPC = "NORMAL_BELIEF_MPC"
    ROBUST_BELIEF_MPC = "ROBUST_BELIEF_MPC"
    FALLBACK = "FALLBACK"


@runtime_checkable
class OnlineDiagnosticRuntime(Protocol):
    """Minimal label-free diagnostic interface consumed by the controller."""

    def reset(self) -> None: ...

    def step(self, measurement: Measurement) -> DiagnosticOutput: ...


@runtime_checkable
class ProblemCacheRuntime(Protocol):
    """Injectable parameterized-problem cache used by focused state tests."""

    def prepare(
        self,
        initial_state: ArrayLike,
        belief: ArrayLike,
        previous_input: ArrayLike,
        *,
        entropy_normalized: float,
        ood_suspect: bool,
        diagnostic_numerical_issue: bool = False,
    ) -> SDBMPCProblem: ...

    def clear(self) -> None: ...


SolverFunction = Callable[..., SolverResult]


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _nonnegative_real(value: object, name: str) -> float:
    normalized = _finite_real(value, name)
    if normalized < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def _nonnegative_integer(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def _readonly_vector(value: ArrayLike, size: int, name: str) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise TypeError(f"{name} must be real-valued")
    try:
        vector = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real-valued vector") from exc
    if vector.shape != (size,):
        raise ValueError(f"{name} must have shape ({size},), got {vector.shape}")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must contain only finite values")
    result = vector.copy()
    result.setflags(write=False)
    return result


def _freeze_options(
    value: Mapping[str, Mapping[str, object]],
) -> Mapping[str, Mapping[str, object]]:
    if not isinstance(value, Mapping):
        raise TypeError("solver_options must be a mapping")
    outer: dict[str, Mapping[str, object]] = {}
    for raw_solver, raw_options in value.items():
        solver = str(raw_solver).strip().upper()
        if not solver:
            raise ValueError("solver_options keys must not be empty")
        if not isinstance(raw_options, Mapping):
            raise TypeError("each solver_options value must be a mapping")
        outer[solver] = MappingProxyType(dict(raw_options))
    return MappingProxyType(outer)


@dataclass(frozen=True, slots=True)
class SDBMPCControllerConfig:
    """Online solver, rejection, fallback, and recovery policy."""

    max_acceptable_freq_slack_hz: float = 0.02
    max_acceptable_rocof_slack_hz_per_s: float = 0.02
    max_acceptable_power_slack_pu: float = 0.02
    solve_timeout_s: float = 0.20
    warm_start: bool = True
    solver_priority: tuple[str, ...] = DEFAULT_SOLVER_PRIORITY
    solver_options: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    recovery_hold_steps: int = 10
    return_blend_steps: int = 10
    enable_ood_fallback: bool = True
    input_feasibility_tolerance: float = 1.0e-7
    precompile_on_reset: bool = True

    def __post_init__(self) -> None:
        for name in (
            "max_acceptable_freq_slack_hz",
            "max_acceptable_rocof_slack_hz_per_s",
            "max_acceptable_power_slack_pu",
            "input_feasibility_tolerance",
        ):
            object.__setattr__(self, name, _nonnegative_real(getattr(self, name), name))
        timeout = _finite_real(self.solve_timeout_s, "solve_timeout_s")
        if timeout <= 0.0:
            raise ValueError("solve_timeout_s must be positive")
        object.__setattr__(self, "solve_timeout_s", timeout)
        for name in ("recovery_hold_steps", "return_blend_steps"):
            value = _nonnegative_integer(getattr(self, name), name)
            if name == "return_blend_steps" and value == 0:
                raise ValueError("return_blend_steps must be positive")
            object.__setattr__(self, name, value)
        for name in ("warm_start", "enable_ood_fallback", "precompile_on_reset"):
            if not isinstance(getattr(self, name), (bool, np.bool_)):
                raise TypeError(f"{name} must be boolean")
            object.__setattr__(self, name, bool(getattr(self, name)))
        if isinstance(self.solver_priority, (str, bytes)):
            raise TypeError("solver_priority must be a sequence")
        priority = tuple(str(value).strip().upper() for value in self.solver_priority)
        if not priority or any(not value for value in priority):
            raise ValueError("solver_priority must contain non-empty solver names")
        if len(set(priority)) != len(priority):
            raise ValueError("solver_priority must not contain duplicates")
        object.__setattr__(self, "solver_priority", priority)
        object.__setattr__(self, "solver_options", _freeze_options(self.solver_options))


@dataclass(frozen=True, slots=True)
class SDBMPCProvenance:
    """Hashes bound by the production file factory."""

    base_config_sha256: str
    mpc_config_sha256: str
    mode_library_file_sha256: str
    mode_library_logical_sha256: str
    ood_calibration_file_sha256: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = str(getattr(self, name)).lower()
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class PrecompileRecord:
    """Immutable reset-time canonicalization evidence."""

    solver: str | None
    success: bool
    wall_time_s: float
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.solver is not None and not str(self.solver).strip():
            raise ValueError("solver must be non-empty when recorded")
        object.__setattr__(self, "wall_time_s", _nonnegative_real(self.wall_time_s, "wall_time_s"))


@dataclass(frozen=True, slots=True)
class FallbackEvent:
    """Immutable snapshot of one contiguous fallback interval."""

    event_id: int
    started_time_s: float
    last_fallback_time_s: float
    ended_time_s: float | None
    fallback_steps: int
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        event_id = _nonnegative_integer(self.event_id, "event_id")
        steps = _nonnegative_integer(self.fallback_steps, "fallback_steps")
        started = _nonnegative_real(self.started_time_s, "started_time_s")
        last = _nonnegative_real(self.last_fallback_time_s, "last_fallback_time_s")
        if last < started:
            raise ValueError("last_fallback_time_s precedes started_time_s")
        ended = self.ended_time_s
        if ended is not None:
            ended = _nonnegative_real(ended, "ended_time_s")
            if ended < last:
                raise ValueError("ended_time_s precedes the final fallback action")
        reasons = tuple(str(reason).strip() for reason in self.reasons)
        if not reasons or any(not reason for reason in reasons):
            raise ValueError("fallback event reasons must be non-empty")
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "fallback_steps", steps)
        object.__setattr__(self, "started_time_s", started)
        object.__setattr__(self, "last_fallback_time_s", last)
        object.__setattr__(self, "ended_time_s", ended)
        object.__setattr__(self, "reasons", reasons)

    @property
    def active(self) -> bool:
        return self.ended_time_s is None

    @property
    def duration_s(self) -> float:
        end = self.last_fallback_time_s if self.ended_time_s is None else self.ended_time_s
        return float(end - self.started_time_s)

    def to_log_record(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "started_time_s": self.started_time_s,
            "last_fallback_time_s": self.last_fallback_time_s,
            "ended_time_s": self.ended_time_s,
            "duration_s": self.duration_s,
            "fallback_steps": self.fallback_steps,
            "reasons": list(self.reasons),
            "active": self.active,
        }


@dataclass(frozen=True, slots=True)
class SDBMPCStepRecord:
    """Complete immutable controller-side record for one executed action."""

    time_s: float
    sample_index: int
    controller_state: str
    diagnostic_state: str
    mode_belief: FloatArray
    map_mode: int
    belief_entropy: float
    ood_pvalue: float
    solver_status: str
    solver_outcome: str
    solver_name: str | None
    solver_version: str | None
    solve_time_s: float
    problem_prepare_time_s: float
    solver_objective: float | None
    solver_iterations: int | None
    risk_component_ids: tuple[int, ...]
    max_freq_slack_hz: float
    max_rocof_slack_hz_per_s: float
    max_power_slack_pu: float
    fallback_event_id: int | None
    trigger_reasons: tuple[str, ...]
    fallback_event_reasons: tuple[str, ...]
    fallback_steps: int
    recovery_hold_count: int
    recovery_blend_alpha: float
    u_sg_pu: float
    u_ibr_pu: float
    fallback_u_sg_pu: float | None
    fallback_u_ibr_pu: float | None
    mpc_u_sg_pu: float | None
    mpc_u_ibr_pu: float | None
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        time_s = _nonnegative_real(self.time_s, "time_s")
        sample_index = _nonnegative_integer(self.sample_index, "sample_index")
        belief = _readonly_vector(self.mode_belief, np.asarray(self.mode_belief).size, "mode_belief")
        if belief.size == 0 or np.any(belief < 0.0) or not math.isclose(
            float(np.sum(belief)), 1.0, rel_tol=0.0, abs_tol=1.0e-10
        ):
            raise ValueError("mode_belief must be non-negative and sum to one")
        map_mode = _nonnegative_integer(self.map_mode, "map_mode")
        if map_mode >= belief.size:
            raise ValueError("map_mode is outside mode_belief")
        entropy = _finite_real(self.belief_entropy, "belief_entropy")
        pvalue = _finite_real(self.ood_pvalue, "ood_pvalue")
        alpha = _finite_real(self.recovery_blend_alpha, "recovery_blend_alpha")
        if not 0.0 <= entropy <= 1.0 or not 0.0 <= pvalue <= 1.0:
            raise ValueError("belief entropy and OOD p-value must lie in [0, 1]")
        if not 0.0 <= alpha <= 1.0:
            raise ValueError("recovery_blend_alpha must lie in [0, 1]")
        for name in (
            "solve_time_s",
            "problem_prepare_time_s",
            "max_freq_slack_hz",
            "max_rocof_slack_hz_per_s",
            "max_power_slack_pu",
        ):
            object.__setattr__(self, name, _nonnegative_real(getattr(self, name), name))
        for name in ("u_sg_pu", "u_ibr_pu"):
            object.__setattr__(self, name, _finite_real(getattr(self, name), name))
        for name in (
            "fallback_u_sg_pu",
            "fallback_u_ibr_pu",
            "mpc_u_sg_pu",
            "mpc_u_ibr_pu",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _finite_real(value, name))
        object.__setattr__(self, "time_s", time_s)
        object.__setattr__(self, "sample_index", sample_index)
        object.__setattr__(self, "mode_belief", belief)
        object.__setattr__(self, "map_mode", map_mode)
        object.__setattr__(self, "belief_entropy", entropy)
        object.__setattr__(self, "ood_pvalue", pvalue)
        object.__setattr__(self, "recovery_blend_alpha", alpha)
        object.__setattr__(self, "fallback_steps", _nonnegative_integer(self.fallback_steps, "fallback_steps"))
        object.__setattr__(self, "recovery_hold_count", _nonnegative_integer(self.recovery_hold_count, "recovery_hold_count"))

    def to_log_record(self) -> dict[str, object]:
        record: dict[str, object] = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "mode_belief"
        }
        record["trigger_reasons"] = list(self.trigger_reasons)
        record["fallback_event_reasons"] = list(self.fallback_event_reasons)
        record["risk_component_ids"] = list(self.risk_component_ids)
        for index, probability in enumerate(self.mode_belief):
            record[f"belief_{index}"] = float(probability)
        return record


@dataclass(slots=True)
class _ActiveFallback:
    event_id: int
    started_time_s: float
    last_fallback_time_s: float
    fallback_steps: int
    reasons: list[str]

    def add_reasons(self, reasons: Sequence[str]) -> None:
        for reason in reasons:
            if reason not in self.reasons:
                self.reasons.append(reason)

    def snapshot(self, ended_time_s: float | None = None) -> FallbackEvent:
        return FallbackEvent(
            event_id=self.event_id,
            started_time_s=self.started_time_s,
            last_fallback_time_s=self.last_fallback_time_s,
            ended_time_s=ended_time_s,
            fallback_steps=self.fallback_steps,
            reasons=tuple(self.reasons),
        )


@dataclass(slots=True)
class _MPCProposal:
    sequence: FloatArray | None
    result: SolverResult | None
    status: str
    outcome: str
    prepare_time_s: float
    risk_component_ids: tuple[int, ...]
    max_freq_slack_hz: float = 0.0
    max_rocof_slack_hz_per_s: float = 0.0
    max_power_slack_pu: float = 0.0
    rejection_reasons: tuple[str, ...] = ()
    error_type: str | None = None
    error_message: str | None = None

    @property
    def accepted(self) -> bool:
        return self.sequence is not None and not self.rejection_reasons


class SDBMPCController:
    """Belief-aware shared-input MPC with equations-(70)--(75) fallback."""

    def __init__(
        self,
        grid_model: GridFrequencyModel,
        modes: Sequence[SDBMPCMode],
        diagnostic: OnlineDiagnosticRuntime,
        *,
        mpc_config: SDBMPCConfig | None = None,
        controller_config: SDBMPCControllerConfig | None = None,
        estimator: GridStateEstimator | None = None,
        fallback_config: LQIFallbackConfig | None = None,
        problem_cache: ProblemCacheRuntime | None = None,
        solve_function: SolverFunction = solve_cvxpy_problem,
        provenance: SDBMPCProvenance | None = None,
    ) -> None:
        if not isinstance(grid_model, GridFrequencyModel):
            raise TypeError("grid_model must be a GridFrequencyModel")
        mode_tuple = tuple(modes)
        if not mode_tuple or not all(isinstance(mode, SDBMPCMode) for mode in mode_tuple):
            raise TypeError("modes must be a non-empty sequence of SDBMPCMode")
        component_ids = tuple(mode.component_id for mode in mode_tuple)
        if component_ids != tuple(range(len(mode_tuple))):
            raise ValueError("mode component IDs must be contiguous and ordered")
        if not isinstance(diagnostic, OnlineDiagnosticRuntime):
            raise TypeError("diagnostic must provide reset() and step(measurement)")
        settings = SDBMPCConfig() if mpc_config is None else mpc_config
        if not isinstance(settings, SDBMPCConfig):
            raise TypeError("mpc_config must be an SDBMPCConfig")
        policy = (
            SDBMPCControllerConfig()
            if controller_config is None
            else controller_config
        )
        if not isinstance(policy, SDBMPCControllerConfig):
            raise TypeError("controller_config must be an SDBMPCControllerConfig")
        if not math.isclose(
            settings.sample_time_s,
            grid_model.params.control_period_s,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise ValueError("MPC sample time must equal the grid control period")
        if not math.isclose(
            settings.f0_hz,
            grid_model.params.f0_hz,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise ValueError("MPC nominal frequency must equal the grid model")

        resolved_estimator: GridStateEstimator = (
            GridKalmanFilter(grid_model) if estimator is None else estimator
        )
        if not isinstance(resolved_estimator, GridStateEstimator):
            raise TypeError("estimator must satisfy GridStateEstimator")
        if fallback_config is None:
            fallback_settings = LQIFallbackConfig(
                u_sg_min_pu=settings.bounds.u_min_pu[0],
                u_sg_max_pu=settings.bounds.u_max_pu[0],
                u_sg_ramp_pu_per_s=settings.bounds.ramp_pu_per_s[0],
                ibr_withdraw_rate_pu_per_s=settings.bounds.ramp_pu_per_s[1],
            )
        else:
            fallback_settings = fallback_config
        if not isinstance(fallback_settings, LQIFallbackConfig):
            raise TypeError("fallback_config must be an LQIFallbackConfig")
        self._validate_fallback_limits(settings, fallback_settings)

        resolved_cache: ProblemCacheRuntime = (
            SDBMPCProblemCache(mode_tuple, config=settings)
            if problem_cache is None
            else problem_cache
        )
        if not isinstance(resolved_cache, ProblemCacheRuntime):
            raise TypeError("problem_cache must provide prepare() and clear()")
        if not callable(solve_function):
            raise TypeError("solve_function must be callable")
        if provenance is not None and not isinstance(provenance, SDBMPCProvenance):
            raise TypeError("provenance must be an SDBMPCProvenance")

        self._grid_model = grid_model
        self._modes = mode_tuple
        self._component_ids = component_ids
        self._diagnostic = diagnostic
        self._mpc_config = settings
        self._controller_config = policy
        self._estimator = resolved_estimator
        self._fallback = LQIFallbackController(
            grid_model,
            config=fallback_settings,
            estimator=resolved_estimator,
        )
        self._problem_cache = resolved_cache
        self._solve_function = solve_function
        self._provenance = provenance

        self._estimated_state: FloatArray | None = None
        self._last_estimator_time_s: float | None = None
        self._previous_measurement: Measurement | None = None
        self._reset_measurement: Measurement | None = None
        self._cached_diagnostic: DiagnosticOutput | None = None
        self._cached_diagnostic_error: Exception | None = None
        self._cached_diagnostic_time_s: float | None = None
        self._last_action_measurement: Measurement | None = None
        self._last_action: ControlAction | None = None
        self._warm_start: FloatArray | None = None
        self._last_problem: SDBMPCProblem | None = None
        self._state = SDControllerState.ROBUST_BELIEF_MPC
        self._active_fallback: _ActiveFallback | None = None
        self._completed_fallback_events: list[FallbackEvent] = []
        self._next_fallback_event_id = 0
        self._recovery_hold_count = 0
        self._recovery_blend_step = 0
        self._step_records: list[SDBMPCStepRecord] = []
        self._precompile_records: list[PrecompileRecord] = []
        self._is_reset = False

    @staticmethod
    def _validate_fallback_limits(
        mpc_config: SDBMPCConfig,
        fallback_config: LQIFallbackConfig,
    ) -> None:
        bounds = mpc_config.bounds
        if not (
            math.isclose(
                fallback_config.u_sg_min_pu,
                bounds.u_min_pu[0],
                rel_tol=0.0,
                abs_tol=1.0e-12,
            )
            and math.isclose(
                fallback_config.u_sg_max_pu,
                bounds.u_max_pu[0],
                rel_tol=0.0,
                abs_tol=1.0e-12,
            )
        ):
            raise ValueError(
                "fallback SG bounds must equal MPC bounds so every MPC action "
                "can transition safely"
            )
        if fallback_config.u_sg_ramp_pu_per_s > bounds.ramp_pu_per_s[0]:
            raise ValueError("fallback SG ramp must not exceed the MPC SG ramp")
        if fallback_config.ibr_withdraw_rate_pu_per_s > bounds.ramp_pu_per_s[1]:
            raise ValueError("IBR withdrawal rate must not exceed the MPC IBR ramp")

    @property
    def state(self) -> SDControllerState:
        return self._state

    @property
    def modes(self) -> tuple[SDBMPCMode, ...]:
        return self._modes

    @property
    def mpc_config(self) -> SDBMPCConfig:
        return self._mpc_config

    @property
    def controller_config(self) -> SDBMPCControllerConfig:
        return self._controller_config

    @property
    def provenance(self) -> SDBMPCProvenance | None:
        return self._provenance

    @property
    def estimated_state(self) -> FloatArray:
        if self._estimated_state is None:
            raise RuntimeError("controller must be reset before reading estimated_state")
        return self._estimated_state.copy()

    @property
    def step_records(self) -> tuple[SDBMPCStepRecord, ...]:
        return tuple(self._step_records)

    @property
    def last_step_record(self) -> SDBMPCStepRecord:
        if not self._step_records:
            raise RuntimeError("no action has been executed")
        return self._step_records[-1]

    @property
    def precompile_records(self) -> tuple[PrecompileRecord, ...]:
        return tuple(self._precompile_records)

    @property
    def fallback_events(self) -> tuple[FallbackEvent, ...]:
        events = list(self._completed_fallback_events)
        if self._active_fallback is not None:
            events.append(self._active_fallback.snapshot())
        return tuple(events)

    def reset(self, initial_measurement: Measurement) -> None:
        """Reset all runtime state and precompile the all-component template."""

        if not isinstance(initial_measurement, Measurement):
            raise TypeError("initial_measurement must be a Measurement")
        previous_input = np.array(
            [
                initial_measurement.u_sg_prev_pu,
                initial_measurement.u_ibr_prev_pu,
            ],
            dtype=np.float64,
        )
        self._validate_previous_input(previous_input)

        self._problem_cache.clear()
        self._last_problem = None
        self._diagnostic.reset()
        self._fallback.reset(initial_measurement)
        estimate = np.asarray(self._fallback.estimated_state, dtype=np.float64)
        if estimate.shape != (GRID_STATE_SIZE,) or not np.all(np.isfinite(estimate)):
            raise ValueError("reset estimator returned an invalid grid state")
        self._estimated_state = estimate.copy()
        self._last_estimator_time_s = initial_measurement.time_s
        self._previous_measurement = initial_measurement
        self._reset_measurement = initial_measurement
        self._last_action_measurement = None
        self._last_action = None
        self._warm_start = None
        self._state = SDControllerState.ROBUST_BELIEF_MPC
        self._active_fallback = None
        self._completed_fallback_events.clear()
        self._next_fallback_event_id = 0
        self._recovery_hold_count = 0
        self._recovery_blend_step = 0
        self._step_records.clear()
        self._precompile_records.clear()

        self._cached_diagnostic = None
        self._cached_diagnostic_error = None
        self._cached_diagnostic_time_s = initial_measurement.time_s
        try:
            output = self._diagnostic.step(initial_measurement)
            self._cached_diagnostic = self._validate_diagnostic_output(output)
        except Exception as exc:
            self._cached_diagnostic_error = exc

        self._precompile_all_modes(initial_measurement, previous_input)
        self._is_reset = True

    def _precompile_all_modes(
        self,
        measurement: Measurement,
        previous_input: FloatArray,
    ) -> None:
        if not self._controller_config.precompile_on_reset:
            return
        assert self._estimated_state is not None
        state = self._joint_state(measurement)
        uniform = np.full(len(self._modes), 1.0 / len(self._modes), dtype=np.float64)
        try:
            bundle = self._problem_cache.prepare(
                state,
                uniform,
                previous_input,
                entropy_normalized=1.0 if len(self._modes) > 1 else 0.0,
                ood_suspect=True,
                diagnostic_numerical_issue=False,
            )
            self._last_problem = bundle
        except Exception as exc:
            self._precompile_records.append(
                PrecompileRecord(
                    solver=None,
                    success=False,
                    wall_time_s=0.0,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            )
            return
        installed = {str(value).upper() for value in cp.installed_solvers()}
        solver = next(
            (
                candidate
                for candidate in self._controller_config.solver_priority
                if candidate in installed
            ),
            None,
        )
        if solver is None:
            self._discard_warm_start(bundle)
            self._precompile_records.append(
                PrecompileRecord(
                    solver=None,
                    success=False,
                    wall_time_s=0.0,
                    error_type="SolverNotInstalled",
                    error_message="no configured solver is installed",
                )
            )
            return
        start = perf_counter()
        try:
            reported_wall = float(bundle.precompile(solver))
            wall = max(reported_wall, perf_counter() - start)
            bundle.set_warm_start(None)
            self._precompile_records.append(
                PrecompileRecord(solver=solver, success=True, wall_time_s=wall)
            )
        except Exception as exc:
            self._discard_warm_start(bundle)
            self._precompile_records.append(
                PrecompileRecord(
                    solver=solver,
                    success=False,
                    wall_time_s=perf_counter() - start,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            )

    def act(self, measurement: Measurement) -> ControlAction:
        """Update diagnosis/estimation once and execute one safe control action."""

        if not isinstance(measurement, Measurement):
            raise TypeError("measurement must be a Measurement")
        if not self._is_reset or self._reset_measurement is None:
            raise RuntimeError("reset must be called before act")
        if self._last_action_measurement is not None:
            if measurement.time_s < self._last_action_measurement.time_s:
                raise ValueError("measurement times must be nondecreasing")
            if measurement.time_s == self._last_action_measurement.time_s:
                if measurement != self._last_action_measurement:
                    raise ValueError("a timestamp cannot be reused with changed signals")
                assert self._last_action is not None
                return self._last_action
        elif measurement.time_s < self._reset_measurement.time_s:
            raise ValueError("measurement precedes the reset timestamp")
        elif (
            measurement.time_s == self._reset_measurement.time_s
            and measurement != self._reset_measurement
        ):
            raise ValueError("the reset timestamp cannot be reused with changed signals")

        estimator_error: Exception | None = None
        assert self._last_estimator_time_s is not None
        if measurement.time_s > self._last_estimator_time_s:
            try:
                estimate = np.asarray(
                    self._estimator.update_from_measurement(measurement),
                    dtype=np.float64,
                )
                if estimate.shape != (GRID_STATE_SIZE,) or not np.all(np.isfinite(estimate)):
                    raise ValueError("estimator returned an invalid grid state")
                self._estimated_state = estimate.copy()
            except Exception as exc:
                estimator_error = exc
            self._last_estimator_time_s = measurement.time_s

        diagnostic, diagnostic_error = self._diagnose_once(measurement)
        belief, map_mode, entropy, pvalue, diagnostic_state = self._diagnostic_snapshot(
            diagnostic
        )
        previous_input = np.array(
            [measurement.u_sg_prev_pu, measurement.u_ibr_prev_pu],
            dtype=np.float64,
        )
        self._validate_previous_input(previous_input)

        immediate_reasons: list[str] = []
        if estimator_error is not None:
            immediate_reasons.append("estimator_error")
        if diagnostic_error is not None:
            immediate_reasons.append("diagnostic_error")
        if self._controller_config.enable_ood_fallback:
            if diagnostic_state == "OOD_ACTIVE":
                immediate_reasons.append("ood_active")
            elif diagnostic_state == "RECOVERY":
                immediate_reasons.append("ood_recovery")

        target_state = self._mpc_state(diagnostic_state, entropy)
        proposal: _MPCProposal | None = None
        blend_alpha = 0.0
        trigger_reasons: tuple[str, ...] = tuple(immediate_reasons)
        fallback_candidate: ControlAction | None = None
        mpc_candidate: FloatArray | None = None

        if immediate_reasons:
            self._enter_or_extend_fallback(measurement.time_s, immediate_reasons)
            self._reset_recovery()
            self._warm_start = None
            action = self._fallback_action(
                measurement,
                solver_status="not_run_fallback_trigger",
                solve_time_s=0.0,
                max_freq_slack_hz=0.0,
            )
            fallback_candidate = action
        elif self._active_fallback is not None:
            if diagnostic_state != "KNOWN":
                trigger_reasons = ("diagnostic_not_known",)
                self._active_fallback.add_reasons(trigger_reasons)
                self._reset_recovery()
                self._discard_warm_start()
                action = self._fallback_action(
                    measurement,
                    solver_status="not_run_fallback_diagnostic",
                    solve_time_s=0.0,
                    max_freq_slack_hz=0.0,
                )
                fallback_candidate = action
            elif self._recovery_hold_count < self._controller_config.recovery_hold_steps:
                self._recovery_hold_count += 1
                action = self._fallback_action(
                    measurement,
                    solver_status="not_run_recovery_hold",
                    solve_time_s=0.0,
                    max_freq_slack_hz=0.0,
                )
                fallback_candidate = action
            else:
                proposal = self._solve_mpc(
                    measurement,
                    belief,
                    entropy,
                    diagnostic_state,
                    previous_input,
                )
                if not proposal.accepted:
                    trigger_reasons = proposal.rejection_reasons
                    self._active_fallback.add_reasons(trigger_reasons)
                    self._reset_recovery()
                    self._warm_start = None
                    action = self._fallback_action(
                        measurement,
                        solver_status=proposal.status,
                        solve_time_s=self._proposal_solve_time(proposal),
                        max_freq_slack_hz=proposal.max_freq_slack_hz,
                    )
                    fallback_candidate = action
                else:
                    assert proposal.sequence is not None
                    mpc_candidate = proposal.sequence[:, 0].copy()
                    fallback_candidate = self._fallback_action(
                        measurement,
                        solver_status=proposal.status,
                        solve_time_s=self._proposal_solve_time(proposal),
                        max_freq_slack_hz=proposal.max_freq_slack_hz,
                    )
                    self._recovery_blend_step += 1
                    blend_alpha = min(
                        1.0,
                        self._recovery_blend_step
                        / self._controller_config.return_blend_steps,
                    )
                    blended = (
                        (1.0 - blend_alpha)
                        * np.array(
                            [
                                fallback_candidate.u_sg_pu,
                                fallback_candidate.u_ibr_pu,
                            ]
                        )
                        + blend_alpha * mpc_candidate
                    )
                    if blend_alpha >= 1.0:
                        self._close_fallback(measurement.time_s)
                        self._state = target_state
                    else:
                        self._state = SDControllerState.FALLBACK
                    action = ControlAction(
                        u_sg_pu=float(blended[0]),
                        u_ibr_pu=float(blended[1]),
                        controller_state=self._state.value,
                        solver_status=proposal.status,
                        solve_time_s=self._proposal_solve_time(proposal),
                        max_freq_slack_hz=proposal.max_freq_slack_hz,
                    )
        else:
            proposal = self._solve_mpc(
                measurement,
                belief,
                entropy,
                diagnostic_state,
                previous_input,
            )
            if proposal.accepted:
                assert proposal.sequence is not None
                mpc_candidate = proposal.sequence[:, 0].copy()
                self._state = target_state
                action = ControlAction(
                    u_sg_pu=float(mpc_candidate[0]),
                    u_ibr_pu=float(mpc_candidate[1]),
                    controller_state=self._state.value,
                    solver_status=proposal.status,
                    solve_time_s=self._proposal_solve_time(proposal),
                    max_freq_slack_hz=proposal.max_freq_slack_hz,
                )
            else:
                trigger_reasons = proposal.rejection_reasons
                self._enter_or_extend_fallback(measurement.time_s, trigger_reasons)
                self._reset_recovery()
                self._warm_start = None
                action = self._fallback_action(
                    measurement,
                    solver_status=proposal.status,
                    solve_time_s=self._proposal_solve_time(proposal),
                    max_freq_slack_hz=proposal.max_freq_slack_hz,
                )
                fallback_candidate = action

        if self._state is SDControllerState.FALLBACK:
            self._note_fallback_action(measurement.time_s)
            if action.controller_state != SDControllerState.FALLBACK.value:
                action = ControlAction(
                    u_sg_pu=action.u_sg_pu,
                    u_ibr_pu=action.u_ibr_pu,
                    controller_state=SDControllerState.FALLBACK.value,
                    solver_status=action.solver_status,
                    solve_time_s=action.solve_time_s,
                    max_freq_slack_hz=action.max_freq_slack_hz,
                )

        record = self._make_step_record(
            measurement=measurement,
            action=action,
            belief=belief,
            map_mode=map_mode,
            entropy=entropy,
            pvalue=pvalue,
            diagnostic_state=diagnostic_state,
            proposal=proposal,
            trigger_reasons=trigger_reasons,
            blend_alpha=blend_alpha,
            fallback_candidate=fallback_candidate,
            mpc_candidate=mpc_candidate,
            external_error=estimator_error or diagnostic_error,
        )
        self._step_records.append(record)
        self._previous_measurement = measurement
        self._last_action_measurement = measurement
        self._last_action = action
        return action

    def _diagnose_once(
        self,
        measurement: Measurement,
    ) -> tuple[DiagnosticOutput | None, Exception | None]:
        if self._cached_diagnostic_time_s == measurement.time_s:
            return self._cached_diagnostic, self._cached_diagnostic_error
        try:
            output = self._validate_diagnostic_output(
                self._diagnostic.step(measurement)
            )
            error: Exception | None = None
        except Exception as exc:
            output = None
            error = exc
        self._cached_diagnostic = output
        self._cached_diagnostic_error = error
        self._cached_diagnostic_time_s = measurement.time_s
        return output, error

    def _validate_diagnostic_output(
        self,
        output: DiagnosticOutput,
    ) -> DiagnosticOutput:
        required = (
            "mode_belief",
            "map_mode",
            "belief_entropy",
            "ood_pvalue",
            "diagnostic_state",
        )
        if any(not hasattr(output, name) for name in required):
            raise TypeError("diagnostic output is missing required fields")
        belief = np.asarray(output.mode_belief, dtype=np.float64)
        if belief.shape != (len(self._modes),) or not np.all(np.isfinite(belief)):
            raise ValueError("diagnostic belief does not match the native modes")
        if np.any(belief < 0.0) or not math.isclose(
            float(np.sum(belief)), 1.0, rel_tol=0.0, abs_tol=1.0e-10
        ):
            raise ValueError("diagnostic belief must be a probability vector")
        entropy = float(output.belief_entropy)
        pvalue = float(output.ood_pvalue)
        if not math.isfinite(entropy) or not 0.0 <= entropy <= 1.0:
            raise ValueError("diagnostic belief entropy is invalid")
        if not math.isfinite(pvalue) or not 0.0 <= pvalue <= 1.0:
            raise ValueError("diagnostic OOD p-value is invalid")
        state = str(output.diagnostic_state)
        if state not in {"KNOWN", "SUSPECT", "OOD_ACTIVE", "RECOVERY"}:
            raise ValueError("diagnostic state is invalid")
        map_mode = int(output.map_mode)
        if map_mode != int(np.argmax(belief)):
            raise ValueError("diagnostic MAP component disagrees with belief")
        return output

    def _diagnostic_snapshot(
        self,
        output: DiagnosticOutput | None,
    ) -> tuple[FloatArray, int, float, float, str]:
        if output is None:
            belief = np.full(
                len(self._modes), 1.0 / len(self._modes), dtype=np.float64
            )
            entropy = 1.0 if len(self._modes) > 1 else 0.0
            return belief, 0, entropy, 0.0, "DIAGNOSTIC_ERROR"
        return (
            np.asarray(output.mode_belief, dtype=np.float64).copy(),
            int(output.map_mode),
            float(output.belief_entropy),
            float(output.ood_pvalue),
            str(output.diagnostic_state),
        )

    def _joint_state(self, measurement: Measurement) -> FloatArray:
        if self._estimated_state is None or self._previous_measurement is None:
            raise RuntimeError("controller state is not initialized")
        state = np.empty(JOINT_ARX_STATE_SIZE, dtype=np.float64)
        state[:GRID_STATE_SIZE] = self._estimated_state
        state[5] = measurement.p_ibr_pu
        state[6] = self._previous_measurement.p_ibr_pu
        state[7] = measurement.u_ibr_prev_pu
        state[8] = self._previous_measurement.omega_pu
        state[9] = 1.0
        if not np.all(np.isfinite(state)):
            raise FloatingPointError("joint controller state became non-finite")
        return state

    def _validate_previous_input(self, previous_input: FloatArray) -> None:
        if previous_input.shape != (2,) or not np.all(np.isfinite(previous_input)):
            raise ValueError("previous executable input must be a finite two-vector")
        tolerance = self._controller_config.input_feasibility_tolerance
        if np.any(previous_input < self._mpc_config.bounds.lower - tolerance) or np.any(
            previous_input > self._mpc_config.bounds.upper + tolerance
        ):
            raise ValueError("previous executable input is outside MPC bounds")

    def _mpc_state(
        self,
        diagnostic_state: str,
        entropy: float,
    ) -> SDControllerState:
        robust = bool(
            diagnostic_state != "KNOWN"
            or entropy >= self._mpc_config.entropy_use_all_modes
        )
        return (
            SDControllerState.ROBUST_BELIEF_MPC
            if robust
            else SDControllerState.NORMAL_BELIEF_MPC
        )

    def _solve_mpc(
        self,
        measurement: Measurement,
        belief: FloatArray,
        entropy: float,
        diagnostic_state: str,
        previous_input: FloatArray,
    ) -> _MPCProposal:
        prepare_start = perf_counter()
        bundle: SDBMPCProblem | None = None
        try:
            bundle = self._problem_cache.prepare(
                self._joint_state(measurement),
                belief,
                previous_input,
                entropy_normalized=entropy,
                ood_suspect=diagnostic_state != "KNOWN",
                diagnostic_numerical_issue=False,
            )
            self._last_problem = bundle
            bundle.set_warm_start(
                self._warm_start if self._controller_config.warm_start else None
            )
        except Exception as exc:
            self._discard_warm_start(bundle)
            return _MPCProposal(
                sequence=None,
                result=None,
                status="problem_prepare_error",
                outcome="error",
                prepare_time_s=perf_counter() - prepare_start,
                risk_component_ids=(),
                rejection_reasons=("problem_prepare_error",),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        prepare_time = perf_counter() - prepare_start
        risk_ids = tuple(int(value) for value in bundle.risk_component_ids)
        try:
            result = self._solve_function(
                bundle.problem,
                solution_variables=bundle.solution_variables(),
                solver_priority=self._controller_config.solver_priority,
                solver_options=self._controller_config.solver_options,
                timeout_s=self._controller_config.solve_timeout_s,
                warm_start=self._controller_config.warm_start,
            )
        except Exception as exc:
            self._discard_warm_start(bundle)
            return _MPCProposal(
                sequence=None,
                result=None,
                status="solver_exception",
                outcome="error",
                prepare_time_s=prepare_time,
                risk_component_ids=risk_ids,
                rejection_reasons=("solver_exception",),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        if not isinstance(result, SolverResult):
            self._discard_warm_start(bundle)
            return _MPCProposal(
                sequence=None,
                result=None,
                status="invalid_solver_result",
                outcome="error",
                prepare_time_s=prepare_time,
                risk_component_ids=risk_ids,
                rejection_reasons=("invalid_solver_result",),
                error_type="TypeError",
                error_message="solve_function did not return SolverResult",
            )
        if not result.success:
            reason = (
                "solver_timeout"
                if result.timed_out
                else f"solver_{result.outcome.value}"
            )
            self._discard_warm_start(bundle)
            return _MPCProposal(
                sequence=None,
                result=result,
                status=result.status,
                outcome=result.outcome.value,
                prepare_time_s=prepare_time,
                risk_component_ids=risk_ids,
                rejection_reasons=(reason,),
                error_type=result.error_type,
                error_message=result.error_message,
            )

        try:
            sequence = np.asarray(result.value("shared_input"), dtype=np.float64)
            expected_shape = (2, self._mpc_config.horizon_steps)
            if sequence.shape != expected_shape or not np.all(np.isfinite(sequence)):
                raise FloatingPointError(
                    f"shared input must be finite with shape {expected_shape}"
                )
            freq_slack = self._maximum_slack(result.value("freq_slack_hz"))
            rocof_slack = self._maximum_slack(
                result.value("rocof_slack_hz_per_s")
            )
            power_slack = self._maximum_slack(result.value("power_slack_pu"))
        except Exception as exc:
            self._discard_warm_start(bundle)
            return _MPCProposal(
                sequence=None,
                result=result,
                status="nonfinite_solution",
                outcome=SolverOutcome.NONFINITE.value,
                prepare_time_s=prepare_time,
                risk_component_ids=risk_ids,
                rejection_reasons=("solver_nonfinite",),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        rejection: list[str] = []
        if freq_slack > self._controller_config.max_acceptable_freq_slack_hz:
            rejection.append("frequency_slack")
        if rocof_slack > self._controller_config.max_acceptable_rocof_slack_hz_per_s:
            rejection.append("rocof_slack")
        if power_slack > self._controller_config.max_acceptable_power_slack_pu:
            rejection.append("power_slack")
        if not self._sequence_is_executable(sequence, previous_input):
            rejection.append("solution_constraint_violation")
        if rejection:
            self._discard_warm_start(bundle)
            return _MPCProposal(
                sequence=None,
                result=result,
                status="optimal_rejected",
                outcome="rejected",
                prepare_time_s=prepare_time,
                risk_component_ids=risk_ids,
                max_freq_slack_hz=freq_slack,
                max_rocof_slack_hz_per_s=rocof_slack,
                max_power_slack_pu=power_slack,
                rejection_reasons=tuple(rejection),
            )

        accepted_sequence = sequence.copy()
        self._warm_start = shift_warm_start_sequence(accepted_sequence)
        return _MPCProposal(
            sequence=accepted_sequence,
            result=result,
            status=result.status,
            outcome=result.outcome.value,
            prepare_time_s=prepare_time,
            risk_component_ids=risk_ids,
            max_freq_slack_hz=freq_slack,
            max_rocof_slack_hz_per_s=rocof_slack,
            max_power_slack_pu=power_slack,
        )

    def _discard_warm_start(
        self,
        bundle: SDBMPCProblem | None = None,
    ) -> None:
        """Make a prior MPC sequence unreachable after any fallback trigger."""

        self._warm_start = None
        target = self._last_problem if bundle is None else bundle
        if target is None:
            return
        try:
            target.set_warm_start(None)
        except Exception:
            # A cache that cannot clear its executable variable is unsafe to
            # reuse. Dropping it forces a fresh template on the next MPC step.
            self._problem_cache.clear()
            self._last_problem = None

    @staticmethod
    def _maximum_slack(value: ArrayLike | float) -> float:
        array = np.asarray(value, dtype=np.float64)
        if array.size == 0 or not np.all(np.isfinite(array)):
            raise FloatingPointError("slack solution is empty or non-finite")
        return max(0.0, float(np.max(array)))

    def _sequence_is_executable(
        self,
        sequence: FloatArray,
        previous_input: FloatArray,
    ) -> bool:
        tolerance = self._controller_config.input_feasibility_tolerance
        bounds = self._mpc_config.bounds
        if np.any(sequence < bounds.lower[:, None] - tolerance) or np.any(
            sequence > bounds.upper[:, None] + tolerance
        ):
            return False
        deltas = np.diff(
            np.concatenate((previous_input[:, None], sequence), axis=1),
            axis=1,
        )
        maximum = bounds.ramp[:, None] * self._mpc_config.sample_time_s
        return bool(np.all(np.abs(deltas) <= maximum + tolerance))

    @staticmethod
    def _proposal_solve_time(proposal: _MPCProposal) -> float:
        return 0.0 if proposal.result is None else proposal.result.total_wall_time_s

    def _fallback_action(
        self,
        measurement: Measurement,
        *,
        solver_status: str,
        solve_time_s: float,
        max_freq_slack_hz: float,
    ) -> ControlAction:
        if self._estimated_state is None:
            raise RuntimeError("no finite estimate is available for LQI fallback")
        # Equation (74) and the equation-(71) IBR withdrawal are recomputed at
        # every fallback/recovery timestamp from the current visible signals.
        fallback = self._fallback.action_from_estimate(
            measurement,
            self._estimated_state,
        )
        self._state = SDControllerState.FALLBACK
        return ControlAction(
            u_sg_pu=fallback.u_sg_pu,
            u_ibr_pu=fallback.u_ibr_pu,
            controller_state=SDControllerState.FALLBACK.value,
            solver_status=solver_status,
            solve_time_s=solve_time_s,
            max_freq_slack_hz=max_freq_slack_hz,
        )

    def _enter_or_extend_fallback(
        self,
        time_s: float,
        reasons: Sequence[str],
    ) -> None:
        self._discard_warm_start()
        normalized = tuple(str(reason).strip() for reason in reasons if str(reason).strip())
        if not normalized:
            normalized = ("unspecified_fallback",)
        if self._active_fallback is None:
            self._active_fallback = _ActiveFallback(
                event_id=self._next_fallback_event_id,
                started_time_s=time_s,
                last_fallback_time_s=time_s,
                fallback_steps=0,
                reasons=list(normalized),
            )
            self._next_fallback_event_id += 1
        else:
            self._active_fallback.add_reasons(normalized)
        self._state = SDControllerState.FALLBACK

    def _note_fallback_action(self, time_s: float) -> None:
        if self._active_fallback is None:
            self._enter_or_extend_fallback(time_s, ("fallback_state",))
        assert self._active_fallback is not None
        self._active_fallback.last_fallback_time_s = time_s
        self._active_fallback.fallback_steps += 1

    def _close_fallback(self, time_s: float) -> None:
        if self._active_fallback is None:
            return
        self._completed_fallback_events.append(
            self._active_fallback.snapshot(ended_time_s=time_s)
        )
        self._active_fallback = None
        self._reset_recovery()

    def _reset_recovery(self) -> None:
        self._recovery_hold_count = 0
        self._recovery_blend_step = 0

    def _make_step_record(
        self,
        *,
        measurement: Measurement,
        action: ControlAction,
        belief: FloatArray,
        map_mode: int,
        entropy: float,
        pvalue: float,
        diagnostic_state: str,
        proposal: _MPCProposal | None,
        trigger_reasons: tuple[str, ...],
        blend_alpha: float,
        fallback_candidate: ControlAction | None,
        mpc_candidate: FloatArray | None,
        external_error: Exception | None,
    ) -> SDBMPCStepRecord:
        event: FallbackEvent | None = None
        if self._active_fallback is not None:
            event = self._active_fallback.snapshot()
        elif blend_alpha >= 1.0 and self._completed_fallback_events:
            event = self._completed_fallback_events[-1]
        result = None if proposal is None else proposal.result
        error_type = None if external_error is None else type(external_error).__name__
        error_message = None if external_error is None else str(external_error)
        if proposal is not None and proposal.error_type is not None:
            error_type = proposal.error_type
            error_message = proposal.error_message
        return SDBMPCStepRecord(
            time_s=measurement.time_s,
            sample_index=len(self._step_records),
            controller_state=action.controller_state,
            diagnostic_state=diagnostic_state,
            mode_belief=belief,
            map_mode=map_mode,
            belief_entropy=entropy,
            ood_pvalue=pvalue,
            solver_status=action.solver_status,
            solver_outcome="not_run" if proposal is None else proposal.outcome,
            solver_name=None if result is None else result.solver,
            solver_version=None if result is None else result.solver_version,
            solve_time_s=action.solve_time_s,
            problem_prepare_time_s=0.0 if proposal is None else proposal.prepare_time_s,
            solver_objective=None if result is None else result.objective,
            solver_iterations=None if result is None else result.iterations,
            risk_component_ids=() if proposal is None else proposal.risk_component_ids,
            max_freq_slack_hz=0.0 if proposal is None else proposal.max_freq_slack_hz,
            max_rocof_slack_hz_per_s=(
                0.0 if proposal is None else proposal.max_rocof_slack_hz_per_s
            ),
            max_power_slack_pu=0.0 if proposal is None else proposal.max_power_slack_pu,
            fallback_event_id=None if event is None else event.event_id,
            trigger_reasons=trigger_reasons,
            fallback_event_reasons=() if event is None else event.reasons,
            fallback_steps=0 if event is None else event.fallback_steps,
            recovery_hold_count=self._recovery_hold_count,
            recovery_blend_alpha=blend_alpha,
            u_sg_pu=action.u_sg_pu,
            u_ibr_pu=action.u_ibr_pu,
            fallback_u_sg_pu=(
                None if fallback_candidate is None else fallback_candidate.u_sg_pu
            ),
            fallback_u_ibr_pu=(
                None if fallback_candidate is None else fallback_candidate.u_ibr_pu
            ),
            mpc_u_sg_pu=None if mpc_candidate is None else float(mpc_candidate[0]),
            mpc_u_ibr_pu=None if mpc_candidate is None else float(mpc_candidate[1]),
            error_type=error_type,
            error_message=error_message,
        )

    @classmethod
    def from_project_files(
        cls,
        *,
        base_config_path: str | Path,
        mpc_config_path: str | Path,
        mode_library_path: str | Path,
        ood_calibration_path: str | Path,
    ) -> "SDBMPCController":
        """Build the canonical K=6 controller from hashed project artifacts.

        The calibration artifact must attest both the exact model-library file
        and its canonical logical content.  Configuration values are copied
        into frozen dataclasses before the controller is returned.
        """

        base_path = Path(base_config_path).expanduser().resolve()
        mpc_path = Path(mpc_config_path).expanduser().resolve()
        library_path = Path(mode_library_path).expanduser().resolve()
        calibration_path = Path(ood_calibration_path).expanduser().resolve()
        for path in (base_path, mpc_path, library_path, calibration_path):
            if not path.is_file():
                raise FileNotFoundError(path)

        base = load_yaml(base_path)
        mpc_payload = load_yaml(mpc_path)
        if base.get("schema_version") != 1 or mpc_payload.get("schema_version") != 1:
            raise ValueError("base and MPC configuration schema_version must equal 1")
        library = ModeLibrary.load_json(library_path)
        artifact_payload = _load_json_mapping(calibration_path)
        artifact = OODCalibrationArtifact.from_dict(artifact_payload)

        library_file_hash = sha256_file(library_path)
        library_logical_hash = sha256_json(library.to_dict())
        if artifact.mode_library_sha256 != library_file_hash:
            raise ValueError("OOD calibration model-library file SHA-256 mismatch")
        if artifact.mode_library_logical_sha256 != library_logical_hash:
            raise ValueError("OOD calibration model-library logical SHA-256 mismatch")
        if tuple(artifact.known_component_ids) != tuple(range(6)):
            raise ValueError("canonical SD-BMPC requires calibrated native K=6 IDs")

        grid_values = _section(base, "grid")
        grid_model = GridFrequencyModel(
            GridParams(
                f0_hz=grid_values["f0_hz"],
                M_s=grid_values["M_s"],
                D_pu=grid_values["D_pu"],
                T_t_s=grid_values["T_t_s"],
                T_g_s=grid_values["T_g_s"],
                R_pu=grid_values["R_pu"],
                control_period_s=grid_values["control_period_s"],
                integration_step_s=grid_values["integration_step_s"],
            )
        )
        mpc_values = _section(mpc_payload, "mpc")
        ibr_values = _section(base, "ibr_command")
        weights = SDBMPCWeights(
            q_freq=float(mpc_values["q_freq"]),
            q_integral=float(mpc_values["q_integral"]),
            q_rocof=float(mpc_values["q_rocof"]),
            r_sg=float(mpc_values["r_sg"]),
            r_ibr=float(mpc_values["r_ibr"]),
            s_delta_sg=float(mpc_values["s_delta_sg"]),
            s_delta_ibr=float(mpc_values["s_delta_ibr"]),
            q_terminal_freq=float(mpc_values["q_terminal_freq"]),
            q_terminal_integral=float(mpc_values["q_terminal_integral"]),
            lambda_worst_base=float(mpc_values["lambda_worst_base"]),
            lambda_worst_entropy=float(mpc_values["lambda_worst_entropy"]),
            rho_freq_slack=float(mpc_values["rho_freq_slack"]),
            rho_rocof_slack=float(mpc_values["rho_rocof_slack"]),
            rho_power_slack=float(mpc_values["rho_power_slack"]),
        )
        bounds = SDBMPCBounds(
            u_min_pu=(grid_values["u_sg_min_pu"], ibr_values["u_min_pu"]),
            u_max_pu=(grid_values["u_sg_max_pu"], ibr_values["u_max_pu"]),
            ramp_pu_per_s=(
                grid_values["u_sg_ramp_pu_per_s"],
                ibr_values["ramp_pu_per_s"],
            ),
            freq_limit_hz=grid_values["freq_limit_hz"],
            rocof_limit_hz_per_s=grid_values["rocof_limit_hz_per_s"],
        )
        mpc_config = SDBMPCConfig(
            horizon_steps=mpc_values["horizon_steps"],
            sample_time_s=grid_model.params.control_period_s,
            f0_hz=grid_model.params.f0_hz,
            credible_mass=mpc_values["credible_mass"],
            entropy_use_all_modes=mpc_values["entropy_use_all_modes"],
            use_constraint_tightening=mpc_values["use_constraint_tightening"],
            weights=weights,
            bounds=bounds,
        )
        fallback_values = _section(mpc_payload, "fallback")
        common_slack = mpc_values["max_acceptable_slack_hz"]
        controller_config = SDBMPCControllerConfig(
            max_acceptable_freq_slack_hz=common_slack,
            # The supplied first-version configuration declares one common
            # rejection threshold; preserve it explicitly for all slack units.
            max_acceptable_rocof_slack_hz_per_s=common_slack,
            max_acceptable_power_slack_pu=common_slack,
            solve_timeout_s=mpc_values["solve_timeout_s"],
            warm_start=mpc_values["warm_start"],
            solver_priority=tuple(mpc_values["solver_priority"]),
            recovery_hold_steps=fallback_values["recovery_hold_steps"],
            return_blend_steps=fallback_values["return_blend_steps"],
        )
        fallback_config = LQIFallbackConfig(
            u_sg_min_pu=grid_values["u_sg_min_pu"],
            u_sg_max_pu=grid_values["u_sg_max_pu"],
            u_sg_ramp_pu_per_s=grid_values["u_sg_ramp_pu_per_s"],
            ibr_withdraw_rate_pu_per_s=fallback_values[
                "ibr_withdraw_rate_pu_per_s"
            ],
        )

        estimation = _section(base, "estimation")
        kalman = _section(estimation, "grid_kalman")
        estimator = GridKalmanFilter(
            grid_model,
            process_noise_covariance=np.diag(
                np.asarray(kalman["process_noise_diagonal"], dtype=np.float64)
            ),
            measurement_noise_covariance=np.diag(
                np.asarray(kalman["measurement_noise_diagonal"], dtype=np.float64)
            ),
            initial_covariance=np.diag(
                np.asarray(kalman["initial_covariance_diagonal"], dtype=np.float64)
            ),
            load_random_walk_std_pu_per_s=kalman[
                "load_random_walk_std_pu_per_s"
            ],
        )
        identification = _section(base, "identification")
        generation = _section(identification, "generation")
        measurement_variance = float(generation["power_measurement_noise_std_pu"]) ** 2
        if measurement_variance != artifact.measurement_noise_variance_pu2:
            raise ValueError("base measurement noise differs from OOD calibration")
        belief_values = _section(base, "belief")
        if float(belief_values["residual_variance_floor"]) != artifact.variance_floor_pu2:
            raise ValueError("base variance floor differs from OOD calibration")
        ood_values = _section(base, "ood")
        ood_config = OODDetectorConfig(
            alpha_on=ood_values["alpha_on"],
            alpha_off=ood_values["alpha_off"],
            L_on=ood_values["hold_on_steps"],
            L_off=ood_values["hold_off_steps"],
            variance_floor=artifact.variance_floor_pu2,
        )
        transition = build_sticky_transition_matrix(
            len(library.models),
            belief_values["switch_epsilon"],
        )
        diagnostic = OnlineModeDiagnostic(
            library,
            artifact,
            measurement_noise_variance_pu2=measurement_variance,
            belief_floor=belief_values["probability_floor"],
            variance_floor_pu2=belief_values["residual_variance_floor"],
            ood_config=ood_config,
            transition_matrix=transition,
        )
        modes = modes_from_library(grid_model, library)
        provenance = SDBMPCProvenance(
            base_config_sha256=config_sha256(base),
            mpc_config_sha256=config_sha256(mpc_payload),
            mode_library_file_sha256=library_file_hash,
            mode_library_logical_sha256=library_logical_hash,
            ood_calibration_file_sha256=sha256_file(calibration_path),
        )
        return cls(
            grid_model,
            modes,
            diagnostic,
            mpc_config=mpc_config,
            controller_config=controller_config,
            estimator=estimator,
            fallback_config=fallback_config,
            provenance=provenance,
        )


def _section(mapping: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    if name not in mapping:
        raise KeyError(f"missing configuration section {name!r}")
    value = mapping[name]
    if not isinstance(value, Mapping):
        raise TypeError(f"configuration section {name!r} must be a mapping")
    return value


def _load_json_mapping(path: Path) -> Mapping[str, Any]:
    def reject_nonfinite(token: str) -> None:
        raise ValueError(f"non-standard JSON number {token!r} is forbidden")

    payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_nonfinite)
    if not isinstance(payload, Mapping):
        raise TypeError("OOD calibration file must contain a JSON mapping")
    return payload


__all__ = [
    "FallbackEvent",
    "OnlineDiagnosticRuntime",
    "PrecompileRecord",
    "ProblemCacheRuntime",
    "SDBMPCController",
    "SDBMPCControllerConfig",
    "SDBMPCProvenance",
    "SDBMPCStepRecord",
    "SDControllerState",
]
