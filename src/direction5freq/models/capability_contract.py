"""Physical BESS actuator and the Phase-I contract/performance semantics.

The physical realization is evaluation-side truth and is never part of an
ordinary controller input.  Only power, ramp, and delay can be hidden.  Energy
is a measured state; availability has no separate latent variable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True, slots=True)
class CapabilityContract:
    lower_power_pu: tuple[float, float] = (-0.045, -0.045)
    upper_power_pu: tuple[float, float] = (0.045, 0.045)
    ramp_down_pu_per_s: tuple[float, float] = (0.025, 0.025)
    ramp_up_pu_per_s: tuple[float, float] = (0.025, 0.025)
    maximum_delay_s: tuple[float, float] = (1.50, 1.50)


@dataclass(frozen=True, slots=True)
class CapabilityRealization:
    """Evaluation-only command-to-actual capability truth."""

    lower_power_pu: tuple[float, float] = (-0.080, -0.080)
    upper_power_pu: tuple[float, float] = (0.080, 0.080)
    ramp_down_pu_per_s: tuple[float, float] = (0.060, 0.060)
    ramp_up_pu_per_s: tuple[float, float] = (0.060, 0.060)
    delay_s: tuple[float, float] = (0.20, 0.20)

    def contains_contract(self, contract: CapabilityContract) -> bool:
        return bool(
            np.all(np.asarray(self.lower_power_pu) <= np.asarray(contract.lower_power_pu))
            and np.all(np.asarray(self.upper_power_pu) >= np.asarray(contract.upper_power_pu))
            and np.all(np.asarray(self.ramp_down_pu_per_s) >= np.asarray(contract.ramp_down_pu_per_s))
            and np.all(np.asarray(self.ramp_up_pu_per_s) >= np.asarray(contract.ramp_up_pu_per_s))
            and np.all(np.asarray(self.delay_s) <= np.asarray(contract.maximum_delay_s))
        )


@dataclass(frozen=True, slots=True)
class BESSParameters:
    system_base_mva: float = 1000.0
    rating_mw: float = 100.0
    energy_mwh: float = 50.0
    soc_min: float = 0.10
    soc_max: float = 0.90
    eta_charge: float = 0.95
    eta_discharge: float = 0.95
    pfr_gain_pu_power_per_pu_frequency: float = 2.5
    actuator_time_constant_s: float = 0.15
    maximum_physical_delay_s: float = 3.0
    contract: CapabilityContract = field(default_factory=CapabilityContract)

    @property
    def rating_pu(self) -> float:
        return self.rating_mw / self.system_base_mva


@dataclass(frozen=True, slots=True)
class DelayPipelineState:
    samples: np.ndarray


@dataclass(frozen=True, slots=True)
class BESSState:
    power_pu: np.ndarray
    energy_mwh: np.ndarray
    delay_pipeline: DelayPipelineState

    @classmethod
    def equilibrium(
        cls, parameters: BESSParameters, dt_s: float, soc: tuple[float, float] = (0.5, 0.5)
    ) -> "BESSState":
        count = int(np.ceil(parameters.maximum_physical_delay_s / dt_s)) + 3
        return cls(
            power_pu=np.zeros(2),
            energy_mwh=parameters.energy_mwh * np.asarray(soc, dtype=float),
            delay_pipeline=DelayPipelineState(np.zeros((count, 2))),
        )

    def measured_soc(self, parameters: BESSParameters) -> np.ndarray:
        return self.energy_mwh / parameters.energy_mwh


@dataclass(frozen=True, slots=True)
class BESSDiagnostics:
    pfr_target_pu: np.ndarray
    sfr_target_pu: np.ndarray
    requested_total_pu: np.ndarray
    delayed_request_pu: np.ndarray
    feasible_target_pu: np.ndarray
    actual_ramp_pu_per_s: np.ndarray
    energy_residual_mwh: np.ndarray
    power_saturation: np.ndarray
    ramp_saturation: np.ndarray
    energy_boundary_active: np.ndarray
    measured_soc: np.ndarray
    contract_violation_truth: bool


def _delayed_sample(samples: np.ndarray, delay_s: np.ndarray, dt_s: float) -> np.ndarray:
    result = np.empty(2)
    for area in range(2):
        steps = float(delay_s[area] / dt_s)
        lower = int(np.floor(steps))
        fraction = steps - lower
        recent = samples[-1 - lower, area]
        older = samples[-2 - lower, area]
        result[area] = (1.0 - fraction) * recent + fraction * older
    return result


def step_bess(
    state: BESSState,
    omega_pu: np.ndarray,
    sfr_command_pu: np.ndarray,
    parameters: BESSParameters,
    realization: CapabilityRealization,
    dt_s: float,
) -> tuple[BESSState, BESSDiagnostics]:
    """Advance the physical actuator with continuous-delay interpolation."""

    omega = np.asarray(omega_pu, dtype=float)
    sfr = np.asarray(sfr_command_pu, dtype=float)
    if omega.shape != (2,) or sfr.shape != (2,):
        raise ValueError("omega and SFR command must each contain two areas")
    delay = np.asarray(realization.delay_s, dtype=float)
    if np.any(delay < 0.0) or np.any(delay > parameters.maximum_physical_delay_s):
        raise ValueError("physical delay is outside registered pipeline capacity")

    pfr = -parameters.pfr_gain_pu_power_per_pu_frequency * omega
    requested = pfr + sfr
    samples = np.vstack((state.delay_pipeline.samples[1:], requested))
    delayed = _delayed_sample(samples, delay, dt_s)

    lower = np.maximum(np.asarray(realization.lower_power_pu), -parameters.rating_pu)
    upper = np.minimum(np.asarray(realization.upper_power_pu), parameters.rating_pu)
    soc = state.measured_soc(parameters)
    discharge_energy_limit = (
        np.maximum(state.energy_mwh - parameters.soc_min * parameters.energy_mwh, 0.0)
        * parameters.eta_discharge * 3600.0 / (parameters.system_base_mva * dt_s)
    )
    charge_energy_limit = (
        np.maximum(parameters.soc_max * parameters.energy_mwh - state.energy_mwh, 0.0)
        / parameters.eta_charge * 3600.0 / (parameters.system_base_mva * dt_s)
    )
    lower = np.maximum(lower, -charge_energy_limit)
    upper = np.minimum(upper, discharge_energy_limit)
    feasible = np.clip(delayed, lower, upper)

    raw_rate = (feasible - state.power_pu) / parameters.actuator_time_constant_s
    ramp_down = np.asarray(realization.ramp_down_pu_per_s)
    ramp_up = np.asarray(realization.ramp_up_pu_per_s)
    rate = np.clip(raw_rate, -ramp_down, ramp_up)
    next_power = state.power_pu + dt_s * rate
    next_power = np.where(feasible >= state.power_pu, np.minimum(next_power, feasible), np.maximum(next_power, feasible))
    next_power = np.clip(next_power, lower, upper)

    average_power = 0.5 * (state.power_pu + next_power)
    power_mw = parameters.system_base_mva * average_power
    delta_energy = np.where(
        power_mw >= 0.0,
        -dt_s * power_mw / parameters.eta_discharge / 3600.0,
        -dt_s * power_mw * parameters.eta_charge / 3600.0,
    )
    next_energy = state.energy_mwh + delta_energy
    physical_lower = parameters.soc_min * parameters.energy_mwh
    physical_upper = parameters.soc_max * parameters.energy_mwh
    if np.any(next_energy < physical_lower - 1e-9) or np.any(next_energy > physical_upper + 1e-9):
        raise RuntimeError("measured BESS energy crossed a physical bound")
    energy_residual = next_energy - state.energy_mwh - delta_energy
    next_state = BESSState(next_power, next_energy, DelayPipelineState(samples))
    diagnostics = BESSDiagnostics(
        pfr_target_pu=pfr,
        sfr_target_pu=sfr,
        requested_total_pu=requested,
        delayed_request_pu=delayed,
        feasible_target_pu=feasible,
        actual_ramp_pu_per_s=rate,
        energy_residual_mwh=energy_residual,
        power_saturation=np.abs(delayed - feasible) > 1e-12,
        ramp_saturation=np.abs(raw_rate - rate) > 1e-12,
        energy_boundary_active=(next_energy <= physical_lower + 1e-8) | (next_energy >= physical_upper - 1e-8),
        measured_soc=soc,
        contract_violation_truth=not realization.contains_contract(parameters.contract),
    )
    return next_state, diagnostics
