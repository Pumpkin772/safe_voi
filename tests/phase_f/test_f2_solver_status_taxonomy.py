from __future__ import annotations

import numpy as np

from direction1freq.controllers.mpc_transaction import (
    SolverOutcome,
    classify_solver_attempt,
)


def test_mathematical_infeasibility_and_numerical_failure_are_distinct() -> None:
    assert classify_solver_attempt("infeasible", np.inf, np.inf, 1e-5) == (
        SolverOutcome.PRIMAL_INFEASIBLE,
        False,
    )
    assert classify_solver_attempt("unbounded", np.inf, np.inf, 1e-5) == (
        SolverOutcome.DUAL_INFEASIBLE,
        False,
    )
    assert classify_solver_attempt("user_limit", 1e-2, 1e-2, 1e-5) == (
        SolverOutcome.MAX_ITER,
        False,
    )


def test_inaccurate_solution_requires_explicit_residual_acceptance() -> None:
    assert classify_solver_attempt("optimal_inaccurate", 1e-6, 2e-6, 1e-5) == (
        SolverOutcome.OPTIMAL_INACCURATE_ACCEPTED,
        True,
    )
    assert classify_solver_attempt("optimal_inaccurate", 1e-3, 2e-6, 1e-5) == (
        SolverOutcome.RESIDUAL_REJECT,
        False,
    )


def test_nominal_mpc_diagnostics_expose_required_taxonomy_fields() -> None:
    from direction1freq.controllers.nominal_mpc import MPCDiagnostics

    fields = set(MPCDiagnostics.__dataclass_fields__)
    required = {
        "primary_status",
        "secondary_status",
        "primary_primal_residual",
        "primary_dual_residual",
        "secondary_primal_residual",
        "secondary_dual_residual",
        "mathematical_infeasible",
        "numerical_failure",
        "terminal_reject",
        "restoration_used",
        "backup_used",
        "previous_applied_action",
        "previous_model_action",
        "history_match",
        "consecutive_backup_count",
    }
    assert required <= fields

