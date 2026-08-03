"""Finite power--ramp--energy bridge certificate calculations."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from direction5_freq.models.sustainability_classifier import CapabilityContract, DomainResult


@dataclass(frozen=True, slots=True)
class BridgeCertificate:
    power_feasible: bool
    ramp_delay_feasible: bool
    energy_feasible: bool
    slow_reserve_handoff_feasible: bool
    frequency_bound_hz: float
    ace_bound_pu: float
    tie_bound_pu: float
    safety_feasible: bool
    finite_horizon_viable: bool


def certify_bridge(
    result: DomainResult,
    contract: CapabilityContract,
    period_s: float,
    nominal_frequency_hz: float,
    minimum_inertia_s: float = 4.5,
) -> BridgeCertificate:
    power = np.asarray(result.bridge_bess_power_pu, dtype=float)
    power_feasible = bool(
        np.all(power >= contract.power_lower_pu - 1e-10)
        and np.all(power <= contract.power_upper_pu + 1e-10)
    )
    effective = np.maximum(period_s - contract.delay_s, 0.0)
    ramp_capacity = np.where(
        power >= 0.0,
        contract.ramp_up_pu_per_s * effective,
        contract.ramp_down_pu_per_s * effective,
    )
    ramp_delay = bool(np.all(np.abs(power) <= ramp_capacity + 1e-10))
    energy = bool(
        np.all(result.bridge_energy_required_mwh <= contract.energy_available_mwh + 1e-10)
    )
    # Conservative impulse bound before delayed/ramped bridge power is fully
    # delivered. It is finite-horizon and does not assume a recursive backup.
    relevant_ramp = np.where(
        power >= 0.0, contract.ramp_up_pu_per_s, contract.ramp_down_pu_per_s
    )
    ramp_time = np.divide(
        np.abs(power),
        relevant_ramp,
        out=np.full(2, np.inf),
        where=relevant_ramp > 0.0,
    )
    impulse = np.abs(power) * (contract.delay_s + 0.5 * ramp_time)
    frequency = float(nominal_frequency_hz * np.max(impulse) / (2.0 * minimum_inertia_s))
    tie = abs(float(result.bridge_tie_pu))
    ace = float(21.0 * frequency / nominal_frequency_hz + tie)
    safety = bool(frequency <= 0.80 and ace <= 0.30 and tie <= 0.15)
    handoff = bool(result.slow_reserve_equilibrium.feasible)
    viable = power_feasible and ramp_delay and energy and safety and handoff
    return BridgeCertificate(
        power_feasible,
        ramp_delay,
        energy,
        handoff,
        frequency,
        ace,
        tie,
        safety,
        viable,
    )
