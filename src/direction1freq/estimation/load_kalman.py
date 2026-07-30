"""Augmented-state Kalman filter for unknown two-area load increments."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class LoadEstimate:
    omega_pu: np.ndarray
    tie_pu: float
    load_pu: np.ndarray
    covariance: np.ndarray
    innovation: np.ndarray


class AugmentedLoadKalman:
    """Estimate `[omega1, omega2, tie, load1, load2]` causally.

    Inputs are measured SG/BESS active power from the previous interval and
    current measured frequency/tie-line.  No simulator load or future sample is
    accepted by the API.
    """

    def __init__(
        self, dt_s: float = 0.05, nominal_frequency_hz: float = 50.0,
        inertia_s: tuple[float, float] = (5.0, 4.5),
        damping: tuple[float, float] = (1.0, 1.0), tie_coefficient: float = 0.07,
        measurement_std: tuple[float, float, float] = (2e-5, 2e-5, 2e-4),
        load_random_walk_std: float = 7e-4,
    ) -> None:
        self.dt_s = float(dt_s); self.f0 = float(nominal_frequency_hz)
        h = np.asarray(inertia_s, dtype=float); d = np.asarray(damping, dtype=float)
        a = np.eye(5)
        a[0, 0] -= dt_s * d[0] / (2 * h[0]); a[0, 2] = -dt_s / (2 * h[0]); a[0, 3] = -dt_s / (2 * h[0])
        a[1, 1] -= dt_s * d[1] / (2 * h[1]); a[1, 2] = dt_s / (2 * h[1]); a[1, 4] = -dt_s / (2 * h[1])
        a[2, 0] = dt_s * 2 * np.pi * self.f0 * tie_coefficient
        a[2, 1] = -dt_s * 2 * np.pi * self.f0 * tie_coefficient
        b = np.zeros((5, 4)); b[0, 0:2] = dt_s / (2 * h[0]); b[1, 2:4] = dt_s / (2 * h[1])
        c = np.zeros((3, 5)); c[0, 0] = 1; c[1, 1] = 1; c[2, 2] = 1
        self.A, self.B, self.C = a, b, c
        self.Q = np.diag([2e-9, 2e-9, 2e-8, load_random_walk_std**2, load_random_walk_std**2])
        self.R = np.diag(np.asarray(measurement_std, dtype=float) ** 2)
        self.x = np.zeros(5); self.P = np.diag([1e-5, 1e-5, 1e-3, 0.02, 0.02]) ** 2
        self.previous_power = np.zeros(4)

    def update(self, measured_frequency_hz: np.ndarray, measured_tie_pu: float, measured_power_pu: np.ndarray) -> LoadEstimate:
        frequency = np.asarray(measured_frequency_hz, dtype=float)
        power = np.asarray(measured_power_pu, dtype=float)
        if frequency.shape != (2,) or power.shape != (4,):
            raise ValueError("public measurement shapes must be frequency (2,) and power (4,)")
        x_prior = self.A @ self.x + self.B @ self.previous_power
        p_prior = self.A @ self.P @ self.A.T + self.Q
        measurement = np.r_[frequency / self.f0, float(measured_tie_pu)]
        innovation = measurement - self.C @ x_prior
        innovation_covariance = self.C @ p_prior @ self.C.T + self.R
        gain = np.linalg.solve(innovation_covariance, self.C @ p_prior).T
        self.x = x_prior + gain @ innovation
        identity = np.eye(5)
        self.P = (identity - gain @ self.C) @ p_prior @ (identity - gain @ self.C).T + gain @ self.R @ gain.T
        self.previous_power = power.copy()
        return LoadEstimate(self.x[:2].copy(), float(self.x[2]), self.x[3:5].copy(), self.P.copy(), innovation.copy())

