"""Pre-controller physical-domain classification."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from direction5freq.models.plant_a_full import PlantAParameters


@dataclass(frozen=True, slots=True)
class DomainDecision:
    domain: str
    equilibrium_sg_power_pu: np.ndarray
    equilibrium_slow_reserve_pu: np.ndarray
    bridge_remaining_s: float
    bridge_energy_required_mwh: float
    physical_margin_pu: np.ndarray
    certificate_reason: str


class DomainSupervisor:
    def __init__(self, parameters: PlantAParameters | None = None) -> None:
        self.parameters = PlantAParameters() if parameters is None else parameters

    def classify(self, load_estimate_pu: np.ndarray, measured_soc: np.ndarray) -> DomainDecision:
        load = np.maximum(np.asarray(load_estimate_pu, dtype=float), 0.0)
        sg = np.asarray(self.parameters.sg_power_upper_pu)
        reserve = np.asarray(self.parameters.slow_reserve.upper_pu)
        total = sg + reserve
        physical_margin = total - load
        if np.any(load > total + 1e-12):
            return DomainDecision(
                domain="PHYSICALLY_INFEASIBLE",
                equilibrium_sg_power_pu=np.minimum(load, sg),
                equilibrium_slow_reserve_pu=np.minimum(np.maximum(load - sg, 0.0), reserve),
                bridge_remaining_s=0.0,
                bridge_energy_required_mwh=np.inf,
                physical_margin_pu=physical_margin,
                certificate_reason="steady load exceeds registered SG plus slow-reserve power",
            )
        equilibrium_sg = np.minimum(load, sg)
        equilibrium_reserve = np.maximum(load - equilibrium_sg, 0.0)
        if np.all(equilibrium_reserve <= 1e-12):
            return DomainDecision(
                domain="SUSTAINABLE",
                equilibrium_sg_power_pu=equilibrium_sg,
                equilibrium_slow_reserve_pu=np.zeros(2),
                bridge_remaining_s=0.0,
                bridge_energy_required_mwh=0.0,
                physical_margin_pu=physical_margin,
                certificate_reason="load-parameterized equilibrium uses SG without net BESS energy",
            )
        ramp = np.asarray(self.parameters.slow_reserve.ramp_up_pu_per_s)
        handoff = float(np.max(equilibrium_reserve / np.maximum(ramp, 1e-12)))
        triangular_pu_s = float(np.sum(0.5 * equilibrium_reserve * handoff))
        required_mwh = triangular_pu_s * self.parameters.system_base_mva / 3600.0
        usable_mwh = float(np.sum(
            (np.asarray(measured_soc) - self.parameters.bess.soc_min)
            * self.parameters.bess.energy_mwh
            * self.parameters.bess.eta_discharge
        ))
        if usable_mwh + 1e-12 < required_mwh:
            domain = "PHYSICALLY_INFEASIBLE"
            reason = "measured SoC cannot bridge the finite-ramp slow-reserve handoff"
        else:
            domain = "BRIDGE"
            reason = "finite BESS energy bridges until ramp-limited slow reserve reaches equilibrium"
        return DomainDecision(
            domain=domain,
            equilibrium_sg_power_pu=equilibrium_sg,
            equilibrium_slow_reserve_pu=equilibrium_reserve,
            bridge_remaining_s=handoff,
            bridge_energy_required_mwh=required_mwh,
            physical_margin_pu=physical_margin,
            certificate_reason=reason,
        )
