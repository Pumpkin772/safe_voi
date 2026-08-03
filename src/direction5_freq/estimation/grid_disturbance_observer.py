"""Reduced-order load observer with measured BESS POI power as a known input."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from scipy.linalg import block_diag
from scipy.signal import cont2discrete


@dataclass(frozen=True, slots=True)
class GridPublicMeasurement:
    time_s: float
    frequency_deviation_hz: np.ndarray
    tie_line_pu: float
    mechanical_power_pu: np.ndarray
    actual_bess_power_pu: np.ndarray
    issued_sg_command_pu: np.ndarray


@dataclass(frozen=True, slots=True)
class DisturbanceObserverEstimate:
    grid_state_pu: np.ndarray
    load_pu: np.ndarray
    load_rate_pu_per_s: np.ndarray
    covariance: np.ndarray
    raw_power_balance_load_pu: np.ndarray
    candidate: str
    actual_bess_power_used_as_known_input: bool


class GridDisturbanceObserver:
    """Estimate persistent net load without a command-to-BESS actuator model.

    The measured POI power enters the swing balance directly. The BESS command
    is intentionally absent from this API, so delay or capability mismatch
    cannot be absorbed by predicting an unmeasured BESS state from commands.
    """

    CANDIDATES = (
        "reduced_order_kalman_actual_bess_input",
        "unknown_input_observer",
        "constrained_mhe",
    )

    def __init__(
        self,
        period_s: float,
        candidate: str = "reduced_order_kalman_actual_bess_input",
        nominal_frequency_hz: float = 50.0,
        inertia_s: tuple[float, float] = (5.0, 4.5),
        damping_pu: tuple[float, float] = (1.0, 1.0),
        load_bound_pu: float = 0.20,
    ) -> None:
        if candidate not in self.CANDIDATES:
            raise ValueError(candidate)
        self.period_s = float(period_s)
        self.candidate = candidate
        self.nominal_frequency_hz = float(nominal_frequency_hz)
        self.inertia = np.asarray(inertia_s, dtype=float)
        self.damping = np.asarray(damping_pu, dtype=float)
        self.load_bound = float(load_bound_pu)
        self.reset()

    def reset(self) -> None:
        self.previous_time: float | None = None
        self.previous_omega = np.zeros(2)
        self.previous_mechanical = np.zeros(2)
        self.load = np.zeros(2)
        self.previous_load = np.zeros(2)
        self.covariance = np.eye(2) * 0.03**2
        self.raw_history: deque[np.ndarray] = deque(maxlen=6)

    @staticmethod
    def observability_condition_number(period_s: float) -> tuple[int, float]:
        """Condition the registered nine-state grid/load augmented model."""

        inertia = np.array([5.0, 4.5])
        damping = np.array([1.0, 1.0])
        droop = np.array([0.05, 0.05])
        governor = np.array([0.20, 0.25])
        turbine = np.array([0.50, 0.60])
        tie_gain = 2.0 * np.pi * 50.0 * 0.07
        a = np.zeros((7, 7))
        e = np.zeros((7, 2))
        for area in range(2):
            a[area, area] = -damping[area] / (2.0 * inertia[area])
            a[area, 5 + area] = 1.0 / (2.0 * inertia[area])
            a[3 + area, area] = -1.0 / (droop[area] * governor[area])
            a[3 + area, 3 + area] = -1.0 / governor[area]
            a[5 + area, 3 + area] = 1.0 / turbine[area]
            a[5 + area, 5 + area] = -1.0 / turbine[area]
            e[area, area] = -1.0 / (2.0 * inertia[area])
        a[0, 2] = -1.0 / (2.0 * inertia[0])
        a[1, 2] = 1.0 / (2.0 * inertia[1])
        a[2, 0] = tie_gain
        a[2, 1] = -tie_gain
        augmented = np.block([[a, e], [np.zeros((2, 7)), np.zeros((2, 2))]])
        c = np.zeros((5, 9))
        for row, index in enumerate((0, 1, 2, 5, 6)):
            c[row, index] = 1.0
        discrete = cont2discrete(
            (augmented, np.zeros((9, 1)), c, np.zeros((5, 1))),
            period_s,
        )[0]
        observability = np.vstack([c @ np.linalg.matrix_power(discrete, k) for k in range(9)])
        singular = np.linalg.svd(observability, compute_uv=False)
        rank = int(np.linalg.matrix_rank(observability, tol=1e-10))
        condition = float(singular[0] / max(singular[-1], np.finfo(float).tiny))
        return rank, condition

    def update(self, measurement: GridPublicMeasurement) -> DisturbanceObserverEstimate:
        omega = (
            np.asarray(measurement.frequency_deviation_hz, dtype=float)
            / self.nominal_frequency_hz
        )
        mechanical = np.asarray(measurement.mechanical_power_pu, dtype=float)
        actual_bess = np.asarray(measurement.actual_bess_power_pu, dtype=float)
        issued_sg = np.asarray(measurement.issued_sg_command_pu, dtype=float)
        if any(value.shape != (2,) for value in (omega, mechanical, actual_bess, issued_sg)):
            raise ValueError("all public vector measurements must contain two areas")
        if self.previous_time is None:
            dt = self.period_s
            omega_rate = np.zeros(2)
            mechanical_rate = np.zeros(2)
        else:
            dt = max(float(measurement.time_s) - self.previous_time, 1e-9)
            omega_rate = (omega - self.previous_omega) / dt
            mechanical_rate = (mechanical - self.previous_mechanical) / dt
        signed_tie = np.array([measurement.tie_line_pu, -measurement.tie_line_pu])
        raw_load = (
            mechanical
            + actual_bess
            - self.damping * omega
            - signed_tie
            - 2.0 * self.inertia * omega_rate
        )
        raw_load = np.clip(raw_load, -self.load_bound, self.load_bound)
        self.raw_history.append(raw_load.copy())
        self.previous_load = self.load.copy()
        if self.candidate == "reduced_order_kalman_actual_bess_input":
            process = np.eye(2) * (7.5e-4 * np.sqrt(dt / self.period_s)) ** 2
            measurement_covariance = np.eye(2) * 0.008**2
            prior_covariance = self.covariance + process
            gain = prior_covariance @ np.linalg.inv(
                prior_covariance + measurement_covariance
            )
            self.load = self.load + gain @ (raw_load - self.load)
            update = np.eye(2) - gain
            self.covariance = update @ prior_covariance @ update.T + gain @ measurement_covariance @ gain.T
        elif self.candidate == "unknown_input_observer":
            gain = 0.35
            self.load = (1.0 - gain) * self.load + gain * raw_load
            self.covariance = np.eye(2) * np.var(np.vstack(self.raw_history), axis=0, ddof=0)
        else:
            history = np.vstack(self.raw_history)
            constrained = np.median(history, axis=0)
            gain = min(0.55, len(history) / 10.0)
            self.load = (1.0 - gain) * self.load + gain * constrained
            variance = np.var(history, axis=0, ddof=0) + 1e-8
            self.covariance = np.diag(variance)
        self.load = np.clip(self.load, -self.load_bound, self.load_bound)
        load_rate = (self.load - self.previous_load) / dt
        valve_estimate = mechanical + np.array([0.50, 0.60]) * mechanical_rate
        state = np.r_[
            omega,
            float(measurement.tie_line_pu),
            valve_estimate,
            mechanical,
            actual_bess,
        ]
        self.previous_time = float(measurement.time_s)
        self.previous_omega = omega.copy()
        self.previous_mechanical = mechanical.copy()
        return DisturbanceObserverEstimate(
            grid_state_pu=state,
            load_pu=self.load.copy(),
            load_rate_pu_per_s=load_rate,
            covariance=self.covariance.copy(),
            raw_power_balance_load_pu=raw_load,
            candidate=self.candidate,
            actual_bess_power_used_as_known_input=True,
        )
