"""Evaluation-only hidden-mode trajectories for online diagnosis tests.

This module is deliberately located under :mod:`d5freq.evaluation`: it is
allowed to construct simulator truth, but returns the controller-visible
trajectory and the truth timeline as two separate objects.  The diagnostic
runtime consumes only :class:`~d5freq.data.schemas.IdentificationTrajectory`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math

import numpy as np
from numpy.typing import NDArray

from d5freq.data.schemas import ExcitationSignals, IdentificationTrajectory
from d5freq.models.hidden_mode_ibr import (
    CommandHistory,
    IBRModeParams,
    IBRState,
    ibr_derivative,
    resolve_delay_s,
)
from d5freq.simulation.integrators import rk4_step
from d5freq.simulation.mode_schedules import PiecewiseConstantModeSchedule
from d5freq.utils.seeds import make_rng


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class EvaluationTruthTimeline:
    """Simulator-private truth retained outside a runtime trajectory."""

    trajectory_id: str
    mode_name_eval_only: tuple[str, ...]

    def __post_init__(self) -> None:
        names = tuple(str(value) for value in self.mode_name_eval_only)
        if not names or any(not value for value in names):
            raise ValueError("mode_name_eval_only must contain non-empty names")
        object.__setattr__(self, "mode_name_eval_only", names)


def _finite_nonnegative(value: float, name: str) -> float:
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return normalized


def _next_fixed_delay_boundary(
    history: CommandHistory,
    *,
    start_time_s: float,
    end_time_s: float,
    params: IBRModeParams,
) -> float | None:
    if params.delay_profile is not None:
        return None
    boundaries = history.delayed_transition_times_between(
        start_time_s,
        end_time_s,
        params.delay_s,
    )
    return boundaries[0] if boundaries else None


def simulate_scheduled_ibr_trajectory(
    signals: ExcitationSignals,
    mode_params: Mapping[str, IBRModeParams],
    mode_schedule: PiecewiseConstantModeSchedule,
    *,
    trajectory_id: str,
    integration_step_s: float,
    power_measurement_noise_std_pu: float,
    measurement_seed: int,
) -> tuple[IdentificationTrajectory, EvaluationTruthTimeline]:
    """Simulate a scheduled known or OOD IBR against external signals.

    Physical IBR state and delayed-command history remain continuous at a mode
    switch.  Fixed-delay command discontinuities and mode switches split RK4
    intervals exactly.  A time-varying delay is evaluated at each RK4 stage,
    matching the held-out truth convention in the coupled simulator.
    """

    if not isinstance(signals, ExcitationSignals):
        raise TypeError("signals must be an ExcitationSignals instance")
    if not isinstance(mode_schedule, PiecewiseConstantModeSchedule):
        raise TypeError("mode_schedule must be a PiecewiseConstantModeSchedule")
    modes = dict(mode_params)
    if not modes or any(not isinstance(value, IBRModeParams) for value in modes.values()):
        raise TypeError("mode_params must be a non-empty mapping of IBRModeParams")
    if any(key != value.name for key, value in modes.items()):
        raise ValueError("each mode_params key must equal IBRModeParams.name")
    unknown = set(mode_schedule.modes) - set(modes)
    if unknown:
        raise ValueError(f"mode schedule references unknown modes: {sorted(unknown)}")
    maximum_step = _finite_nonnegative(integration_step_s, "integration_step_s")
    if maximum_step <= 0.0:
        raise ValueError("integration_step_s must be positive")
    noise_std = _finite_nonnegative(
        power_measurement_noise_std_pu,
        "power_measurement_noise_std_pu",
    )
    if isinstance(measurement_seed, bool) or int(measurement_seed) != measurement_seed:
        raise TypeError("measurement_seed must be an integer")
    seed = int(measurement_seed)
    if seed < 0:
        raise ValueError("measurement_seed must be non-negative")

    time = np.asarray(signals.time_s, dtype=np.float64)
    command = np.asarray(signals.u_ibr_pu, dtype=np.float64)
    omega = np.asarray(signals.omega_pu, dtype=np.float64)
    history = CommandHistory(initial_value_pu=0.0)
    for time_s, command_pu in zip(time, command, strict=True):
        history.record(float(time_s), float(command_pu))

    state = IBRState()
    true_power = np.zeros(time.size, dtype=np.float64)
    for sample_index in range(time.size - 1):
        cursor = float(time[sample_index])
        interval_end = float(time[sample_index + 1])
        held_omega = float(omega[sample_index])
        while cursor < interval_end:
            mode_name = mode_schedule.mode_at(cursor)
            params = modes[mode_name]
            segment_end = min(interval_end, cursor + maximum_step)
            switches = mode_schedule.switch_times_between(cursor, segment_end)
            if switches:
                segment_end = min(segment_end, switches[0])
            delayed_boundary = _next_fixed_delay_boundary(
                history,
                start_time_s=cursor,
                end_time_s=segment_end,
                params=params,
            )
            if delayed_boundary is not None:
                segment_end = min(segment_end, delayed_boundary)
            if not segment_end > cursor:
                raise RuntimeError("scheduled IBR integrator failed to advance")

            left_limit = float(np.nextafter(segment_end, cursor))
            tolerance = 64.0 * np.finfo(float).eps * max(
                1.0, abs(cursor), abs(segment_end)
            )

            def derivative(stage_time_s: float, values: FloatArray) -> FloatArray:
                query_time = (
                    left_limit
                    if math.isclose(
                        stage_time_s,
                        segment_end,
                        rel_tol=0.0,
                        abs_tol=tolerance,
                    )
                    else stage_time_s
                )
                delay_s = resolve_delay_s(params, query_time)
                delayed_command = history.delayed_value(query_time, delay_s)
                return ibr_derivative(
                    IBRState.from_array(values),
                    delayed_command_pu=delayed_command,
                    omega_pu=held_omega,
                    params=params,
                )

            next_values = rk4_step(
                derivative,
                cursor,
                state.to_array(),
                segment_end - cursor,
            )
            state = IBRState.from_array(next_values)
            cursor = segment_end
        true_power[sample_index + 1] = state.p_ibr_pu

    observed_power = true_power.copy()
    if noise_std > 0.0:
        observed_power += make_rng(seed).normal(0.0, noise_std, size=time.size)
    trajectory = IdentificationTrajectory(
        trajectory_id=trajectory_id,
        time_s=time,
        u_ibr_pu=command,
        omega_pu=omega,
        p_ibr_pu=observed_power,
    )
    truth = EvaluationTruthTimeline(
        trajectory_id=trajectory_id,
        mode_name_eval_only=tuple(
            mode_schedule.mode_at(float(time_s)) for time_s in time
        ),
    )
    return trajectory, truth


__all__ = ["EvaluationTruthTimeline", "simulate_scheduled_ibr_trajectory"]
