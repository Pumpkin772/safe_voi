"""Causal actual-POI load-observer candidates for Direction5."""

from __future__ import annotations

from collections import deque

import cvxpy as cp
import numpy as np

from .grid_load_observer import LoadEstimate, LoadObserverInput


class _ActualPOIBalance:
    def __init__(
        self,
        nominal_frequency_hz: float,
        inertia_s: tuple[float, float],
        damping_pu_per_pu_frequency: tuple[float, float],
        derivative_filter: float,
        warmup_samples: int,
    ) -> None:
        self.nominal_frequency_hz = float(nominal_frequency_hz)
        self.inertia = np.asarray(inertia_s, dtype=float)
        self.damping = np.asarray(damping_pu_per_pu_frequency, dtype=float)
        self.derivative_filter = float(derivative_filter)
        self.warmup_samples = int(warmup_samples)
        self._previous_time: float | None = None
        self._previous_omega: np.ndarray | None = None
        self._derivative = np.zeros(2)
        self._samples = 0

    def balance_observation(self, measurement: LoadObserverInput) -> np.ndarray:
        omega = np.asarray(measurement.frequency_deviation_hz) / self.nominal_frequency_hz
        if self._previous_time is None:
            derivative = np.zeros(2)
        else:
            dt_s = float(measurement.time_s - self._previous_time)
            if dt_s <= 0:
                raise ValueError("load-observer timestamps must increase")
            derivative = (omega - self._previous_omega) / dt_s
        self._derivative = self.derivative_filter * derivative + (1.0 - self.derivative_filter) * self._derivative
        tie = np.array((measurement.tie_line_pu, -measurement.tie_line_pu))
        observed = (
            np.asarray(measurement.sg_mechanical_power_pu)
            + np.asarray(measurement.bess_actual_poi_power_pu)
            + np.asarray(measurement.slow_reserve_power_pu)
            - self.damping * omega
            - tie
            - 2.0 * self.inertia * self._derivative
        )
        self._previous_time = float(measurement.time_s)
        self._previous_omega = omega.copy()
        self._samples += 1
        return observed

    def result(self, load: np.ndarray, observed: np.ndarray) -> LoadEstimate:
        return LoadEstimate(
            load_pu=np.asarray(load, dtype=float).copy(),
            instantaneous_balance_load_pu=np.asarray(observed, dtype=float).copy(),
            warmed=self._samples >= self.warmup_samples,
            samples=self._samples,
        )


class AugmentedKalmanLoadObserver(_ActualPOIBalance):
    name = "augmented_kalman_actual_poi"

    def __init__(self, *args, process_variance: float = 2e-6, measurement_variance: float = 2e-4, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._load = np.zeros(2)
        self._covariance = np.full(2, 0.05)
        self.process_variance = float(process_variance)
        self.measurement_variance = float(measurement_variance)

    def update(self, measurement: LoadObserverInput) -> LoadEstimate:
        observed = self.balance_observation(measurement)
        prediction_covariance = self._covariance + self.process_variance
        gain = prediction_covariance / (prediction_covariance + self.measurement_variance)
        self._load += gain * (observed - self._load)
        self._covariance = (1.0 - gain) * prediction_covariance
        return self.result(self._load, observed)


class UnknownInputLoadObserver(_ActualPOIBalance):
    name = "unknown_input_actual_poi"

    def __init__(self, *args, gain: float = 0.16, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.gain = float(gain)
        self._load = np.zeros(2)

    def update(self, measurement: LoadObserverInput) -> LoadEstimate:
        observed = self.balance_observation(measurement)
        self._load += self.gain * (observed - self._load)
        return self.result(self._load, observed)


class ConstrainedGridLoadMHE(_ActualPOIBalance):
    name = "constrained_mhe_actual_poi"

    def __init__(
        self,
        *args,
        window_samples: int = 12,
        load_bound_pu: float = 0.35,
        load_slew_pu_per_s: float = 0.04,
        smoothness_weight: float = 12.0,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.window_samples = int(max(window_samples, 3))
        self.load_bound = float(load_bound_pu)
        self.load_slew = float(load_slew_pu_per_s)
        self.smoothness_weight = float(smoothness_weight)
        self._times: deque[float] = deque(maxlen=self.window_samples)
        self._observed: deque[np.ndarray] = deque(maxlen=self.window_samples)
        self._load = np.zeros(2)

    def update(self, measurement: LoadObserverInput) -> LoadEstimate:
        observed = self.balance_observation(measurement)
        self._times.append(float(measurement.time_s))
        self._observed.append(observed.copy())
        values = np.asarray(self._observed)
        if len(values) < 3:
            self._load = values.mean(axis=0)
            return self.result(self._load, observed)
        time = np.asarray(self._times)
        dt = np.diff(time)
        load = cp.Variable(values.shape)
        constraints = [load >= -self.load_bound, load <= self.load_bound]
        constraints += [cp.abs(load[1:] - load[:-1]) <= self.load_slew * dt[:, None]]
        objective = cp.sum_squares(load - values) + self.smoothness_weight * cp.sum_squares(load[1:] - load[:-1])
        problem = cp.Problem(cp.Minimize(objective), constraints)
        try:
            problem.solve(solver=cp.CLARABEL, warm_start=True, max_iter=100, verbose=False)
        except Exception:
            problem = None
        if problem is not None and problem.status in {"optimal", "optimal_inaccurate"} and load.value is not None:
            self._load = np.asarray(load.value[-1]).ravel()
        else:
            self._load = np.median(values, axis=0)
        return self.result(self._load, observed)


__all__ = [
    "AugmentedKalmanLoadObserver",
    "UnknownInputLoadObserver",
    "ConstrainedGridLoadMHE",
]

