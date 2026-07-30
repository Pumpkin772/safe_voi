"""SG-only terminal backup box and reachability checks."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class SGTerminalBackupSet:
    frequency_hz: float = 0.30
    ace_pu: float = 0.15
    tie_pu: float = 0.08
    sg_power_pu: float = 0.10

    def contains(self, state: np.ndarray, c_ace: np.ndarray, nominal_frequency_hz: float = 50.0) -> bool:
        vector = np.asarray(state, dtype=float)
        return bool(
            np.max(np.abs(nominal_frequency_hz * vector[:2])) <= self.frequency_hz
            and np.max(np.abs(c_ace @ vector)) <= self.ace_pu
            and abs(vector[2]) <= self.tie_pu
            and np.max(np.abs(vector[5:7])) <= self.sg_power_pu
        )
