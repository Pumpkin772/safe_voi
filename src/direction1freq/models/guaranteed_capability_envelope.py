"""Controller-visible guaranteed capability contract, never a truth label."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class GuaranteedCapabilityEnvelope:
    power_upper_pu: np.ndarray
    power_lower_pu: np.ndarray
    ramp_up_pu_per_s: np.ndarray
    ramp_down_pu_per_s: np.ndarray
    delay_vertices_s: tuple[float, ...]
    energy_window_mwh: np.ndarray
    energy_midpoint_mwh: np.ndarray
    eta_charge: float = 0.95
    eta_discharge: float = 0.95
    system_base_mva: float = 1000.0
    source: str = "registered Phase-E mechanism floors plus service contract"

    def __post_init__(self) -> None:
        for name in (
            "power_upper_pu",
            "power_lower_pu",
            "ramp_up_pu_per_s",
            "ramp_down_pu_per_s",
            "energy_window_mwh",
            "energy_midpoint_mwh",
        ):
            value = np.asarray(getattr(self, name), dtype=float)
            if value.shape != (2,) or not np.all(np.isfinite(value)):
                raise ValueError(f"{name} must be a finite two-area vector")
            object.__setattr__(self, name, value.copy())
        if np.any(self.power_upper_pu <= 0.0) or np.any(self.power_lower_pu >= 0.0):
            raise ValueError("power envelope must straddle zero")
        if np.any(self.ramp_up_pu_per_s <= 0.0) or np.any(
            self.ramp_down_pu_per_s <= 0.0
        ):
            raise ValueError("ramp floors must be positive")
        if np.any(self.energy_window_mwh <= 0.0):
            raise ValueError("energy window must be positive")
        if tuple(sorted(self.delay_vertices_s)) != self.delay_vertices_s:
            raise ValueError("delay vertices must be sorted")

    @classmethod
    def phase_f_registered(cls) -> "GuaranteedCapabilityEnvelope":
        return cls(
            power_upper_pu=np.full(2, 0.03),
            power_lower_pu=np.full(2, -0.03),
            ramp_up_pu_per_s=np.full(2, 0.012),
            ramp_down_pu_per_s=np.full(2, 0.012),
            delay_vertices_s=(0.2, 0.6, 1.0, 1.6, 1.999),
            energy_window_mwh=np.full(2, 0.8),
            energy_midpoint_mwh=np.full(2, 25.0),
        )

    @property
    def energy_lower_mwh(self) -> np.ndarray:
        return self.energy_midpoint_mwh - self.energy_window_mwh

    @property
    def energy_upper_mwh(self) -> np.ndarray:
        return self.energy_midpoint_mwh + self.energy_window_mwh

    def command_slew(self, period_s: float) -> np.ndarray:
        return np.minimum(
            period_s * self.ramp_up_pu_per_s,
            self.power_upper_pu - self.power_lower_pu,
        )

    def total_bess_power(
        self,
        sfr_command_pu: np.ndarray,
        omega_pu: np.ndarray,
        pfr_gain_pu_power_per_pu_frequency: float = 2.5,
    ) -> np.ndarray:
        """Shared PFR+SFR quantity constrained by the envelope."""

        return np.asarray(sfr_command_pu, dtype=float) - (
            pfr_gain_pu_power_per_pu_frequency
            * np.asarray(omega_pu, dtype=float)
        )

    def next_energy_mwh(
        self,
        energy_mwh: np.ndarray,
        discharge_pu: np.ndarray,
        charge_pu: np.ndarray,
        period_s: float,
    ) -> np.ndarray:
        discharge = np.asarray(discharge_pu, dtype=float)
        charge = np.asarray(charge_pu, dtype=float)
        if np.any(discharge < 0.0) or np.any(charge < 0.0):
            raise ValueError("split power variables must be nonnegative")
        return np.asarray(energy_mwh, dtype=float) - (
            period_s
            * self.system_base_mva
            / 3600.0
            * (discharge / self.eta_discharge - self.eta_charge * charge)
        )

