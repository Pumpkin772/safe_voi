"""Bridge-state bookkeeping shared by DCSV-MPC and H6 certificates."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class BridgeState:
    remaining_time_s: float
    remaining_energy_mwh: np.ndarray
    required_power_pu: np.ndarray
    registered_slow_reserve: bool

    def advance(
        self,
        actual_bess_power_pu: np.ndarray,
        period_s: float,
        system_base_mva: float = 1000.0,
        eta_discharge: float = 0.95,
        eta_charge: float = 0.95,
    ) -> "BridgeState":
        power = np.asarray(actual_bess_power_pu, dtype=float)
        used = np.where(
            power >= 0.0,
            power * system_base_mva * period_s / (3600.0 * eta_discharge),
            -power * system_base_mva * period_s * eta_charge / 3600.0,
        )
        return BridgeState(
            max(self.remaining_time_s - period_s, 0.0),
            np.maximum(self.remaining_energy_mwh - used, 0.0),
            self.required_power_pu.copy(),
            self.registered_slow_reserve,
        )
