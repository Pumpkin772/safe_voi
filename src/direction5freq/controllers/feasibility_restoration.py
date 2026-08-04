"""Lexicographic restoration records for DCSV-MPC."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RestorationPolicy:
    frequency_terminal_slack_penalty: float = 1.0e6
    ace_terminal_slack_penalty: float = 5.0e5
    allow_device_constraint_relaxation: bool = False
    allow_energy_constraint_relaxation: bool = False
    allow_delay_causality_relaxation: bool = False


@dataclass(frozen=True, slots=True)
class SolverDiagnostics:
    status: str
    objective: float
    solve_time_s: float
    iterations: int
    maximum_constraint_residual: float
    vertex_count: int
    hard_margin_pu: float
    energy_margin_mwh: float
    restoration_used: bool
    fallback_used: bool
    mathematical_infeasibility: bool
    numerical_failure: bool
