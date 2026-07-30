"""Worst-case capability-set rolling MPC baseline."""

from __future__ import annotations

import numpy as np

from direction1freq.models.plant_a_v2 import PublicObservationV2

from .nominal_mpc import FiniteHorizonMPC, MPCDiagnostics


class RobustCapabilityMPC:
    """Uses the full preregistered uncertainty set, never a hidden current label."""

    def __init__(self, period_s: float = 4.0, horizon: int = 6) -> None:
        # Worst delay and certified minimum symmetric external capability.
        self.optimizer = FiniteHorizonMPC(period_s, horizon, nominal_delay_s=min(2.0, period_s - 1e-6))
        self.certified_bess_limit = 0.02
        self.certified_bess_slew = 0.02

    def reset(self) -> None:
        self.optimizer.reset()

    def update(
        self,
        observation: PublicObservationV2,
        estimated_state: np.ndarray,
        causal_load_estimate: np.ndarray,
        sg_reserve_pu: float,
    ) -> tuple[np.ndarray, MPCDiagnostics]:
        del observation
        lower = np.array([-sg_reserve_pu, -self.certified_bess_limit, -sg_reserve_pu, -self.certified_bess_limit])
        upper = -lower
        return self.optimizer.solve(
            estimated_state, causal_load_estimate, lower, upper,
            np.array([-self.certified_bess_limit] * 2), np.array([self.certified_bess_limit] * 2),
            np.array([0.04, self.certified_bess_slew, 0.04, self.certified_bess_slew]),
            delay_s=min(2.0, self.optimizer.period_s - 1e-6),
        )
