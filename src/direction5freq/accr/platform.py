"""Registered ACCR benchmark-platform utilities.

The one-hour profile is a synthetic operational-quality test signal.  It is
not presented as measured grid data.  Its sample mean and linear trend are
removed before a fixed physical scaling is applied on the 1000 MVA base.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from direction5freq.controllers.anti_windup_pi import FixedAllocationAntiWindupPI
from direction5freq.controllers.contract_robust_mpc import (
    ContractOnlyRollingRobustMPC,
    NominalOffsetFreeMPC,
)
from direction5freq.controllers.dcsv_mpc_final import DCSVInput
from direction5freq.controllers.domain_supervisor import DomainSupervisor
from direction5freq.estimation.deliverability_set_membership import DeliverabilitySetMembership
from direction5freq.estimation.grid_load_mhe import ConstrainedGridLoadMHE
from direction5freq.estimation.grid_load_observer import LoadObserverInput
from direction5freq.models.capability_contract import CapabilityRealization
from direction5freq.models.plant_a_full import PlantAParameters, PublicObservation


NORMAL_PROFILE_PROVENANCE = (
    "SYNTHETIC_STATIONARY_ZERO_MEAN_AR1_MULTISINE_NOT_PUBLIC_MEASURED"
)


def normal_load_profile(seed: int, duration_s: int = 3600) -> np.ndarray:
    """Return a bounded, detrended two-area operational load profile in pu."""

    rng = np.random.default_rng(np.random.SeedSequence([20260810, int(seed), 1001]))
    count = int(duration_s) + 1
    values = np.zeros((count, 2), dtype=float)
    innovations = rng.normal(0.0, 0.00022, (count, 2))
    for index in range(1, count):
        values[index] = 0.985 * values[index - 1] + innovations[index]
    time_s = np.arange(count, dtype=float)
    values += np.column_stack((
        0.0032 * np.sin(2.0 * np.pi * time_s / 760.0),
        0.0028 * np.sin(2.0 * np.pi * time_s / 910.0 + 0.37),
    ))
    # Remove sample mean and linear drift without looking at controller output.
    centered_time = time_s - np.mean(time_s)
    for area in range(2):
        slope = float(np.dot(centered_time, values[:, area]) / np.dot(centered_time, centered_time))
        values[:, area] -= np.mean(values[:, area]) + slope * centered_time
    return np.clip(values, -0.012, 0.012)


def interpolate_profile(profile: np.ndarray, time_s: float) -> np.ndarray:
    position = min(max(float(time_s), 0.0), len(profile) - 1.0)
    lower = int(np.floor(position))
    upper = min(lower + 1, len(profile) - 1)
    fraction = position - lower
    return (1.0 - fraction) * profile[lower] + fraction * profile[upper]


def normal_capability(seed: int, time_s: float) -> CapabilityRealization:
    """Contract-containing unannounced power/ramp/delay changes for A0."""

    mechanism = int(seed) % 3
    if time_s < 1200.0:
        return CapabilityRealization()
    if mechanism == 0:
        changed = CapabilityRealization(
            lower_power_pu=(-0.055, -0.052), upper_power_pu=(0.055, 0.052)
        )
    elif mechanism == 1:
        changed = CapabilityRealization(
            ramp_down_pu_per_s=(0.032, 0.030), ramp_up_pu_per_s=(0.032, 0.030)
        )
    else:
        changed = CapabilityRealization(delay_s=(1.10, 1.20))
    if time_s < 2400.0:
        return changed
    return CapabilityRealization(
        lower_power_pu=tuple(np.minimum(np.asarray(changed.lower_power_pu) * 1.08, -0.050)),
        upper_power_pu=tuple(np.maximum(np.asarray(changed.upper_power_pu) * 1.08, 0.050)),
        ramp_down_pu_per_s=tuple(np.maximum(np.asarray(changed.ramp_down_pu_per_s) * 1.08, 0.028)),
        ramp_up_pu_per_s=tuple(np.maximum(np.asarray(changed.ramp_up_pu_per_s) * 1.08, 0.028)),
        delay_s=tuple(np.maximum(np.asarray(changed.delay_s) - 0.15, 0.10)),
    )


class A0BaselinePolicy:
    """Public-I/O-only policy for the registered A0 baseline qualification."""

    def __init__(
        self,
        method: str,
        period_s: float,
        parameters: PlantAParameters,
        horizon_steps: int = 3,
    ) -> None:
        self.method = method
        self.period_s = float(period_s)
        self.parameters = parameters
        self.observer = ConstrainedGridLoadMHE(
            nominal_frequency_hz=parameters.nominal_frequency_hz,
            inertia_s=parameters.inertia_s,
            damping_pu_per_pu_frequency=parameters.damping_pu_per_pu_frequency,
            derivative_filter=0.40,
            warmup_samples=8,
        )
        self.estimator = DeliverabilitySetMembership(parameters.bess.contract, period_s)
        self.supervisor = DomainSupervisor(parameters)
        self.last_command = np.zeros(4)
        self.reserve_request = np.zeros(2)
        self.calls: list[dict[str, Any]] = []
        if method == "fixed_allocation_anti_windup_pi":
            self.controller: Any = FixedAllocationAntiWindupPI(period_s)
        elif method == "contract_only_rolling_mpc":
            self.controller = ContractOnlyRollingRobustMPC(period_s, horizon_steps, parameters)
        elif method == "nominal_offset_free_mpc":
            self.controller = NominalOffsetFreeMPC(period_s, horizon_steps, parameters)
        else:
            raise ValueError(method)

    def update(self, observation: PublicObservation) -> tuple[np.ndarray, np.ndarray]:
        load = self.observer.update(LoadObserverInput(
            time_s=observation.time_s,
            frequency_deviation_hz=observation.frequency_deviation_hz,
            tie_line_pu=observation.tie_line_pu,
            sg_mechanical_power_pu=observation.sg_mechanical_power_pu,
            bess_actual_poi_power_pu=observation.bess_actual_power_pu,
            slow_reserve_power_pu=observation.slow_reserve_power_pu,
        ))
        requested = (
            -self.parameters.bess.pfr_gain_pu_power_per_pu_frequency
            * observation.frequency_deviation_hz / self.parameters.nominal_frequency_hz
            + self.last_command[[1, 3]]
        )
        envelope = self.estimator.update(
            observation.time_s, requested, observation.bess_actual_power_pu
        )
        domain = self.supervisor.classify(load.load_pu, observation.measured_soc)
        if self.method == "fixed_allocation_anti_windup_pi":
            action = self.controller.propose(observation)
            reserve = domain.equilibrium_slow_reserve_pu
            call = {"attempted_solver_calls": 0, "solve_time_s": 0.0, "fallback_used": False}
        else:
            result = self.controller.propose(DCSVInput(observation, load.load_pu, envelope, domain))
            action = result.proposed_action_pu.copy()
            reserve = result.slow_reserve_request_pu.copy()
            self.controller.commit(action, observation.bess_actual_power_pu)
            diagnostics = result.diagnostics
            call = {
                "attempted_solver_calls": int(getattr(diagnostics, "attempted_optimization_calls", 1)),
                "solve_time_s": float(diagnostics.solve_time_s),
                "fallback_used": bool(diagnostics.fallback_used),
            }
        action = np.asarray(action, dtype=float)
        action[[0, 2]] = np.clip(action[[0, 2]], self.parameters.valve_lower_pu, self.parameters.valve_upper_pu)
        action[[1, 3]] = np.clip(action[[1, 3]], -self.parameters.bess.rating_pu, self.parameters.bess.rating_pu)
        self.last_command = action.copy()
        self.reserve_request = np.asarray(reserve, dtype=float).copy()
        self.calls.append(call)
        return action, self.reserve_request


__all__ = [
    "A0BaselinePolicy", "NORMAL_PROFILE_PROVENANCE", "interpolate_profile",
    "normal_capability", "normal_load_profile",
]
