"""Controller-side contracts and deterministic constraint helpers.

Only controller-visible measurements and estimates appear in this module.
Simulator truth, hidden-mode schedules, and evaluation labels are deliberately
absent from every runtime contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from d5freq.interfaces import Measurement


FloatArray = NDArray[np.float64]


def _finite_real(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _boolean(value: bool, name: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{name} must be boolean")
    return bool(value)


@runtime_checkable
class GridStateEstimator(Protocol):
    """Minimal controller-side adapter implemented by ``GridKalmanFilter``."""

    def reset_from_measurement(self, measurement: Measurement) -> FloatArray: ...

    def update_from_measurement(self, measurement: Measurement) -> FloatArray: ...


@dataclass(frozen=True, slots=True)
class FallbackTrigger:
    """Auditable inputs and indicator ``chi_k`` from equation (70)."""

    ood_active: bool = False
    solver_failed: bool = False
    frequency_slack_hz: float = 0.0
    max_acceptable_slack_hz: float = 0.0
    timed_out: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "ood_active", _boolean(self.ood_active, "ood_active"))
        object.__setattr__(
            self, "solver_failed", _boolean(self.solver_failed, "solver_failed")
        )
        object.__setattr__(self, "timed_out", _boolean(self.timed_out, "timed_out"))
        slack = _finite_real(self.frequency_slack_hz, "frequency_slack_hz")
        limit = _finite_real(
            self.max_acceptable_slack_hz, "max_acceptable_slack_hz"
        )
        if slack < 0.0 or limit < 0.0:
            raise ValueError("frequency slack and its limit must be non-negative")
        object.__setattr__(self, "frequency_slack_hz", slack)
        object.__setattr__(self, "max_acceptable_slack_hz", limit)

    @property
    def active(self) -> bool:
        """Whether equation (70)'s disjunction evaluates to true."""

        return bool(
            self.ood_active
            or self.solver_failed
            or self.frequency_slack_hz > self.max_acceptable_slack_hz
            or self.timed_out
        )

    @property
    def indicator(self) -> int:
        """Integer value of ``chi_k`` in equation (70)."""

        return int(self.active)

    @property
    def reasons(self) -> tuple[str, ...]:
        """Stable, deterministic list of all active trigger reasons."""

        reasons: list[str] = []
        if self.ood_active:
            reasons.append("ood")
        if self.solver_failed:
            reasons.append("solver_fail")
        if self.frequency_slack_hz > self.max_acceptable_slack_hz:
            reasons.append("frequency_slack")
        if self.timed_out:
            reasons.append("timeout")
        return tuple(reasons)


def fallback_required(
    *,
    ood_active: bool = False,
    solver_failed: bool = False,
    frequency_slack_hz: float = 0.0,
    max_acceptable_slack_hz: float = 0.0,
    timed_out: bool = False,
) -> bool:
    """Evaluate the fallback trigger in equation (70)."""

    return FallbackTrigger(
        ood_active=ood_active,
        solver_failed=solver_failed,
        frequency_slack_hz=frequency_slack_hz,
        max_acceptable_slack_hz=max_acceptable_slack_hz,
        timed_out=timed_out,
    ).active


def clip_with_rate_limit(
    requested_value: float,
    previous_value: float,
    lower_bound: float,
    upper_bound: float,
    ramp_rate_per_s: float,
    sample_time_s: float,
) -> float:
    """Apply an amplitude bound and equation-(63) rate bound together.

    The prior executable command must already lie inside the amplitude bounds;
    otherwise no command can necessarily satisfy both constraints in one step,
    so the inconsistent state is rejected instead of silently choosing which
    safety constraint to violate.
    """

    requested = _finite_real(requested_value, "requested_value")
    previous = _finite_real(previous_value, "previous_value")
    lower = _finite_real(lower_bound, "lower_bound")
    upper = _finite_real(upper_bound, "upper_bound")
    ramp = _finite_real(ramp_rate_per_s, "ramp_rate_per_s")
    sample_time = _finite_real(sample_time_s, "sample_time_s")
    if lower > upper:
        raise ValueError("lower_bound must not exceed upper_bound")
    if ramp < 0.0:
        raise ValueError("ramp_rate_per_s must be non-negative")
    if sample_time <= 0.0:
        raise ValueError("sample_time_s must be positive")
    if previous < lower or previous > upper:
        raise ValueError("previous_value must lie within the amplitude bounds")

    maximum_change = ramp * sample_time
    feasible_lower = max(lower, previous - maximum_change)
    feasible_upper = min(upper, previous + maximum_change)
    return min(feasible_upper, max(feasible_lower, requested))


def withdraw_toward_zero(
    previous_value: float,
    withdrawal_rate_per_s: float,
    sample_time_s: float,
) -> float:
    """Equation (71): move a command toward zero without overshoot."""

    previous = _finite_real(previous_value, "previous_value")
    rate = _finite_real(withdrawal_rate_per_s, "withdrawal_rate_per_s")
    sample_time = _finite_real(sample_time_s, "sample_time_s")
    if rate < 0.0:
        raise ValueError("withdrawal_rate_per_s must be non-negative")
    if sample_time <= 0.0:
        raise ValueError("sample_time_s must be positive")
    remaining_magnitude = max(0.0, abs(previous) - rate * sample_time)
    if remaining_magnitude == 0.0:
        return 0.0
    return math.copysign(remaining_magnitude, previous)


should_trigger_fallback = fallback_required


__all__ = [
    "FallbackTrigger",
    "FloatArray",
    "GridStateEstimator",
    "clip_with_rate_limit",
    "fallback_required",
    "should_trigger_fallback",
    "withdraw_toward_zero",
]
