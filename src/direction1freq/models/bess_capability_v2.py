"""Phase-E physical BESS/IBR capability, shared PFR/SFR, delay, and energy."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from direction1freq.simulation.delay_channel import CausalDelayChannel, DelayChannelState


@dataclass(frozen=True, slots=True)
class BESSParametersV2:
    system_base_mva: float = 1000.0
    rating_mw: float = 100.0
    energy_mwh: float = 50.0
    soc_min: float = 0.10
    soc_max: float = 0.90
    eta_charge: float = 0.95
    eta_discharge: float = 0.95
    pfr_gain_pu_power_per_pu_frequency: float = 2.5
    actuator_time_constant_s: float = 0.15
    ramp_up_pu_per_s: float = 0.08
    ramp_down_pu_per_s: float = 0.08
    maximum_delay_s: float = 2.0
    base_power_pu: tuple[float, float] = (0.0, 0.0)

    @property
    def rating_pu(self) -> float:
        return self.rating_mw / self.system_base_mva


@dataclass(frozen=True, slots=True)
class CapabilityTruthV2:
    """Evaluation-side truth.  It is intentionally absent from controller APIs."""

    upper_headroom_fraction: tuple[float, float] = (1.0, 1.0)
    lower_headroom_fraction: tuple[float, float] = (1.0, 1.0)
    ramp_up_fraction: tuple[float, float] = (1.0, 1.0)
    ramp_down_fraction: tuple[float, float] = (1.0, 1.0)
    delay_s: tuple[float, float] = (0.2, 0.2)
    availability: tuple[float, float] = (1.0, 1.0)
    service_fraction: tuple[float, float] = (1.0, 1.0)
    reactive_power_pu: tuple[float, float] = (0.0, 0.0)
    accessible_energy_fraction: tuple[float, float] = (1.0, 1.0)


@dataclass(frozen=True, slots=True)
class BESSStateV2:
    power_pu: np.ndarray
    energy_mwh: np.ndarray
    delay: DelayChannelState

    @classmethod
    def equilibrium(
        cls, parameters: BESSParametersV2, dt_s: float, soc: tuple[float, float] = (0.5, 0.5),
    ) -> "BESSStateV2":
        channel = CausalDelayChannel(2, dt_s, parameters.maximum_delay_s)
        return cls(
            power_pu=np.zeros(2),
            energy_mwh=parameters.energy_mwh * np.asarray(soc, dtype=float),
            delay=channel.equilibrium(),
        )


@dataclass(frozen=True, slots=True)
class CapabilitySnapshotV2:
    lower_power_pu: np.ndarray
    upper_power_pu: np.ndarray
    ramp_down_pu_per_s: np.ndarray
    ramp_up_pu_per_s: np.ndarray
    lower_energy_mwh: np.ndarray
    upper_energy_mwh: np.ndarray
    delay_s: np.ndarray
    availability: np.ndarray


@dataclass(frozen=True, slots=True)
class BESSDiagnosticsV2:
    pfr_target_pu: np.ndarray
    sfr_target_pu: np.ndarray
    requested_total_pu: np.ndarray
    delayed_request_pu: np.ndarray
    feasible_target_pu: np.ndarray
    capability: CapabilitySnapshotV2
    actual_ramp_pu_per_s: np.ndarray
    energy_residual_mwh: np.ndarray
    power_saturation: np.ndarray
    energy_boundary_active: np.ndarray


def _energy_bounds(
    parameters: BESSParametersV2, truth: CapabilityTruthV2,
) -> tuple[np.ndarray, np.ndarray]:
    physical_lower = parameters.soc_min * parameters.energy_mwh
    physical_upper = parameters.soc_max * parameters.energy_mwh
    midpoint = 0.5 * (physical_lower + physical_upper)
    half_width = 0.5 * (physical_upper - physical_lower) * np.asarray(truth.accessible_energy_fraction)
    return midpoint - half_width, midpoint + half_width


def current_capability_v2(
    state: BESSStateV2,
    parameters: BESSParametersV2,
    truth: CapabilityTruthV2,
    dt_s: float,
) -> CapabilitySnapshotV2:
    availability = np.asarray(truth.availability, dtype=float) * np.asarray(truth.service_fraction, dtype=float)
    apparent = np.sqrt(np.maximum(parameters.rating_pu**2 - np.asarray(truth.reactive_power_pu) ** 2, 0.0))
    upper = np.minimum(apparent, parameters.rating_pu * np.asarray(truth.upper_headroom_fraction)) * availability
    lower_magnitude = np.minimum(apparent, parameters.rating_pu * np.asarray(truth.lower_headroom_fraction)) * availability

    lower_energy, upper_energy = _energy_bounds(parameters, truth)
    discharge_pu = (
        np.maximum(state.energy_mwh - lower_energy, 0.0)
        * parameters.eta_discharge * 3600.0 / (parameters.system_base_mva * dt_s)
    )
    charge_pu = (
        np.maximum(upper_energy - state.energy_mwh, 0.0)
        / parameters.eta_charge * 3600.0 / (parameters.system_base_mva * dt_s)
    )
    upper = np.minimum(upper, discharge_pu)
    lower = -np.minimum(lower_magnitude, charge_pu)
    ramp_up = parameters.ramp_up_pu_per_s * np.asarray(truth.ramp_up_fraction) * availability
    ramp_down = parameters.ramp_down_pu_per_s * np.asarray(truth.ramp_down_fraction) * availability
    return CapabilitySnapshotV2(
        lower_power_pu=lower,
        upper_power_pu=upper,
        ramp_down_pu_per_s=ramp_down,
        ramp_up_pu_per_s=ramp_up,
        lower_energy_mwh=lower_energy,
        upper_energy_mwh=upper_energy,
        delay_s=np.asarray(truth.delay_s, dtype=float),
        availability=availability,
    )


def _energy_derivative(power_pu: np.ndarray, parameters: BESSParametersV2) -> np.ndarray:
    power_mw = parameters.system_base_mva * power_pu
    return np.where(
        power_mw >= 0.0,
        -power_mw / parameters.eta_discharge / 3600.0,
        -power_mw * parameters.eta_charge / 3600.0,
    )


def step_bess_v2(
    state: BESSStateV2,
    omega_pu: np.ndarray,
    sfr_command_pu: np.ndarray,
    parameters: BESSParametersV2,
    truth: CapabilityTruthV2,
    dt_s: float,
) -> tuple[BESSStateV2, BESSDiagnosticsV2]:
    """Advance the physical actuator without post-hoc SoC projection."""

    omega = np.asarray(omega_pu, dtype=float)
    sfr = np.asarray(sfr_command_pu, dtype=float)
    if omega.shape != (2,) or sfr.shape != (2,):
        raise ValueError("omega and SFR command must each contain two areas")
    pfr = -parameters.pfr_gain_pu_power_per_pu_frequency * omega
    requested = np.asarray(parameters.base_power_pu) + pfr + sfr
    channel = CausalDelayChannel(2, dt_s, parameters.maximum_delay_s)
    next_delay, delayed = channel.step(state.delay, requested, np.asarray(truth.delay_s))
    capability = current_capability_v2(state, parameters, truth, dt_s)
    feasible = np.minimum(np.maximum(delayed, capability.lower_power_pu), capability.upper_power_pu)

    raw_rate = (feasible - state.power_pu) / parameters.actuator_time_constant_s
    rate = np.minimum(np.maximum(raw_rate, -capability.ramp_down_pu_per_s), capability.ramp_up_pu_per_s)
    next_power = state.power_pu + dt_s * rate
    increasing = feasible >= state.power_pu
    next_power = np.where(increasing, np.minimum(next_power, feasible), np.maximum(next_power, feasible))
    next_power = np.minimum(np.maximum(next_power, capability.lower_power_pu), capability.upper_power_pu)

    average_power = 0.5 * (state.power_pu + next_power)
    delta_energy = dt_s * _energy_derivative(average_power, parameters)
    next_energy = state.energy_mwh + delta_energy
    if np.any(next_energy < capability.lower_energy_mwh - 1e-9) or np.any(next_energy > capability.upper_energy_mwh + 1e-9):
        raise RuntimeError("BESS energy crossed the current accessible bound; no projection is permitted")
    residual = next_energy - state.energy_mwh - delta_energy
    diagnostics = BESSDiagnosticsV2(
        pfr_target_pu=pfr,
        sfr_target_pu=sfr,
        requested_total_pu=requested,
        delayed_request_pu=delayed,
        feasible_target_pu=feasible,
        capability=capability,
        actual_ramp_pu_per_s=rate,
        energy_residual_mwh=residual,
        power_saturation=np.abs(delayed - feasible) > 1e-12,
        energy_boundary_active=(
            (next_energy <= capability.lower_energy_mwh + 1e-9)
            | (next_energy >= capability.upper_energy_mwh - 1e-9)
        ),
    )
    return BESSStateV2(next_power, next_energy, next_delay), diagnostics
