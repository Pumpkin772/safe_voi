"""Auditable deficit fields for H2 physically infeasible cells."""

from __future__ import annotations

import numpy as np

from direction5_freq.models.sustainability_classifier import CapabilityContract


def deficit_components(
    load_pu: np.ndarray,
    sg_reserve_pu: float,
    slow_reserve_additional_pu: np.ndarray,
    contract: CapabilityContract,
    period_s: float,
    slow_reserve_arrival_s: float,
) -> dict[str, float]:
    load = np.asarray(load_pu, dtype=float)
    effective_time = np.maximum(period_s - contract.delay_s, 0.0)
    ramp_power = np.minimum(
        contract.power_upper_pu,
        contract.ramp_up_pu_per_s * effective_time,
    )
    steady_capacity = 2.0 * sg_reserve_pu + float(
        np.sum(slow_reserve_additional_pu)
    )
    steady_shortfall = max(float(np.sum(np.abs(load))) - steady_capacity, 0.0)
    pre_reserve_need = max(float(np.sum(np.abs(load))) - 2.0 * sg_reserve_pu, 0.0)
    power_shortfall = max(pre_reserve_need - float(np.sum(np.abs(contract.power_upper_pu))), 0.0)
    ramp_shortfall = max(pre_reserve_need - float(np.sum(ramp_power)), 0.0)
    required_energy = pre_reserve_need * 1000.0 * slow_reserve_arrival_s / (3600.0 * 0.95)
    energy_shortfall = max(required_energy - float(np.sum(contract.energy_available_mwh)), 0.0)
    return {
        "steady_state_power_shortfall_pu": steady_shortfall,
        "pre_reserve_power_shortfall_pu": power_shortfall,
        "ramp_delay_shortfall_pu": ramp_shortfall,
        "energy_shortfall_mwh": energy_shortfall,
    }
