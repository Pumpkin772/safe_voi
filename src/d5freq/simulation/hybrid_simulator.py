"""Coupled continuous grid/hidden-IBR simulator with a control-period ZOH."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray

from d5freq.interfaces import ControlAction, Measurement
from d5freq.models.grid_frequency import (
    GRID_STATE_SIZE,
    GridFrequencyModel,
    GridStateIndex,
)
from d5freq.models.hidden_mode_ibr import (
    CommandHistory,
    IBRModeParams,
    IBRState,
    ibr_derivative,
    resolve_delay_s,
)
from d5freq.utils.seeds import SeedManager

from .disturbances import LoadDisturbance, LoadDisturbanceSpec
from .integrators import rk4_step
from .mode_schedules import PiecewiseConstantModeSchedule


FloatArray = NDArray[np.float64]


def _finite_nonnegative(value: float, name: str) -> float:
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return normalized


@dataclass(frozen=True, slots=True)
class Scenario:
    """Simulator-private recipe for one closed-loop episode.

    A controller never receives this object. In particular, the hidden mode
    schedule remains on the simulator/evaluation side of the API boundary.
    """

    mode_schedule: PiecewiseConstantModeSchedule
    duration_s: float
    disturbance: LoadDisturbanceSpec = field(default_factory=LoadDisturbanceSpec)
    name: str = "scenario"
    omega_measurement_std_pu: float = 0.0
    power_measurement_std_pu: float = 0.0
    initial_grid_state: tuple[float, ...] | None = None
    initial_ibr_state: tuple[float, float] = (0.0, 0.0)

    def __post_init__(self) -> None:
        if not isinstance(self.mode_schedule, PiecewiseConstantModeSchedule):
            raise TypeError("mode_schedule must be a PiecewiseConstantModeSchedule")
        if not isinstance(self.disturbance, LoadDisturbanceSpec):
            raise TypeError("disturbance must be a LoadDisturbanceSpec")
        duration = _finite_nonnegative(self.duration_s, "duration_s")
        if duration <= 0.0:
            raise ValueError("duration_s must be positive")
        omega_std = _finite_nonnegative(
            self.omega_measurement_std_pu, "omega_measurement_std_pu"
        )
        power_std = _finite_nonnegative(
            self.power_measurement_std_pu, "power_measurement_std_pu"
        )
        name = str(self.name).strip()
        if not name:
            raise ValueError("name must not be empty")
        if self.initial_grid_state is not None:
            initial_grid = tuple(float(value) for value in self.initial_grid_state)
            if len(initial_grid) != GRID_STATE_SIZE or not all(
                math.isfinite(value) for value in initial_grid
            ):
                raise ValueError("initial_grid_state must contain five finite values")
            object.__setattr__(self, "initial_grid_state", initial_grid)
        initial_ibr = tuple(float(value) for value in self.initial_ibr_state)
        if len(initial_ibr) != 2 or not all(math.isfinite(value) for value in initial_ibr):
            raise ValueError("initial_ibr_state must contain two finite values")
        object.__setattr__(self, "duration_s", duration)
        object.__setattr__(self, "omega_measurement_std_pu", omega_std)
        object.__setattr__(self, "power_measurement_std_pu", power_std)
        object.__setattr__(self, "initial_ibr_state", initial_ibr)
        object.__setattr__(self, "name", name)


class HiddenModeFrequencySimulator:
    """Integrate the grid and hidden IBR in one consistent RK4 state vector."""

    def __init__(
        self,
        grid_model: GridFrequencyModel,
        mode_params: Mapping[str, IBRModeParams],
    ) -> None:
        if not isinstance(grid_model, GridFrequencyModel):
            raise TypeError("grid_model must be a GridFrequencyModel")
        copied_modes = dict(mode_params)
        if not copied_modes:
            raise ValueError("mode_params must not be empty")
        for key, params in copied_modes.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("mode_params keys must be non-empty strings")
            if not isinstance(params, IBRModeParams):
                raise TypeError("mode_params values must be IBRModeParams instances")
            if key != params.name:
                raise ValueError("each mode_params key must equal IBRModeParams.name")

        self._grid_model = grid_model
        self._mode_params = MappingProxyType(copied_modes)
        self._scenario: Scenario | None = None
        self._disturbance: LoadDisturbance | None = None
        self._grid_state: FloatArray | None = None
        self._ibr_state: IBRState | None = None
        self._command_history: CommandHistory | None = None
        self._measurement_rng: np.random.Generator | None = None
        self._time_s = 0.0
        self._u_sg_prev_pu = 0.0
        self._u_ibr_prev_pu = 0.0

    @property
    def time_s(self) -> float:
        return self._time_s

    def reset(self, seed: int, scenario: Scenario) -> Measurement:
        """Reset all simulator state and return only controller-visible signals."""

        if not isinstance(scenario, Scenario):
            raise TypeError("scenario must be a Scenario")
        unknown_modes = set(scenario.mode_schedule.modes) - set(self._mode_params)
        if unknown_modes:
            raise ValueError(f"scenario references unknown modes: {sorted(unknown_modes)}")

        seed_manager = SeedManager(seed)
        disturbance = scenario.disturbance.realize(
            seed=seed_manager.seed("load_disturbance"),
            duration_s=scenario.duration_s,
        )
        initial_load = disturbance.value_at(0.0)
        if scenario.initial_grid_state is None:
            grid_state = self._grid_model.zero_state(initial_load)
        else:
            grid_state = np.asarray(scenario.initial_grid_state, dtype=float).copy()
            if not math.isclose(
                float(grid_state[GridStateIndex.LOAD_DISTURBANCE_PU]),
                initial_load,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            ):
                raise ValueError(
                    "initial_grid_state load must equal disturbance value at time zero"
                )

        self._scenario = scenario
        self._disturbance = disturbance
        self._grid_state = grid_state
        self._ibr_state = IBRState.from_array(scenario.initial_ibr_state)
        self._command_history = CommandHistory(initial_value_pu=0.0)
        self._command_history.record(0.0, 0.0)
        self._measurement_rng = seed_manager.rng("measurement_noise")
        self._time_s = 0.0
        self._u_sg_prev_pu = 0.0
        self._u_ibr_prev_pu = 0.0
        return self._measurement()

    def _require_state(
        self,
    ) -> tuple[
        Scenario,
        LoadDisturbance,
        FloatArray,
        IBRState,
        CommandHistory,
        np.random.Generator,
    ]:
        values = (
            self._scenario,
            self._disturbance,
            self._grid_state,
            self._ibr_state,
            self._command_history,
            self._measurement_rng,
        )
        if any(value is None for value in values):
            raise RuntimeError("simulator must be reset before use")
        return values  # type: ignore[return-value]

    def _measurement(self) -> Measurement:
        scenario, _, grid_state, ibr_state, _, rng = self._require_state()
        omega = float(grid_state[GridStateIndex.OMEGA_PU])
        p_mech = float(grid_state[GridStateIndex.P_MECH_PU])
        p_ibr = ibr_state.p_ibr_pu
        if scenario.omega_measurement_std_pu > 0.0:
            omega += float(rng.normal(0.0, scenario.omega_measurement_std_pu))
        if scenario.power_measurement_std_pu > 0.0:
            p_mech += float(rng.normal(0.0, scenario.power_measurement_std_pu))
            p_ibr += float(rng.normal(0.0, scenario.power_measurement_std_pu))
        return Measurement(
            time_s=self._time_s,
            omega_pu=omega,
            p_mech_pu=p_mech,
            p_ibr_pu=p_ibr,
            u_sg_prev_pu=self._u_sg_prev_pu,
            u_ibr_prev_pu=self._u_ibr_prev_pu,
        )

    def _advance_segment(
        self,
        *,
        start_time_s: float,
        end_time_s: float,
        mode_name: str,
        load_pu: float,
        action: ControlAction,
    ) -> None:
        _, _, grid_state, ibr_state, history, _ = self._require_state()
        params = self._mode_params[mode_name]
        coupled_initial = np.concatenate((grid_state, ibr_state.to_array()))
        left_endpoint_s = np.nextafter(end_time_s, start_time_s)

        def coupled_derivative(time_s: float, state: FloatArray) -> FloatArray:
            stage_grid = state[:GRID_STATE_SIZE].copy()
            stage_grid[GridStateIndex.LOAD_DISTURBANCE_PU] = load_pu
            stage_ibr = IBRState.from_array(state[GRID_STATE_SIZE:])
            # RK4 evaluates k4 at the segment's right endpoint. Query held
            # command history from the left at that one point so a delayed ZOH
            # change is applied by the following segment, never backward with
            # k4's 1/6 weight.
            history_time_s = min(time_s, left_endpoint_s)
            delay_s = resolve_delay_s(params, history_time_s)
            delayed_command = history.delayed_value(history_time_s, delay_s)
            grid_dot = self._grid_model.derivative(
                stage_grid,
                u_sg_pu=action.u_sg_pu,
                p_ibr_pu=stage_ibr.p_ibr_pu,
                load_derivative_pu_per_s=0.0,
            )
            ibr_dot = ibr_derivative(
                stage_ibr,
                delayed_command_pu=delayed_command,
                omega_pu=float(stage_grid[GridStateIndex.OMEGA_PU]),
                params=params,
            )
            return np.concatenate((grid_dot, ibr_dot))

        next_state = rk4_step(
            coupled_derivative,
            start_time_s,
            coupled_initial,
            end_time_s - start_time_s,
        )
        self._grid_state = next_state[:GRID_STATE_SIZE].copy()
        self._ibr_state = IBRState.from_array(next_state[GRID_STATE_SIZE:])

    def step(self, action: ControlAction) -> tuple[Measurement, dict[str, object]]:
        """Apply one ZOH action and return measurement plus evaluation-only truth."""

        if not isinstance(action, ControlAction):
            raise TypeError("action must be a ControlAction")
        scenario, disturbance, _, _, history, _ = self._require_state()
        if self._time_s >= scenario.duration_s:
            raise RuntimeError("episode is already complete")

        history.record(self._time_s, action.u_ibr_pu)
        target_time = min(
            self._time_s + self._grid_model.params.control_period_s,
            scenario.duration_s,
        )
        integration_step = self._grid_model.params.integration_step_s

        while self._time_s < target_time:
            nominal_end = min(self._time_s + integration_step, target_time)
            mode_name = scenario.mode_schedule.mode_at(self._time_s)
            params = self._mode_params[mode_name]
            command_boundaries: tuple[float, ...] = ()
            if params.delay_profile is None:
                command_boundaries = history.delayed_transition_times_between(
                    self._time_s,
                    nominal_end,
                    params.delay_s,
                )
            boundaries = (
                scenario.mode_schedule.switch_times_between(self._time_s, nominal_end)
                + disturbance.transition_times_between(self._time_s, nominal_end)
                + command_boundaries
            )
            segment_end = min((nominal_end, *boundaries))
            load_pu = disturbance.value_at(self._time_s)
            assert self._grid_state is not None
            self._grid_state[GridStateIndex.LOAD_DISTURBANCE_PU] = load_pu
            self._advance_segment(
                start_time_s=self._time_s,
                end_time_s=segment_end,
                mode_name=mode_name,
                load_pu=load_pu,
                action=action,
            )
            self._time_s = segment_end
            assert self._grid_state is not None
            self._grid_state[GridStateIndex.LOAD_DISTURBANCE_PU] = (
                disturbance.value_at(self._time_s)
            )

        self._u_sg_prev_pu = action.u_sg_pu
        self._u_ibr_prev_pu = action.u_ibr_pu
        measurement = self._measurement()
        assert self._grid_state is not None and self._ibr_state is not None
        evaluation = {
            "time_s": self._time_s,
            "scenario": scenario.name,
            "true_mode_eval_only": scenario.mode_schedule.mode_at(self._time_s),
            "load_disturbance_pu": disturbance.value_at(self._time_s),
            "omega_true_pu": float(self._grid_state[GridStateIndex.OMEGA_PU]),
            "p_mech_true_pu": float(self._grid_state[GridStateIndex.P_MECH_PU]),
            "p_ibr_true_pu": self._ibr_state.p_ibr_pu,
            "done": math.isclose(
                self._time_s, scenario.duration_s, rel_tol=0.0, abs_tol=1.0e-12
            ),
        }
        return measurement, evaluation


__all__ = ["HiddenModeFrequencySimulator", "Scenario"]
