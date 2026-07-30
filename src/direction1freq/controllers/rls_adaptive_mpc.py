"""Causal RLS effectiveness estimate coupled to a true rolling MPC."""

from __future__ import annotations

import numpy as np

from direction1freq.models.plant_a_v2 import PublicObservationV2

from .nominal_mpc import FiniteHorizonMPC, MPCDiagnostics


class RLSAdaptiveMPC:
    def __init__(self, period_s: float = 4.0, horizon: int = 6, forgetting_factor: float = 0.98) -> None:
        self.optimizer = FiniteHorizonMPC(period_s, horizon, nominal_delay_s=0.2)
        self.forgetting_factor = float(forgetting_factor)
        self.effectiveness = np.ones(2)
        self.covariance = np.ones(2) * 10.0
        self.previous_bess_command = np.zeros(2)
        self.previous_bess_power = np.zeros(2)

    def reset(self) -> None:
        self.optimizer.reset()
        self.effectiveness = np.ones(2)
        self.covariance = np.ones(2) * 10.0
        self.previous_bess_command = np.zeros(2)
        self.previous_bess_power = np.zeros(2)

    def _rls_update(self, measured_bess_power: np.ndarray) -> None:
        for area in range(2):
            regressor = self.previous_bess_command[area]
            if abs(regressor) < 2e-3:
                continue
            covariance = self.covariance[area]
            gain = covariance * regressor / (
                self.forgetting_factor + regressor * covariance * regressor
            )
            innovation = measured_bess_power[area] - self.effectiveness[area] * regressor
            self.effectiveness[area] = float(np.clip(self.effectiveness[area] + gain * innovation, 0.2, 1.0))
            self.covariance[area] = float(
                np.clip((covariance - gain * regressor * covariance) / self.forgetting_factor, 1e-3, 100.0)
            )

    def update(
        self,
        observation: PublicObservationV2,
        estimated_state: np.ndarray,
        causal_load_estimate: np.ndarray,
        sg_reserve_pu: float,
    ) -> tuple[np.ndarray, MPCDiagnostics]:
        self._rls_update(np.asarray(observation.bess_power_pu))
        limits = 0.10 * self.effectiveness
        lower = np.array([-sg_reserve_pu, -limits[0], -sg_reserve_pu, -limits[1]])
        upper = -lower
        action, diagnostics = self.optimizer.solve(
            estimated_state, causal_load_estimate, lower, upper, -limits, limits,
            np.array([0.05, 0.08 * self.effectiveness[0], 0.05, 0.08 * self.effectiveness[1]]),
            delay_s=0.2,
        )
        self.previous_bess_command = action[[1, 3]].copy()
        self.previous_bess_power = np.asarray(observation.bess_power_pu).copy()
        return action, diagnostics
