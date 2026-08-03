"""Pre-controller physical classification for sustainable and bridge domains."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog

from .load_parameterized_equilibrium import (
    EquilibriumResult,
    solve_sustainable_equilibrium,
)


@dataclass(frozen=True, slots=True)
class CapabilityContract:
    name: str
    known_ood: str
    power_lower_pu: np.ndarray
    power_upper_pu: np.ndarray
    ramp_down_pu_per_s: np.ndarray
    ramp_up_pu_per_s: np.ndarray
    delay_s: np.ndarray
    energy_available_mwh: np.ndarray
    availability: np.ndarray


@dataclass(frozen=True, slots=True)
class DomainResult:
    classification: str
    reason: str
    equilibrium: EquilibriumResult
    bridge_sg_power_pu: np.ndarray
    bridge_bess_power_pu: np.ndarray
    bridge_tie_pu: float
    bridge_energy_required_mwh: np.ndarray
    bridge_power_balance_residual_pu: np.ndarray
    slow_reserve_equilibrium: EquilibriumResult
    binding_constraints: tuple[str, ...]


def _infeasible_equilibrium(load: np.ndarray, message: str) -> EquilibriumResult:
    nan2 = np.full(2, np.nan)
    return EquilibriumResult(
        False,
        load.copy(),
        nan2,
        float("nan"),
        nan2,
        np.full(9, np.nan),
        nan2,
        message,
    )


def _bridge_lp(
    load: np.ndarray,
    sg_reserve: float,
    tie_limit: float,
    contract: CapabilityContract,
    period_s: float,
) -> tuple[bool, np.ndarray, np.ndarray, float, str, tuple[str, ...]]:
    effective_ramp_time = np.maximum(period_s - contract.delay_s, 0.0)
    ramp_lower = -contract.ramp_down_pu_per_s * effective_ramp_time
    ramp_upper = contract.ramp_up_pu_per_s * effective_ramp_time
    lower = np.maximum(contract.power_lower_pu, ramp_lower)
    upper = np.minimum(contract.power_upper_pu, ramp_upper)
    lower = np.where(contract.availability > 0.0, lower, 0.0)
    upper = np.where(contract.availability > 0.0, upper, 0.0)
    if np.any(lower > upper + 1e-12):
        return False, np.full(2, np.nan), np.full(2, np.nan), float("nan"), "empty power/ramp interval", ("ramp",)
    # z = [pm1, pm2, tie, pb1, pb2, |pb1|, |pb2|]
    objective = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0])
    equality = np.array(
        [
            [1.0, 0.0, -1.0, 1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0],
        ]
    )
    inequality = np.array(
        [
            [0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0],
            [0.0, 0.0, 0.0, -1.0, 0.0, -1.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0],
            [0.0, 0.0, 0.0, 0.0, -1.0, 0.0, -1.0],
        ]
    )
    result = linprog(
        objective,
        A_ub=inequality,
        b_ub=np.zeros(4),
        A_eq=equality,
        b_eq=load,
        bounds=[
            (-sg_reserve, sg_reserve),
            (-sg_reserve, sg_reserve),
            (-tie_limit, tie_limit),
            (float(lower[0]), float(upper[0])),
            (float(lower[1]), float(upper[1])),
            (0.0, None),
            (0.0, None),
        ],
        method="highs",
    )
    if not result.success:
        binding = ["power"]
        if np.any(effective_ramp_time <= 0.0):
            binding.append("delay")
        if np.any(ramp_upper < contract.power_upper_pu - 1e-12) or np.any(
            ramp_lower > contract.power_lower_pu + 1e-12
        ):
            binding.append("ramp")
        return (
            False,
            np.full(2, np.nan),
            np.full(2, np.nan),
            float("nan"),
            str(result.message),
            tuple(binding),
        )
    return (
        True,
        np.asarray(result.x[:2]),
        np.asarray(result.x[3:5]),
        float(result.x[2]),
        str(result.message),
        (),
    )


def classify_physical_domain(
    load_pu: np.ndarray,
    sg_reserve_pu: float,
    tie_limit_pu: float,
    contract: CapabilityContract,
    period_s: float,
    slow_reserve_arrival_s: float,
    slow_reserve_additional_pu: np.ndarray,
    system_base_mva: float = 1000.0,
    eta_discharge: float = 0.95,
    eta_charge: float = 0.95,
) -> DomainResult:
    load = np.asarray(load_pu, dtype=float)
    sustainable = solve_sustainable_equilibrium(
        load,
        np.full(2, -sg_reserve_pu),
        np.full(2, sg_reserve_pu),
        tie_limit_pu,
    )
    if sustainable.feasible:
        return DomainResult(
            "SUSTAINABLE",
            "nonzero BESS steady power not required",
            sustainable,
            np.zeros(2),
            np.zeros(2),
            sustainable.tie_pu,
            np.zeros(2),
            sustainable.balance_residual_pu.copy(),
            sustainable,
            (),
        )

    post_reserve = solve_sustainable_equilibrium(
        load,
        -np.full(2, sg_reserve_pu) - np.asarray(slow_reserve_additional_pu),
        np.full(2, sg_reserve_pu) + np.asarray(slow_reserve_additional_pu),
        tie_limit_pu,
    )
    if not post_reserve.feasible:
        return DomainResult(
            "PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY",
            "steady-state power remains infeasible after registered slow reserve",
            sustainable,
            np.full(2, np.nan),
            np.full(2, np.nan),
            float("nan"),
            np.full(2, np.nan),
            np.full(2, np.nan),
            post_reserve,
            ("steady_state_power", "sg_or_tie"),
        )

    feasible, sg, bess, tie, message, binding = _bridge_lp(
        load, sg_reserve_pu, tie_limit_pu, contract, period_s
    )
    if not feasible:
        return DomainResult(
            "PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY",
            f"pre-reserve bridge power/ramp/delay infeasible: {message}",
            sustainable,
            sg,
            bess,
            tie,
            np.full(2, np.nan),
            np.full(2, np.nan),
            post_reserve,
            binding,
        )

    active_duration = np.maximum(slow_reserve_arrival_s - contract.delay_s, 0.0)
    energy = np.where(
        bess >= 0.0,
        bess * system_base_mva * active_duration / (3600.0 * eta_discharge),
        -bess * system_base_mva * active_duration * eta_charge / 3600.0,
    )
    balance = np.array(
        [sg[0] + bess[0] - load[0] - tie, sg[1] + bess[1] - load[1] + tie]
    )
    if np.any(energy > contract.energy_available_mwh + 1e-12):
        return DomainResult(
            "PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY",
            "finite bridge energy exceeds registered accessible energy",
            sustainable,
            sg,
            bess,
            tie,
            energy,
            balance,
            post_reserve,
            ("energy",),
        )
    active = []
    if np.any(np.isclose(bess, contract.power_lower_pu, atol=1e-9)) or np.any(
        np.isclose(bess, contract.power_upper_pu, atol=1e-9)
    ):
        active.append("power")
    if np.any(np.isclose(energy, contract.energy_available_mwh, atol=1e-9)):
        active.append("energy")
    return DomainResult(
        "BRIDGE_ONLY",
        "finite-energy BESS bridge reaches registered slow-reserve sustainable equilibrium",
        sustainable,
        sg,
        bess,
        tie,
        energy,
        balance,
        post_reserve,
        tuple(active),
    )
