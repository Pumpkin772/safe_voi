"""Causal load observer using actual BESS POI power as a known input."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class LoadObserverInput:
    time_s: float
    frequency_deviation_hz: np.ndarray
    tie_line_pu: float
    sg_mechanical_power_pu: np.ndarray
    bess_actual_poi_power_pu: np.ndarray
    slow_reserve_power_pu: np.ndarray


@dataclass(frozen=True, slots=True)
class LoadEstimate:
    load_pu: np.ndarray
    instantaneous_balance_load_pu: np.ndarray
    warmed: bool
    samples: int


class GridLoadObserver:
    """Augmented slow-state observer for persistent net-load increments.

    The load is one slow state per area.  It is updated from a causal backward
    frequency derivative and the measured mechanical, reserve, tie-line, and
    actual BESS POI powers.  Issued BESS commands are intentionally absent from
    this API.
    """

    def __init__(
        self,
        nominal_frequency_hz: float,
        inertia_s: tuple[float, float],
        damping_pu_per_pu_frequency: tuple[float, float],
        state_gain: float = 0.18,
        derivative_filter: float = 0.25,
        warmup_samples: int = 20,
    ) -> None:
        self.nominal_frequency_hz = float(nominal_frequency_hz)
        self.inertia = np.asarray(inertia_s, dtype=float)
        self.damping = np.asarray(damping_pu_per_pu_frequency, dtype=float)
        self.state_gain = float(state_gain)
        self.derivative_filter = float(derivative_filter)
        self.warmup_samples = int(warmup_samples)
        self._previous_time: float | None = None
        self._previous_omega: np.ndarray | None = None
        self._filtered_derivative = np.zeros(2)
        self._load = np.zeros(2)
        self._samples = 0

    def update(self, measurement: LoadObserverInput) -> LoadEstimate:
        omega = np.asarray(measurement.frequency_deviation_hz, dtype=float) / self.nominal_frequency_hz
        if self._previous_time is None:
            derivative = np.zeros(2)
        else:
            dt_s = float(measurement.time_s - self._previous_time)
            if dt_s <= 0.0:
                raise ValueError("load observer timestamps must increase")
            derivative = (omega - self._previous_omega) / dt_s
        self._filtered_derivative = (
            self.derivative_filter * derivative
            + (1.0 - self.derivative_filter) * self._filtered_derivative
        )
        tie = np.array((measurement.tie_line_pu, -measurement.tie_line_pu))
        instantaneous = (
            np.asarray(measurement.sg_mechanical_power_pu)
            + np.asarray(measurement.bess_actual_poi_power_pu)
            + np.asarray(measurement.slow_reserve_power_pu)
            - self.damping * omega
            - tie
            - 2.0 * self.inertia * self._filtered_derivative
        )
        self._load += self.state_gain * (instantaneous - self._load)
        self._previous_time = float(measurement.time_s)
        self._previous_omega = omega.copy()
        self._samples += 1
        return LoadEstimate(
            load_pu=self._load.copy(),
            instantaneous_balance_load_pu=instantaneous,
            warmed=self._samples >= self.warmup_samples,
            samples=self._samples,
        )
