"""Deployable Phase-I baselines.

Only `RollingContractMPC` is named MPC and it inherits the full rolling
optimization, prediction, delay, ramp, energy and diagnostic machinery.
"""

from __future__ import annotations

import numpy as np

from .dcsv_mpc_final import RollingContractMPC
from direction5freq.models.plant_a_full import PublicObservation


class FixedAllocationPI:
    name = "fixed_allocation_pi"
    is_true_rolling_mpc = False

    def __init__(self, period_s: float, kp: float = 0.42, ki: float = 0.025) -> None:
        self.period_s = float(period_s)
        self.kp = float(kp); self.ki = float(ki)
        self.integral = np.zeros(2)

    def propose(self, observation: PublicObservation) -> np.ndarray:
        self.integral += observation.ace_pu * self.period_s
        total = np.clip(-self.kp * observation.ace_pu - self.ki * self.integral, -0.12, 0.12)
        return np.array((0.75 * total[0], 0.25 * total[0], 0.75 * total[1], 0.25 * total[1]))


__all__ = ["FixedAllocationPI", "RollingContractMPC"]
