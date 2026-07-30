"""One-sided causal GLR/CUSUM detector with conservative set reset."""

from __future__ import annotations

import numpy as np

from .passive_set_membership import (
    CapabilitySetEstimate, GLOBAL_LOWER, GLOBAL_UPPER,
)


class CausalGLRSetReset:
    name = "glr_set_reset"

    def __init__(self, period_s: float, drift: float = 0.0035, threshold: float = 0.030) -> None:
        self.period_s = float(period_s)
        self.drift = float(drift)
        self.threshold = float(threshold)
        self.reset()

    def reset(self) -> None:
        self.lower = GLOBAL_LOWER.copy()
        self.upper = GLOBAL_UPPER.copy()
        self.previous_command = np.zeros(2)
        self.previous_power = np.zeros(2)
        self.score = 0.0
        self._initialized = False

    def update(self, time_s, issued_bess_command, measured_bess_power, frequency_hz):
        command = np.asarray(issued_bess_command, dtype=float)
        power = np.asarray(measured_bess_power, dtype=float) + 0.60 * np.asarray(frequency_hz) / 50.0
        prediction = self.previous_command if self._initialized else power
        residual = float(np.max(np.abs(power - prediction)))
        excitation = max(
            float(np.max(np.abs(self.previous_command))),
            float(np.max(np.abs(command - self.previous_command))),
        )
        self.score = max(0.0, self.score + residual - self.drift)
        alarm = bool(self.score >= self.threshold and excitation >= 0.02)
        # A detector reset expands uncertainty; it must not masquerade as a
        # control-relevant capability contraction.
        if alarm:
            self.lower = GLOBAL_LOWER.copy()
            self.upper = GLOBAL_UPPER.copy()
            self.score = 0.0
        phi = np.r_[self.previous_command, command - self.previous_command]
        energy = float(phi @ phi)
        estimate = CapabilitySetEstimate(
            float(time_s), self.lower.copy(), self.upper.copy(), alarm, False,
            "change_unclassified" if alarm else "uncertain", excitation, residual,
            0.0, float("inf") if energy == 0 else 1.0, "reset_global" if alarm else "monitoring",
        )
        self.previous_command = command.copy()
        self.previous_power = power.copy()
        self._initialized = True
        return estimate
