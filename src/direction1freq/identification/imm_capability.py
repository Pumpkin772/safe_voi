"""Causal interval multiple-model capability observer."""

from __future__ import annotations

from collections import deque

import numpy as np

from .passive_set_membership import (
    CapabilitySetEstimate, GLOBAL_LOWER, GLOBAL_UPPER,
)


class IMMIntervalCapabilityObserver:
    name = "imm_interval"

    def __init__(self, period_s: float, posterior_threshold: float = 0.95) -> None:
        self.period_s = float(period_s)
        self.posterior_threshold = float(posterior_threshold)
        self.reset()

    def reset(self) -> None:
        self.lower = GLOBAL_LOWER.copy()
        self.upper = GLOBAL_UPPER.copy()
        self.previous_command = np.zeros(2)
        self.previous_power = np.zeros(2)
        self.probabilities = np.ones(4) / 4.0
        self.regressors: deque[np.ndarray] = deque(maxlen=6)
        self._initialized = False

    def update(self, time_s, issued_bess_command, measured_bess_power, frequency_hz):
        command = np.asarray(issued_bess_command, dtype=float)
        power = np.asarray(measured_bess_power, dtype=float) + 0.60 * np.asarray(frequency_hz) / 50.0
        previous = self.previous_command
        nominal = previous
        delayed = self.previous_power
        ramped = self.previous_power + np.clip(previous - self.previous_power, -0.012, 0.012)
        limited = np.clip(previous, -0.035, 0.035)
        predictions = (nominal, delayed, ramped, limited)
        errors = np.array([np.sum((power - prediction) ** 2) for prediction in predictions])
        likelihood = np.exp(-errors / (2.0 * 0.004**2)) + 1e-12
        self.probabilities = 0.90 * self.probabilities + 0.10 * likelihood / likelihood.sum()
        self.probabilities /= self.probabilities.sum()
        excitation = max(float(np.max(np.abs(previous))), float(np.max(np.abs(command - previous))))
        posterior = float(np.max(self.probabilities))
        winner = int(np.argmax(self.probabilities))
        before_lower, before_upper = self.lower.copy(), self.upper.copy()
        candidate = ("nominal", "delay", "ramp", "power_limit_ambiguous")[winner]
        alarm = bool(posterior >= self.posterior_threshold and winner != 0 and excitation >= 0.02)
        if alarm and winner == 1:
            self.lower[2] = max(self.lower[2], 0.60)
        elif alarm and winner == 2:
            self.upper[1] = min(self.upper[1], 0.45)
        # The limited model cannot distinguish headroom from availability, so
        # its set remains global even at high posterior.
        set_changed = bool(
            np.max(np.abs(self.lower - before_lower) / (GLOBAL_UPPER - GLOBAL_LOWER)) >= 0.08
            or np.max(np.abs(self.upper - before_upper) / (GLOBAL_UPPER - GLOBAL_LOWER)) >= 0.08
        )
        phi = np.r_[previous, command - previous]
        self.regressors.append(phi)
        gramian = sum((np.outer(item, item) for item in self.regressors), np.zeros((4, 4)))
        eig = np.linalg.eigvalsh(gramian)
        estimate = CapabilitySetEstimate(
            float(time_s), self.lower.copy(), self.upper.copy(), alarm, set_changed,
            candidate, excitation, float(np.sqrt(errors[winner])), float(eig[0]),
            float(eig[-1] / max(eig[0], 1e-12)),
            "updated" if set_changed else ("ambiguous" if alarm else "uncertain"),
        )
        self.previous_command = command.copy()
        self.previous_power = power.copy()
        self._initialized = True
        return estimate
