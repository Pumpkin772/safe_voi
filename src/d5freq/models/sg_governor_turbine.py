"""Governor/turbine dynamics with mechanical-power GRC and reserve limits."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SGParameters:
    droop_pu_frequency_per_pu_power: float = 0.05
    governor_time_constant_s: float = 0.2
    turbine_time_constant_s: float = 0.5
    reserve_up_pu: float = 0.10
    reserve_down_pu: float = 0.10
    grc_up_pu_s: float = 0.01
    grc_down_pu_s: float = 0.01
    antiwindup_gain: float = 2.0


@dataclass(frozen=True, slots=True)
class SGState:
    valve_pu: float = 0.0
    mechanical_pu: float = 0.0


def derivatives(state: SGState, params: SGParameters, omega_pu: float, sfr_command_pu: float) -> SGState:
    raw_error = -state.valve_pu - omega_pu / params.droop_pu_frequency_per_pu_power + sfr_command_pu
    if state.mechanical_pu >= params.reserve_up_pu and raw_error > 0:
        raw_error -= params.antiwindup_gain * (state.mechanical_pu - params.reserve_up_pu)
    if state.mechanical_pu <= -params.reserve_down_pu and raw_error < 0:
        raw_error -= params.antiwindup_gain * (state.mechanical_pu + params.reserve_down_pu)
    valve_dot = raw_error / params.governor_time_constant_s
    mech_raw = (state.valve_pu - state.mechanical_pu) / params.turbine_time_constant_s
    mech_dot = min(max(mech_raw, -params.grc_down_pu_s), params.grc_up_pu_s)
    if state.mechanical_pu >= params.reserve_up_pu and mech_dot > 0:
        mech_dot = 0.0
    if state.mechanical_pu <= -params.reserve_down_pu and mech_dot < 0:
        mech_dot = 0.0
    return SGState(valve_pu=valve_dot, mechanical_pu=mech_dot)


def step_sg(state: SGState, params: SGParameters, omega_pu: float, sfr_command_pu: float, dt_s: float) -> SGState:
    d = derivatives(state, params, omega_pu, sfr_command_pu)
    mechanical = state.mechanical_pu + dt_s * d.mechanical_pu
    mechanical = min(max(mechanical, -params.reserve_down_pu), params.reserve_up_pu)
    return SGState(valve_pu=state.valve_pu + dt_s * d.valve_pu, mechanical_pu=mechanical)
