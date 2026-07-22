"""Independent continuous-time IBR test bench for identification data.

The bench integrates equations (11)--(15) with classical RK4 using steps no
larger than the configured integration step.  External ``u_b`` and ``omega``
signals are right-continuous and held for a complete control period.  Fixed
delay command transitions are integration boundaries, so an RK4 end stage
cannot leak a new delayed command into the preceding interval.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from d5freq.models.hidden_mode_ibr import (
    CommandHistory,
    IBRModeParams,
    IBRState,
    ibr_derivative,
)
from d5freq.simulation.integrators import rk4_step
from d5freq.utils.seeds import make_rng

from .excitation import audit_safe_excitation
from .schemas import (
    ExcitationSignals,
    IdentificationGenerationConfig,
    IdentificationTrajectory,
    TrajectoryAudit,
)


FloatArray = NDArray[np.float64]


def _strictly_after(value: float, reference: float, tolerance: float) -> bool:
    return value > reference + tolerance


def _integration_boundaries(
    start_time_s: float,
    end_time_s: float,
    *,
    maximum_step_s: float,
    discontinuities_s: tuple[float, ...],
) -> tuple[float, ...]:
    """Return increasing RK4 right boundaries including discontinuities."""

    scale = max(1.0, abs(start_time_s), abs(end_time_s))
    tolerance = 64.0 * np.finfo(float).eps * scale
    discontinuities = tuple(
        sorted(
            value
            for value in discontinuities_s
            if _strictly_after(value, start_time_s, tolerance)
            and value <= end_time_s + tolerance
        )
    )
    boundaries: list[float] = []
    cursor = start_time_s
    transition_index = 0
    while _strictly_after(end_time_s, cursor, tolerance):
        candidate = min(end_time_s, cursor + maximum_step_s)
        while (
            transition_index < len(discontinuities)
            and not _strictly_after(
                discontinuities[transition_index], cursor, tolerance
            )
        ):
            transition_index += 1
        if transition_index < len(discontinuities):
            transition = discontinuities[transition_index]
            if transition < candidate - tolerance:
                candidate = transition
            elif math.isclose(
                transition, candidate, rel_tol=0.0, abs_tol=tolerance
            ):
                candidate = transition
        if not _strictly_after(candidate, cursor, tolerance):
            raise RuntimeError("failed to make progress constructing RK4 boundaries")
        boundaries.append(float(candidate))
        cursor = float(candidate)
    if not boundaries or not math.isclose(
        boundaries[-1], end_time_s, rel_tol=0.0, abs_tol=tolerance
    ):
        boundaries.append(float(end_time_s))
    else:
        boundaries[-1] = float(end_time_s)
    return tuple(boundaries)


def _integrate_control_interval(
    state: IBRState,
    *,
    start_time_s: float,
    end_time_s: float,
    omega_pu: float,
    params: IBRModeParams,
    command_history: CommandHistory,
    integration_step_s: float,
) -> IBRState:
    transitions = command_history.delayed_transition_times_between(
        start_time_s,
        end_time_s,
        params.delay_s,
    )
    boundaries = _integration_boundaries(
        start_time_s,
        end_time_s,
        maximum_step_s=integration_step_s,
        discontinuities_s=transitions,
    )
    values = state.to_array()
    left_time = start_time_s
    for right_time in boundaries:
        duration = right_time - left_time
        # Classical RK4 samples its fourth stage at the right endpoint.  A ZOH
        # transition there belongs to the next interval, so query the immediate
        # left limit for that one stage only.
        left_limit = float(np.nextafter(right_time, left_time))
        scale = max(1.0, abs(left_time), abs(right_time))
        endpoint_tolerance = 64.0 * np.finfo(float).eps * scale

        def derivative(time_s: float, stage_values: FloatArray) -> FloatArray:
            query_time = (
                left_limit
                if math.isclose(
                    time_s,
                    right_time,
                    rel_tol=0.0,
                    abs_tol=endpoint_tolerance,
                )
                else time_s
            )
            delayed_command = command_history.delayed_value(
                query_time,
                params.delay_s,
            )
            return ibr_derivative(
                IBRState.from_array(stage_values),
                delayed_command,
                omega_pu,
                params,
            )

        values = rk4_step(derivative, left_time, values, duration)
        left_time = right_time
    return IBRState.from_array(values)


def simulate_identification_trajectory(
    params: IBRModeParams,
    signals: ExcitationSignals,
    config: IdentificationGenerationConfig,
    *,
    trajectory_id: str,
    measurement_seed: int,
) -> IdentificationTrajectory:
    """Simulate one fixed truth mode without exposing it in the return value."""

    if not isinstance(params, IBRModeParams):
        raise TypeError("params must be an IBRModeParams instance")
    if params.delay_profile is not None:
        raise ValueError(
            "identification training accepts fixed-delay known modes only"
        )
    if not isinstance(signals, ExcitationSignals):
        raise TypeError("signals must be an ExcitationSignals instance")
    if not isinstance(config, IdentificationGenerationConfig):
        raise TypeError("config must be an IdentificationGenerationConfig")
    if len(signals.time_s) != config.sample_count:
        raise ValueError("signals do not have the configured sample count")
    signal_audit = audit_safe_excitation(signals, config)
    if not signal_audit.passed:
        raise ValueError(f"unsafe or insufficient excitation: {signal_audit}")

    command_history = CommandHistory(initial_value_pu=0.0)
    for time_s, command_pu in zip(
        signals.time_s, signals.u_ibr_pu, strict=True
    ):
        command_history.record(float(time_s), float(command_pu))

    state = IBRState()
    true_power = np.zeros(config.sample_count, dtype=np.float64)
    for sample_index in range(config.sample_count - 1):
        state = _integrate_control_interval(
            state,
            start_time_s=float(signals.time_s[sample_index]),
            end_time_s=float(signals.time_s[sample_index + 1]),
            omega_pu=float(signals.omega_pu[sample_index]),
            params=params,
            command_history=command_history,
            integration_step_s=config.integration_step_s,
        )
        true_power[sample_index + 1] = state.p_ibr_pu

    if config.power_measurement_noise_std_pu > 0.0:
        rng = make_rng(measurement_seed)
        observed_power = true_power + rng.normal(
            loc=0.0,
            scale=config.power_measurement_noise_std_pu,
            size=config.sample_count,
        )
    else:
        observed_power = true_power
    return IdentificationTrajectory(
        trajectory_id=trajectory_id,
        time_s=signals.time_s,
        u_ibr_pu=signals.u_ibr_pu,
        omega_pu=signals.omega_pu,
        p_ibr_pu=observed_power,
    )


def arx_regression_condition_number(trajectory: IdentificationTrajectory) -> float:
    """Return the raw equation-(76) ARX regressor condition number.

    The first implementation uses ``na=nb=nf=2``.  The returned finite maximum
    float represents rank deficiency, avoiding non-standard JSON ``Infinity``
    values in audit artifacts.
    """

    if not isinstance(trajectory, IdentificationTrajectory):
        raise TypeError("trajectory must be an IdentificationTrajectory")
    p_ibr = trajectory.p_ibr_pu
    command = trajectory.u_ibr_pu
    omega = trajectory.omega_pu
    rows = np.column_stack(
        (
            p_ibr[1:-1],
            p_ibr[:-2],
            command[1:-1],
            command[:-2],
            omega[1:-1],
            omega[:-2],
            np.ones(len(p_ibr) - 2, dtype=np.float64),
        )
    )
    singular_values = np.linalg.svd(rows, compute_uv=False)
    largest = float(singular_values[0])
    smallest = float(singular_values[-1])
    if smallest <= np.finfo(float).eps * max(1.0, largest):
        return float(np.finfo(float).max)
    condition = largest / smallest
    return min(float(np.finfo(float).max), float(condition))


def audit_identification_trajectory(
    trajectory: IdentificationTrajectory,
    config: IdentificationGenerationConfig,
    *,
    tolerance: float = 1.0e-12,
) -> TrajectoryAudit:
    """Audit public inputs and detect insufficient ARX regressor conditioning."""

    if not isinstance(trajectory, IdentificationTrajectory):
        raise TypeError("trajectory must be an IdentificationTrajectory")
    if not isinstance(config, IdentificationGenerationConfig):
        raise TypeError("config must be an IdentificationGenerationConfig")
    if tolerance < 0.0 or not math.isfinite(tolerance):
        raise ValueError("tolerance must be finite and non-negative")
    dt = np.diff(trajectory.time_s)
    if not np.allclose(
        dt, config.control_period_s, rtol=0.0, atol=max(tolerance, 1.0e-12)
    ):
        raise ValueError("trajectory is not sampled at the configured control period")
    max_abs_command = float(np.max(np.abs(trajectory.u_ibr_pu)))
    command_rate = np.diff(trajectory.u_ibr_pu) / dt
    max_abs_command_rate = float(np.max(np.abs(command_rate)))
    frequency_hz = config.f0_hz * trajectory.omega_pu
    max_abs_frequency = float(np.max(np.abs(frequency_hz)))
    command_std = float(np.std(trajectory.u_ibr_pu))
    frequency_std = float(np.std(frequency_hz))
    condition = arx_regression_condition_number(trajectory)
    return TrajectoryAudit(
        trajectory_id=trajectory.trajectory_id,
        max_abs_command_pu=max_abs_command,
        max_abs_command_rate_pu_per_s=max_abs_command_rate,
        max_abs_frequency_hz=max_abs_frequency,
        command_std_pu=command_std,
        frequency_std_hz=frequency_std,
        regression_condition_number=condition,
        command_amplitude_safe=(
            max_abs_command <= config.command_abs_limit_pu + tolerance
        ),
        command_rate_safe=(
            max_abs_command_rate
            <= config.command_rate_limit_pu_per_s + tolerance
        ),
        frequency_safe=(
            max_abs_frequency <= config.frequency_abs_limit_hz + tolerance
        ),
        command_excitation_sufficient=(
            command_std + tolerance >= config.minimum_command_std_pu
        ),
        frequency_excitation_sufficient=(
            frequency_std + tolerance >= config.minimum_frequency_std_hz
        ),
        regression_conditioning_safe=(
            condition <= config.maximum_regression_condition_number
        ),
    )


__all__ = [
    "arx_regression_condition_number",
    "audit_identification_trajectory",
    "simulate_identification_trajectory",
]
