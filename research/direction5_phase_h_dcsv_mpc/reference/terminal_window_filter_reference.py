"""Reference semantics for physically valid sustainable terminal windows."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class TerminalWindowFlags:
    sustainable: bool
    observer_warm: bool
    event_free_full_horizon: bool
    close_to_load_parameterized_equilibrium: bool
    valve_not_at_bound: bool
    mechanical_not_at_bound: bool
    grc_inactive: bool
    bess_power_limit_inactive: bool
    bess_ramp_limit_inactive: bool
    bess_energy_limit_inactive: bool
    command_unsaturated: bool
    no_solver_or_fallback_anomaly: bool


def include_terminal_window(flags: TerminalWindowFlags) -> tuple[bool, list[str]]:
    reasons = [
        name
        for name, value in vars(flags).items()
        if not bool(value)
    ]
    return len(reasons) == 0, reasons
