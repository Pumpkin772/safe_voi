"""Simulator-private hidden-mode IBR truth dynamics.

This module implements equations (11)--(16) from the mathematical
specification.  It deliberately depends only on numeric values and truth-model
parameters: controller instances, diagnostic state, and controller-visible
interfaces do not cross this boundary.

Commands in :class:`CommandHistory` are interpreted as right-continuous,
zero-order-held samples.  A delayed query therefore returns the most recently
recorded command at or before ``time_s - delay_s``.  Before the first recorded
sample, the explicitly configured initial command is returned.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
import math
from numbers import Real

import numpy as np
from numpy.typing import NDArray


FloatArray = NDArray[np.float64]


def _finite(value: float, name: str) -> float:
    """Return ``value`` as a finite float or raise a descriptive error."""

    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _nonnegative(value: float, name: str) -> float:
    normalized = _finite(value, name)
    if normalized < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def _positive(value: float, name: str) -> float:
    normalized = _finite(value, name)
    if normalized <= 0.0:
        raise ValueError(f"{name} must be positive")
    return normalized


@dataclass(frozen=True, slots=True)
class SinusoidalDelayProfile:
    """Deterministic absolute delay profile for the held-out OOD mode.

    The profile starts at ``min_delay_s`` when ``phase_rad`` is zero, reaches
    ``max_delay_s`` after half a period, and returns to the minimum after a full
    period.  ``phase_rad`` shifts that cycle without changing its bounds.
    """

    min_delay_s: float
    max_delay_s: float
    period_s: float
    phase_rad: float = 0.0

    def __post_init__(self) -> None:
        minimum = _nonnegative(self.min_delay_s, "min_delay_s")
        maximum = _nonnegative(self.max_delay_s, "max_delay_s")
        period = _positive(self.period_s, "period_s")
        phase = _finite(self.phase_rad, "phase_rad")
        if maximum < minimum:
            raise ValueError("max_delay_s must be greater than or equal to min_delay_s")
        object.__setattr__(self, "min_delay_s", minimum)
        object.__setattr__(self, "max_delay_s", maximum)
        object.__setattr__(self, "period_s", period)
        object.__setattr__(self, "phase_rad", phase)

    def delay_at(self, time_s: float) -> float:
        """Return the profile's absolute delay at non-negative ``time_s``."""

        time = _nonnegative(time_s, "time_s")
        amplitude = 0.5 * (self.max_delay_s - self.min_delay_s)
        angle = 2.0 * math.pi * time / self.period_s + self.phase_rad
        # This form makes the zero-phase profile begin at its minimum.
        value = self.min_delay_s + amplitude * (1.0 - math.cos(angle))
        # Clamp roundoff at extrema so the declared bounds remain exact.
        return min(self.max_delay_s, max(self.min_delay_s, value))


def _delay_profile_from_mapping(profile: Mapping[str, object]) -> SinusoidalDelayProfile:
    values = dict(profile)
    kind = values.pop("kind", None)
    if kind != "sinusoidal":
        raise ValueError("delay_profile.kind must be 'sinusoidal'")
    allowed = {"min_delay_s", "max_delay_s", "period_s", "phase_rad"}
    unknown = set(values) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"unknown sinusoidal delay profile fields: {names}")
    required = {"min_delay_s", "max_delay_s", "period_s"}
    missing = required - set(values)
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"missing sinusoidal delay profile fields: {names}")
    return SinusoidalDelayProfile(**values)  # type: ignore[arg-type]


def _normalize_delay_profile(profile: object | None) -> object | None:
    if profile is None or isinstance(profile, SinusoidalDelayProfile):
        return profile
    if isinstance(profile, Mapping):
        return _delay_profile_from_mapping(profile)
    if callable(profile) or callable(getattr(profile, "delay_at", None)):
        return profile
    raise TypeError(
        "delay_profile must be None, a sinusoidal profile mapping, "
        "a callable, or an object with delay_at(time_s)"
    )


@dataclass(frozen=True, slots=True)
class IBRModeParams:
    r"""Simulator-private parameter set :math:`\Theta_m` in equation (16).

    ``delay_profile`` is optional.  If present, it provides the *absolute*
    delay used at runtime and supersedes the fixed ``delay_s`` value.  YAML
    mappings using the project's ``kind: sinusoidal`` schema are normalized to
    :class:`SinusoidalDelayProfile` during construction.
    """

    name: str
    command_gain: float
    frequency_gain: float
    command_filter_time_s: float
    power_response_time_s: float
    delay_s: float
    p_max_pos_pu: float
    p_max_neg_pu: float
    ramp_up_pu_per_s: float
    ramp_down_pu_per_s: float
    deadband_pu: float
    delay_profile: object | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        object.__setattr__(self, "name", self.name.strip())

        nonnegative_fields = (
            "command_gain",
            "frequency_gain",
            "delay_s",
            "p_max_pos_pu",
            "p_max_neg_pu",
            "ramp_up_pu_per_s",
            "ramp_down_pu_per_s",
            "deadband_pu",
        )
        for field_name in nonnegative_fields:
            object.__setattr__(
                self,
                field_name,
                _nonnegative(getattr(self, field_name), field_name),
            )
        for field_name in ("command_filter_time_s", "power_response_time_s"):
            object.__setattr__(
                self,
                field_name,
                _positive(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "delay_profile",
            _normalize_delay_profile(self.delay_profile),
        )

    @classmethod
    def from_mapping(cls, name: str, values: Mapping[str, object]) -> "IBRModeParams":
        """Construct a validated mode directly from one YAML mode mapping."""

        if not isinstance(values, Mapping):
            raise TypeError("values must be a mapping")
        return cls(name=name, **dict(values))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class IBRState:
    """Second-order truth state ``[q_m, p_b]`` in per unit."""

    q_pu: float = 0.0
    p_ibr_pu: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "q_pu", _finite(self.q_pu, "q_pu"))
        object.__setattr__(self, "p_ibr_pu", _finite(self.p_ibr_pu, "p_ibr_pu"))

    def to_array(self) -> FloatArray:
        """Return a new ``float64`` vector ordered as ``[q_m, p_b]``."""

        return np.array([self.q_pu, self.p_ibr_pu], dtype=np.float64)

    @classmethod
    def from_array(cls, values: object) -> "IBRState":
        """Build a state from an array-like object containing exactly 2 values."""

        array = np.asarray(values, dtype=float)
        if array.size != 2:
            raise ValueError("IBR state array must contain exactly 2 values")
        flat = array.reshape(2)
        return cls(q_pu=float(flat[0]), p_ibr_pu=float(flat[1]))


class CommandHistory:
    """Deterministic zero-order-held command history for delay evaluation."""

    __slots__ = ("_initial_value_pu", "_times_s", "_values_pu")

    def __init__(self, initial_value_pu: float = 0.0) -> None:
        self._initial_value_pu = _finite(initial_value_pu, "initial_value_pu")
        self._times_s: list[float] = []
        self._values_pu: list[float] = []

    @property
    def initial_value_pu(self) -> float:
        return self._initial_value_pu

    @property
    def times_s(self) -> tuple[float, ...]:
        """Immutable snapshot of recorded sample times."""

        return tuple(self._times_s)

    @property
    def values_pu(self) -> tuple[float, ...]:
        """Immutable snapshot of recorded command values."""

        return tuple(self._values_pu)

    def __len__(self) -> int:
        return len(self._times_s)

    def clear(self, initial_value_pu: float | None = None) -> None:
        """Remove all samples and optionally replace the prehistory value."""

        if initial_value_pu is not None:
            self._initial_value_pu = _finite(initial_value_pu, "initial_value_pu")
        self._times_s.clear()
        self._values_pu.clear()

    def record(self, time_s: float, value: float) -> None:
        """Record a command sample at a nondecreasing non-negative time.

        Re-recording the most recent timestamp replaces that sample.  This is
        useful when a simulator initializes the command at time zero and then
        commits the first control action at the same instant.  Earlier samples
        can never be rewritten.
        """

        time = _nonnegative(time_s, "time_s")
        command = _finite(value, "value")
        if self._times_s and time < self._times_s[-1]:
            raise ValueError("command sample times must be nondecreasing")
        if self._times_s and time == self._times_s[-1]:
            self._values_pu[-1] = command
            return
        self._times_s.append(time)
        self._values_pu.append(command)

    def value_at(self, time_s: float) -> float:
        """Return the held command at ``time_s`` (negative means prehistory)."""

        query_time = _finite(time_s, "time_s")
        index = bisect_right(self._times_s, query_time) - 1
        if index < 0:
            return self._initial_value_pu
        return self._values_pu[index]

    def delayed_value(self, time_s: float, delay_s: float) -> float:
        """Return the ZOH command at ``time_s - delay_s``."""

        time = _nonnegative(time_s, "time_s")
        delay = _nonnegative(delay_s, "delay_s")
        return self.value_at(time - delay)

    def delayed_transition_times_between(
        self,
        start_time_s: float,
        end_time_s: float,
        delay_s: float,
    ) -> tuple[float, ...]:
        """Return fixed-delay command changes in ``(start, end]``.

        A recorded ZOH sample at ``t`` becomes visible at ``t + delay_s``.
        Hybrid integration uses these times to split at command
        discontinuities instead of leaking a new command into the preceding
        RK4 interval's right-end stage.
        """

        start = _nonnegative(start_time_s, "start_time_s")
        end = _nonnegative(end_time_s, "end_time_s")
        delay = _nonnegative(delay_s, "delay_s")
        if end < start:
            raise ValueError("end_time_s must not precede start_time_s")
        return tuple(
            transition
            for sample_time in self._times_s
            if start < (transition := sample_time + delay) <= end
        )


def deadband(value: float, deadband_pu: float) -> float:
    """Equation (11): continuous symmetric deadband with edge subtraction."""

    command = _finite(value, "value")
    width = _nonnegative(deadband_pu, "deadband_pu")
    if abs(command) <= width:
        return 0.0
    return command - math.copysign(width, command)


def asymmetric_saturation(
    value: float,
    p_max_pos_pu: float,
    p_max_neg_pu: float,
) -> float:
    """Equation (14): saturate to ``[-p_max_neg_pu, p_max_pos_pu]``."""

    signal = _finite(value, "value")
    upper = _nonnegative(p_max_pos_pu, "p_max_pos_pu")
    negative_magnitude = _nonnegative(p_max_neg_pu, "p_max_neg_pu")
    return min(upper, max(-negative_magnitude, signal))


def resolve_delay_s(params: IBRModeParams, time_s: float) -> float:
    """Resolve a mode's fixed or optional time-varying absolute delay."""

    if not isinstance(params, IBRModeParams):
        raise TypeError("params must be an IBRModeParams instance")
    time = _nonnegative(time_s, "time_s")
    profile = params.delay_profile
    if profile is None:
        return params.delay_s
    if callable(profile):
        delay = profile(time)
    else:
        delay_at = getattr(profile, "delay_at", None)
        if not callable(delay_at):  # Defensive: construction already rejects it.
            raise TypeError("delay_profile must provide delay_at(time_s)")
        delay = delay_at(time)
    return _nonnegative(delay, "resolved delay")


def ibr_reference(
    delayed_command_pu: float,
    omega_pu: float,
    params: IBRModeParams,
) -> float:
    """Equation (12): hidden mode's internal reference ``r_m``."""

    if not isinstance(params, IBRModeParams):
        raise TypeError("params must be an IBRModeParams instance")
    command = _finite(delayed_command_pu, "delayed_command_pu")
    omega = _finite(omega_pu, "omega_pu")
    return (
        params.command_gain * deadband(command, params.deadband_pu)
        - params.frequency_gain * omega
    )


def ramp_limited_power_derivative(
    q_bar_pu: float,
    p_ibr_pu: float,
    power_response_time_s: float,
    ramp_up_pu_per_s: float,
    ramp_down_pu_per_s: float,
) -> float:
    """Equation (15): output lag derivative with asymmetric ramp clipping."""

    target = _finite(q_bar_pu, "q_bar_pu")
    power = _finite(p_ibr_pu, "p_ibr_pu")
    time_constant = _positive(power_response_time_s, "power_response_time_s")
    ramp_up = _nonnegative(ramp_up_pu_per_s, "ramp_up_pu_per_s")
    ramp_down = _nonnegative(ramp_down_pu_per_s, "ramp_down_pu_per_s")
    unconstrained = (target - power) / time_constant
    return min(ramp_up, max(-ramp_down, unconstrained))


def ibr_derivative(
    state: IBRState,
    delayed_command_pu: float,
    omega_pu: float,
    params: IBRModeParams,
) -> FloatArray:
    """Return ``[dq_m/dt, dp_b/dt]`` for fixed exogenous inputs.

    This pure function implements equations (11)--(15).  Delay resolution and
    history lookup happen outside it so a hybrid simulator can evaluate the
    coupled grid/IBR derivative without hidden mutable state.
    """

    if not isinstance(state, IBRState):
        raise TypeError("state must be an IBRState instance")
    reference = ibr_reference(delayed_command_pu, omega_pu, params)
    q_dot = (reference - state.q_pu) / params.command_filter_time_s
    q_bar = asymmetric_saturation(
        state.q_pu,
        params.p_max_pos_pu,
        params.p_max_neg_pu,
    )
    p_dot = ramp_limited_power_derivative(
        q_bar,
        state.p_ibr_pu,
        params.power_response_time_s,
        params.ramp_up_pu_per_s,
        params.ramp_down_pu_per_s,
    )
    derivative = np.array([q_dot, p_dot], dtype=np.float64)
    if not np.all(np.isfinite(derivative)):
        raise FloatingPointError("IBR derivative is not finite")
    return derivative


def step_ibr_rk4(
    state: IBRState,
    delayed_command_pu: float,
    omega_pu: float,
    params: IBRModeParams,
    dt_s: float,
) -> IBRState:
    """Advance the second-order IBR truth state by one classical RK4 step.

    ``delayed_command_pu`` and ``omega_pu`` are held constant across this
    standalone step.  The full hybrid simulator may instead call
    :func:`ibr_derivative` at its coupled RK4 stages.
    """

    if not isinstance(state, IBRState):
        raise TypeError("state must be an IBRState instance")
    if not isinstance(params, IBRModeParams):
        raise TypeError("params must be an IBRModeParams instance")
    command = _finite(delayed_command_pu, "delayed_command_pu")
    omega = _finite(omega_pu, "omega_pu")
    dt = _positive(dt_s, "dt_s")
    x0 = state.to_array()

    def derivative(values: FloatArray) -> FloatArray:
        return ibr_derivative(IBRState.from_array(values), command, omega, params)

    k1 = derivative(x0)
    k2 = derivative(x0 + 0.5 * dt * k1)
    k3 = derivative(x0 + 0.5 * dt * k2)
    k4 = derivative(x0 + dt * k3)
    next_values = x0 + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
    return IBRState.from_array(next_values)


__all__ = [
    "CommandHistory",
    "IBRModeParams",
    "IBRState",
    "SinusoidalDelayProfile",
    "asymmetric_saturation",
    "deadband",
    "ibr_derivative",
    "ibr_reference",
    "ramp_limited_power_derivative",
    "resolve_delay_s",
    "step_ibr_rk4",
]
