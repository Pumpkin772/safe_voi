"""Causal augmented observer for Phase-G state and load estimation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import cont2discrete

from direction1freq.models.plant_a_v2 import PublicObservationV2
from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2


@dataclass(frozen=True, slots=True)
class StructuredObserverEstimate:
    state_pu: np.ndarray
    load_pu: np.ndarray
    covariance: np.ndarray
    innovation: np.ndarray


class StructuredLoadStateObserver:
    """Estimate nine plant states and two slowly varying loads causally.

    The public measurement vector is frequency, tie flow, SG mechanical power,
    and actual BESS power. Valve states remain hidden states of the observer;
    they are never copied from mechanical power. The only input is the command
    that was already issued during the preceding interval.
    """

    def __init__(
        self,
        period_s: float,
        *,
        plant: TwoAreaPlantAV2 | None = None,
        measurement_std: tuple[float, ...] = (
            2.0e-5,
            2.0e-5,
            2.0e-4,
            4.0e-4,
            4.0e-4,
            4.0e-4,
            4.0e-4,
        ),
        load_random_walk_std_pu: float = 1.5e-3,
    ) -> None:
        self.period_s = float(period_s)
        if self.period_s <= 0.0:
            raise ValueError("period_s must be positive")
        self.plant = TwoAreaPlantAV2() if plant is None else plant
        a, b, _c_ace, e = self.plant.linear_continuous_model_separate()
        augmented_a = np.block(
            [[a, e], [np.zeros((2, 9)), np.zeros((2, 2))]]
        )
        augmented_b = np.vstack([b, np.zeros((2, 4))])
        c = np.zeros((7, 11))
        measured_indices = (0, 1, 2, 5, 6, 7, 8)
        for row, index in enumerate(measured_indices):
            c[row, index] = 1.0
        d = np.zeros((7, 4))
        discrete = cont2discrete(
            (augmented_a, augmented_b, c, d), self.period_s, method="zoh"
        )
        self.A = np.asarray(discrete[0], dtype=float)
        self.B = np.asarray(discrete[1], dtype=float)
        self.C = c
        state_process = np.array(
            [2e-5, 2e-5, 2e-4, 6e-4, 6e-4, 4e-4, 4e-4, 4e-4, 4e-4]
        )
        self.Q = np.diag(
            np.r_[state_process**2, [load_random_walk_std_pu**2] * 2]
        )
        measurement = np.asarray(measurement_std, dtype=float)
        if measurement.shape != (7,) or np.any(measurement <= 0.0):
            raise ValueError("measurement_std must contain seven positive values")
        self.R = np.diag(measurement**2)
        self.reset()

    def reset(self) -> None:
        self.x = np.zeros(11)
        initial_std = np.array(
            [1e-3, 1e-3, 3e-3, 2e-2, 2e-2, 1e-2, 1e-2, 1e-2, 1e-2, 3e-2, 3e-2]
        )
        self.P = np.diag(initial_std**2)
        self.previous_command = np.zeros(4)

    def update(self, observation: PublicObservationV2) -> StructuredObserverEstimate:
        measurement = np.r_[
            np.asarray(observation.frequency_deviation_hz, dtype=float)
            / self.plant.parameters.nominal_frequency_hz,
            float(observation.tie_line_pu),
            np.asarray(observation.sg_mechanical_power_pu, dtype=float),
            np.asarray(observation.bess_power_pu, dtype=float),
        ]
        if measurement.shape != (7,) or not np.all(np.isfinite(measurement)):
            raise ValueError("public observation is nonfinite or has the wrong shape")
        prior = self.A @ self.x + self.B @ self.previous_command
        prior_covariance = self.A @ self.P @ self.A.T + self.Q
        innovation = measurement - self.C @ prior
        innovation_covariance = self.C @ prior_covariance @ self.C.T + self.R
        gain = np.linalg.solve(
            innovation_covariance, self.C @ prior_covariance
        ).T
        self.x = prior + gain @ innovation
        identity = np.eye(11)
        update = identity - gain @ self.C
        self.P = update @ prior_covariance @ update.T + gain @ self.R @ gain.T
        self.P = 0.5 * (self.P + self.P.T)
        command = np.asarray(observation.issued_command_pu, dtype=float)
        if command.shape != (4,) or not np.all(np.isfinite(command)):
            raise ValueError("issued command must be a finite four-vector")
        self.previous_command = command.copy()
        return StructuredObserverEstimate(
            state_pu=self.x[:9].copy(),
            load_pu=self.x[9:11].copy(),
            covariance=self.P.copy(),
            innovation=innovation.copy(),
        )
