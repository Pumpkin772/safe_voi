"""Strict sustainable terminal-window semantics for DCSV-MPC."""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class TerminalWindowFlags:
    sustainable: bool
    event_free_full_horizon: bool
    close_to_load_parameterized_equilibrium: bool
    valve_not_at_bound: bool
    mechanical_not_at_bound: bool
    grc_inactive: bool
    bess_power_limit_inactive: bool
    bess_ramp_limit_inactive: bool
    bess_energy_limit_inactive: bool
    command_unsaturated: bool
    observer_warmed: bool
    no_solver_or_fallback_anomaly: bool


ORDERED_REASONS = {
    "sustainable": "DOMAIN_NOT_SUSTAINABLE",
    "event_free_full_horizon": "EVENT_INSIDE_OR_TOO_CLOSE_TO_FULL_HORIZON",
    "close_to_load_parameterized_equilibrium": "FAR_FROM_LOAD_PARAMETERIZED_EQUILIBRIUM",
    "valve_not_at_bound": "SG_VALVE_BOUNDARY",
    "mechanical_not_at_bound": "SG_MECHANICAL_BOUNDARY",
    "grc_inactive": "GRC_ACTIVE",
    "bess_power_limit_inactive": "BESS_POWER_LIMIT_ACTIVE",
    "bess_ramp_limit_inactive": "BESS_RAMP_LIMIT_ACTIVE",
    "bess_energy_limit_inactive": "BESS_ENERGY_LIMIT_ACTIVE",
    "command_unsaturated": "COMMAND_SATURATION",
    "observer_warmed": "OBSERVER_NOT_WARMED",
    "no_solver_or_fallback_anomaly": "SOLVER_OR_FALLBACK_ANOMALY",
}


def classify_terminal_window(
    flags: TerminalWindowFlags,
) -> tuple[bool, str, tuple[str, ...]]:
    reasons = tuple(
        ORDERED_REASONS[item.name]
        for item in fields(flags)
        if not bool(getattr(flags, item.name))
    )
    if not reasons:
        return True, "INCLUDED", ()
    return False, reasons[0], reasons
