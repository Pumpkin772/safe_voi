"""Finite power-ramp-energy certificate for slow-reserve handoff."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from direction5freq.models.plant_a_full import PlantAParameters


@dataclass(frozen=True, slots=True)
class BridgeCertificate:
    load_pu: np.ndarray
    initial_deficit_pu: np.ndarray
    handoff_time_s: float
    required_energy_mwh: float
    available_energy_mwh: float
    power_margin_pu: float
    ramp_margin_pu_per_s: float
    energy_margin_mwh: float
    certified: bool
    claim_level: str


def compute_bridge_certificate(load_pu: np.ndarray, measured_soc: np.ndarray) -> BridgeCertificate:
    p = PlantAParameters()
    load = np.asarray(load_pu, dtype=float)
    soc = np.asarray(measured_soc, dtype=float)
    sg = np.asarray(p.sg_power_upper_pu)
    reserve_max = np.asarray(p.slow_reserve.upper_pu)
    reserve_ramp = np.asarray(p.slow_reserve.ramp_up_pu_per_s)
    deficit = np.maximum(load - sg, 0.0)
    handoff = float(np.max(deficit / np.maximum(reserve_ramp, 1e-12)))
    # Area-wise linear slow-reserve ramp: BESS supplies a triangular deficit.
    required_pu_s = float(np.sum(0.5 * deficit * handoff))
    delay_buffer_pu_s = float(np.sum(deficit) * max(p.bess.contract.maximum_delay_s))
    required_energy = (required_pu_s + delay_buffer_pu_s) * p.system_base_mva / 3600.0 / p.bess.eta_discharge
    available_energy = float(np.sum((soc - p.bess.soc_min) * p.bess.energy_mwh))
    power_margin = float(np.min(np.asarray(p.bess.contract.upper_power_pu) - deficit))
    ramp_margin = float(np.min(np.asarray(p.bess.contract.ramp_up_pu_per_s) - reserve_ramp))
    energy_margin = available_energy - required_energy
    certified = bool(
        np.all(deficit > 0.0)
        and np.all(load <= sg + reserve_max)
        and power_margin >= -1e-12
        and ramp_margin >= -1e-12
        and energy_margin >= -1e-12
    )
    return BridgeCertificate(
        load_pu=load,
        initial_deficit_pu=deficit,
        handoff_time_s=handoff,
        required_energy_mwh=required_energy,
        available_energy_mwh=available_energy,
        power_margin_pu=power_margin,
        ramp_margin_pu_per_s=ramp_margin,
        energy_margin_mwh=energy_margin,
        certified=certified,
        claim_level="FINITE_HORIZON_BRIDGE_TO_SLOW_RESERVE" if certified else "NO_BRIDGE_CERTIFICATE",
    )
