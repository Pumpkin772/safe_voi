"""Shared, physical BESS PFR/SFR capability and energy dynamics."""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np


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
    ramp_pu_per_s: float = 0.08
    maximum_delay_s: float = 2.0

    @property
    def rating_pu(self) -> float:
        return self.rating_mw / self.system_base_mva


@dataclass(frozen=True, slots=True)
class CapabilityRegime:
    """Simulator truth; this object must never cross a controller API."""

    headroom_fraction: tuple[float, float] = (1.0, 1.0)
    ramp_fraction: tuple[float, float] = (1.0, 1.0)
    delay_s: tuple[float, float] = (0.2, 0.2)
    availability: tuple[float, float] = (1.0, 1.0)
    reactive_power_pu: tuple[float, float] = (0.0, 0.0)
    service_fraction: tuple[float, float] = (1.0, 1.0)


@dataclass(frozen=True, slots=True)
class BESSFleetState:
    power_pu: np.ndarray
    energy_mwh: np.ndarray
    delay_queue_pu: np.ndarray

    @classmethod
    def equilibrium(
        cls, params: BESSParameters, dt_s: float, soc: tuple[float, float] = (0.5, 0.5),
    ) -> "BESSFleetState":
        queue_length = int(math.ceil(params.maximum_delay_s / dt_s)) + 2
        return cls(
            power_pu=np.zeros(2),
            energy_mwh=params.energy_mwh * np.asarray(soc, dtype=float),
            delay_queue_pu=np.zeros((2, queue_length)),
        )


@dataclass(frozen=True, slots=True)
class BESSDiagnostics:
    pfr_target_pu: np.ndarray
    sfr_target_pu: np.ndarray
    total_target_pu: np.ndarray
    delayed_target_pu: np.ndarray
    lower_power_pu: np.ndarray
    upper_power_pu: np.ndarray
    ramp_limit_pu_per_s: np.ndarray
    energy_residual_mwh: np.ndarray


def _energy_derivative_mwh_s(power_pu: np.ndarray, params: BESSParameters) -> np.ndarray:
    physical_mw = power_pu * params.system_base_mva
    return np.where(
        physical_mw >= 0,
        -physical_mw / params.eta_discharge / 3600.0,
        -physical_mw * params.eta_charge / 3600.0,
    )


def current_capability(
    state: BESSFleetState, params: BESSParameters, regime: CapabilityRegime, dt_s: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    availability = np.asarray(regime.availability) * np.asarray(regime.service_fraction)
    apparent = np.sqrt(np.maximum(params.rating_pu**2 - np.asarray(regime.reactive_power_pu) ** 2, 0.0))
    headroom = params.rating_pu * np.asarray(regime.headroom_fraction)
    symmetric = np.minimum(apparent, headroom) * availability
    e_min = params.soc_min * params.energy_mwh
    e_max = params.soc_max * params.energy_mwh
    discharge_energy = np.maximum(state.energy_mwh - e_min, 0.0) * params.eta_discharge * 3600.0 / (params.system_base_mva * dt_s)
    charge_energy = np.maximum(e_max - state.energy_mwh, 0.0) / params.eta_charge * 3600.0 / (params.system_base_mva * dt_s)
    upper = np.minimum(symmetric, discharge_energy)
    lower = -np.minimum(symmetric, charge_energy)
    ramp = params.ramp_pu_per_s * np.asarray(regime.ramp_fraction) * availability
    return lower, upper, ramp


def step_bess_fleet(
    state: BESSFleetState,
    omega_pu: np.ndarray,
    sfr_command_pu: np.ndarray,
    params: BESSParameters,
    regime: CapabilityRegime,
    dt_s: float,
) -> tuple[BESSFleetState, BESSDiagnostics]:
    """Advance both resources without SoC projection or free boundary energy."""

    omega = np.asarray(omega_pu, dtype=float)
    sfr = np.asarray(sfr_command_pu, dtype=float)
    pfr = -params.pfr_gain_pu_power_per_pu_frequency * omega
    lower, upper, ramp = current_capability(state, params, regime, dt_s)
    total = np.clip(pfr + sfr, lower, upper)

    queue = np.roll(state.delay_queue_pu, -1, axis=1)
    queue[:, -1] = total
    delay_steps = np.rint(np.asarray(regime.delay_s) / dt_s).astype(int)
    delay_steps = np.clip(delay_steps, 0, queue.shape[1] - 1)
    delayed = np.array([queue[i, -1 - delay_steps[i]] for i in range(2)])

    raw_rate = (delayed - state.power_pu) / params.actuator_time_constant_s
    rate = np.clip(raw_rate, -ramp, ramp)
    next_power = state.power_pu + dt_s * rate
    # Do not numerically step past either the delayed target or the physical set.
    increasing = delayed >= state.power_pu
    next_power = np.where(increasing, np.minimum(next_power, delayed), np.maximum(next_power, delayed))
    next_power = np.minimum(np.maximum(next_power, lower), upper)

    average_power = 0.5 * (state.power_pu + next_power)
    delta_energy = dt_s * _energy_derivative_mwh_s(average_power, params)
    next_energy = state.energy_mwh + delta_energy
    # The power-side one-step constraint guarantees these bounds. Crossing is an error,
    # never repaired by projecting SoC back into the interval.
    e_min = params.soc_min * params.energy_mwh
    e_max = params.soc_max * params.energy_mwh
    if np.any(next_energy < e_min - 1e-10) or np.any(next_energy > e_max + 1e-10):
        raise RuntimeError("BESS energy bound crossed despite one-step capability constraint")
    residual = next_energy - state.energy_mwh - delta_energy
    next_state = BESSFleetState(next_power, next_energy, queue)
    diagnostics = BESSDiagnostics(pfr, sfr, total, delayed, lower, upper, ramp, residual)
    return next_state, diagnostics

