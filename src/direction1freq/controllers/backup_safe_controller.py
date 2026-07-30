"""Reliable SG-only backup controller used by active probing and Phase-E methods."""

from __future__ import annotations

import numpy as np

from direction1freq.controllers.ace_pi_aw import ACEPIAntiWindup, design_stable_pi
from direction1freq.models.plant_a_v2 import PublicObservationV2, TwoAreaPlantAV2


class SGBackupSafeController:
    def __init__(self, period_s: float, reserve_pu: float) -> None:
        kp, ki, _ = design_stable_pi(TwoAreaPlantAV2(), period_s)
        self.controller = ACEPIAntiWindup(period_s, kp, ki, sg_fraction=1.0)
        self.reserve_pu = float(reserve_pu)

    def reset(self) -> None:
        self.controller.reset()

    def update(self, observation: PublicObservationV2) -> np.ndarray:
        action, _ = self.controller.update(observation)
        action[[0, 2]] = np.clip(action[[0, 2]], -self.reserve_pu, self.reserve_pu)
        action[[1, 3]] = 0.0
        return action
