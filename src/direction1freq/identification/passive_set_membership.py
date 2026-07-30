"""Causal passive capability-set membership estimator for Phase E."""

from __future__ import annotations

from dataclasses import dataclass
from collections import deque

import numpy as np


CAPABILITY_NAMES = ("headroom", "ramp", "delay", "energy", "availability")
GLOBAL_LOWER = np.array([0.25, 0.10, 0.0, 0.03, 0.20])
GLOBAL_UPPER = np.array([1.00, 1.00, 2.0, 1.00, 1.00])


@dataclass(frozen=True, slots=True)
class CapabilitySetEstimate:
    time_s: float
    lower: np.ndarray
    upper: np.ndarray
    alarm: bool
    set_changed: bool
    candidate: str
    excitation: float
    residual: float
    gramian_lambda_min: float
    gramian_condition: float
    status: str

    @property
    def normalized_width(self) -> float:
        return float(np.mean((self.upper - self.lower) / (GLOBAL_UPPER - GLOBAL_LOWER)))


class MultiStepSetMembership:
    """Conservative external-I/O feasible-set intersection.

    An observed output establishes a delivered-capability lower bound.  An
    upper bound is contracted only after persistent excitation and a repeated
    boundary signature.  Ambiguous power-limit signatures intentionally leave
    headroom/availability global instead of inventing a label.
    """

    name = "set_membership"

    def __init__(self, period_s: float, window: int = 4) -> None:
        self.period_s = float(period_s)
        self.window = int(window)
        self.reset()

    def reset(self) -> None:
        self.lower = GLOBAL_LOWER.copy()
        self.upper = GLOBAL_UPPER.copy()
        self.previous_command = np.zeros(2)
        self.previous_power = np.zeros(2)
        self.residuals: deque[float] = deque(maxlen=self.window)
        self.regressors: deque[np.ndarray] = deque(maxlen=self.window)
        self.cumulative_throughput = 0.0
        self._initialized = False

    def update(
        self, time_s: float, issued_bess_command: np.ndarray,
        measured_bess_power: np.ndarray, frequency_hz: np.ndarray,
    ) -> CapabilitySetEstimate:
        command = np.asarray(issued_bess_command, dtype=float)
        power = np.asarray(measured_bess_power, dtype=float)
        frequency = np.asarray(frequency_hz, dtype=float)
        # Remove the known local PFR contribution before judging SFR tracking.
        sfr_power = power + 0.60 * frequency / 50.0
        prediction = self.previous_command if self._initialized else sfr_power
        residual = float(np.max(np.abs(sfr_power - prediction)))
        command_step = float(np.max(np.abs(command - self.previous_command)))
        output_step = float(np.max(np.abs(sfr_power - self.previous_power)))
        excitation = max(float(np.max(np.abs(self.previous_command))), command_step)
        self.residuals.append(residual)
        self.regressors.append(np.r_[self.previous_command, command - self.previous_command])
        self.cumulative_throughput += float(np.sum(np.abs(power))) * self.period_s
        gramian = sum((np.outer(phi, phi) for phi in self.regressors), np.zeros((4, 4)))
        eigenvalues = np.linalg.eigvalsh(gramian)
        lambda_min = float(eigenvalues[0])
        condition = float(eigenvalues[-1] / max(eigenvalues[0], 1e-12))
        persistent = (
            len(self.residuals) == self.window
            and excitation >= 0.02
            and sum(value >= 0.006 for value in self.residuals) >= self.window - 1
        )
        before_lower, before_upper = self.lower.copy(), self.upper.copy()
        candidate = "uncertain"
        alarm = bool(persistent)
        if persistent and command_step >= 0.018 and output_step <= 0.010:
            # Delay and ramp remain distinguishable only if output slew is
            # consistently small after more than one delayed sample.
            if output_step <= 0.003:
                self.upper[1] = min(self.upper[1], 0.40)
                candidate = "ramp"
            elif residual >= 0.012:
                self.lower[2] = max(self.lower[2], 0.70)
                candidate = "delay"
        elif persistent and self.cumulative_throughput >= 0.20:
            self.upper[3] = min(self.upper[3], 0.20)
            candidate = "energy"
        elif persistent:
            # Headroom and availability induce the same external static
            # saturation map here.  Alarm, but do not make a false contraction.
            candidate = "power_limit_ambiguous"
        set_changed = bool(
            np.max(np.abs(self.lower - before_lower) / (GLOBAL_UPPER - GLOBAL_LOWER)) >= 0.08
            or np.max(np.abs(self.upper - before_upper) / (GLOBAL_UPPER - GLOBAL_LOWER)) >= 0.08
        )
        status = "updated" if set_changed else ("alarm_ambiguous" if alarm else "insufficient_information")
        estimate = CapabilitySetEstimate(
            float(time_s), self.lower.copy(), self.upper.copy(), alarm, set_changed,
            candidate, excitation, residual, lambda_min, condition, status,
        )
        self.previous_command = command.copy()
        self.previous_power = sfr_power.copy()
        self._initialized = True
        return estimate
