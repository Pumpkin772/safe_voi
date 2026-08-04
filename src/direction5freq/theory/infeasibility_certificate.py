"""Early physical infeasibility certificates."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from direction5freq.models.plant_a_full import PlantAParameters
from .bridge_certificate import compute_bridge_certificate


@dataclass(frozen=True, slots=True)
class InfeasibilityCertificate:
    load_pu: np.ndarray
    measured_soc: np.ndarray
    certificate_type: str
    violation_margin: float
    certified_infeasible: bool
    reason: str


def compute_infeasibility_certificate(load_pu: np.ndarray, measured_soc: np.ndarray) -> InfeasibilityCertificate:
    p = PlantAParameters()
    load = np.asarray(load_pu, dtype=float)
    soc = np.asarray(measured_soc, dtype=float)
    steady_capacity = np.asarray(p.sg_power_upper_pu) + np.asarray(p.slow_reserve.upper_pu)
    steady_violation = load - steady_capacity
    if np.any(steady_violation > 0.0):
        return InfeasibilityCertificate(
            load, soc, "STEADY_POWER_INFEASIBLE", float(np.max(steady_violation)), True,
            "load-parameterized equilibrium exceeds SG plus slow-reserve power",
        )
    if np.any(load > np.asarray(p.sg_power_upper_pu)):
        bridge = compute_bridge_certificate(load, soc)
        if not bridge.certified:
            return InfeasibilityCertificate(
                load, soc, "BRIDGE_POWER_RAMP_ENERGY_INFEASIBLE",
                float(max(-bridge.power_margin_pu, -bridge.ramp_margin_pu_per_s, -bridge.energy_margin_mwh)),
                True,
                "finite-energy BESS cannot satisfy the registered slow-reserve handoff conditions",
            )
    return InfeasibilityCertificate(load, soc, "NOT_INFEASIBLE", 0.0, False, "no registered physical impossibility condition is active")
