"""Shared PFR/SFR BESS capability and energy-conserving actuator."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class BESSParameters:
    system_base_mw: float = 1000.0
    rating_mw: float = 100.0
    energy_mwh: float = 50.0
    reactive_mvar: float = 30.0
    voltage_pu: float = 1.0
    current_limit_pu: float = 0.11
    eta_charge: float = 0.95
    eta_discharge: float = 0.95
    soc_min: float = 0.1
    soc_max: float = 0.9
    ramp_pu_s: float = 0.08
    actuator_time_constant_s: float = 0.15
    sustainable_horizon_s: float = 30.0
    pfr_gain_pu_power_per_pu_frequency: float = 4.0

    def __post_init__(self) -> None:
        if min(self.system_base_mw, self.rating_mw, self.energy_mwh) <= 0:
            raise ValueError("power and energy ratings must be positive")
        if not 0 <= self.soc_min < self.soc_max <= 1:
            raise ValueError("invalid SoC bounds")
        if not 0 < self.eta_charge <= 1 or not 0 < self.eta_discharge <= 1:
            raise ValueError("efficiencies must be in (0,1]")

    @property
    def rating_pu(self) -> float:
        return self.rating_mw / self.system_base_mw

    @property
    def q_pu(self) -> float:
        return self.reactive_mvar / self.system_base_mw

    @property
    def apparent_active_limit_pu(self) -> float:
        return math.sqrt(max((self.voltage_pu * self.current_limit_pu) ** 2 - self.q_pu**2, 0.0))


@dataclass(frozen=True, slots=True)
class BESSState:
    power_pu: float = 0.0
    energy_mwh: float = 25.0

    def soc(self, params: BESSParameters) -> float:
        return self.energy_mwh / params.energy_mwh


@dataclass(frozen=True, slots=True)
class BESSCapability:
    lower_pu: float
    upper_pu: float
    ramp_lower_pu: float
    ramp_upper_pu: float
    active_limit_pu: float
    available: bool


@dataclass(frozen=True, slots=True)
class BESSStepResult:
    state: BESSState
    pfr_pu: float
    sfr_pu: float
    target_total_pu: float
    applied_total_pu: float
    energy_residual_mwh: float
    constraint_active: tuple[str, ...]
    curtailed_pu: float


def capability(
    state: BESSState,
    params: BESSParameters,
    dt_s: float,
    *,
    availability: float = 1.0,
    headroom_fraction: float = 1.0,
    ramp_fraction: float = 1.0,
) -> BESSCapability:
    """Return the one-step feasible set for total AC active power."""

    if dt_s <= 0:
        raise ValueError("dt_s must be positive")
    a = min(max(float(availability), 0.0), 1.0)
    h = min(max(float(headroom_fraction), 0.0), 1.0)
    r = min(max(float(ramp_fraction), 0.0), 1.0)
    active = min(params.rating_pu, params.apparent_active_limit_pu) * a * h
    e_min = params.soc_min * params.energy_mwh
    e_max = params.soc_max * params.energy_mwh
    discharge_step = 3600.0 * params.eta_discharge * max(state.energy_mwh - e_min, 0.0) / (dt_s * params.system_base_mw)
    charge_step = 3600.0 * max(e_max - state.energy_mwh, 0.0) / (params.eta_charge * dt_s * params.system_base_mw)
    discharge_sustainable = 3600.0 * params.eta_discharge * max(state.energy_mwh - e_min, 0.0) / (params.sustainable_horizon_s * params.system_base_mw)
    charge_sustainable = 3600.0 * max(e_max - state.energy_mwh, 0.0) / (params.eta_charge * params.sustainable_horizon_s * params.system_base_mw)
    upper = min(active, discharge_step, discharge_sustainable)
    lower = -min(active, charge_step, charge_sustainable)
    delta = params.ramp_pu_s * r * dt_s
    return BESSCapability(
        lower_pu=lower,
        upper_pu=upper,
        ramp_lower_pu=max(lower, state.power_pu - delta),
        ramp_upper_pu=min(upper, state.power_pu + delta),
        active_limit_pu=active,
        available=a > 0,
    )


def step_bess(
    state: BESSState,
    params: BESSParameters,
    omega_pu: float,
    sfr_command_pu: float,
    dt_s: float,
    *,
    availability: float = 1.0,
    headroom_fraction: float = 1.0,
    ramp_fraction: float = 1.0,
) -> BESSStepResult:
    """Advance with power-side energy feasibility; never project SoC."""

    cap = capability(
        state, params, dt_s, availability=availability,
        headroom_fraction=headroom_fraction, ramp_fraction=ramp_fraction,
    )
    pfr = -params.pfr_gain_pu_power_per_pu_frequency * float(omega_pu)
    target = pfr + float(sfr_command_pu)
    lagged = state.power_pu + dt_s * (target - state.power_pu) / params.actuator_time_constant_s
    applied = min(max(lagged, cap.ramp_lower_pu), cap.ramp_upper_pu)
    active: list[str] = []
    if abs(applied - lagged) > 1e-12:
        active.append("shared_power_ramp_energy")
    p_mw = applied * params.system_base_mw
    flow_mwh = dt_s / 3600.0 * (
        max(p_mw, 0.0) / params.eta_discharge + params.eta_charge * min(p_mw, 0.0)
    )
    energy = state.energy_mwh - flow_mwh
    residual = energy - state.energy_mwh + flow_mwh
    return BESSStepResult(
        state=BESSState(power_pu=applied, energy_mwh=energy),
        pfr_pu=pfr,
        sfr_pu=float(sfr_command_pu),
        target_total_pu=target,
        applied_total_pu=applied,
        energy_residual_mwh=residual,
        constraint_active=tuple(active),
        curtailed_pu=target - applied,
    )
