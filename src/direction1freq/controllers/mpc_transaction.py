"""Transactional MPC contracts and solver-outcome taxonomy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class SolverOutcome(StrEnum):
    OPTIMAL = "optimal"
    OPTIMAL_INACCURATE_ACCEPTED = "optimal_inaccurate_accepted"
    PRIMAL_INFEASIBLE = "primal_infeasible"
    DUAL_INFEASIBLE = "dual_infeasible"
    MAX_ITER = "max_iter"
    RESIDUAL_REJECT = "residual_reject"
    NUMERICAL_FAILURE = "numerical_failure"
    NOT_RUN = "not_run"


@dataclass(frozen=True, slots=True)
class SolverAttempt:
    solver: str
    raw_status: str
    outcome: SolverOutcome
    accepted: bool
    objective: float
    primal_residual: float
    dual_residual: float
    iterations: int
    error: str = ""

    @property
    def mathematical_infeasible(self) -> bool:
        return self.outcome in {
            SolverOutcome.PRIMAL_INFEASIBLE,
            SolverOutcome.DUAL_INFEASIBLE,
        }

    @property
    def numerical_failure(self) -> bool:
        return self.outcome in {
            SolverOutcome.MAX_ITER,
            SolverOutcome.RESIDUAL_REJECT,
            SolverOutcome.NUMERICAL_FAILURE,
        }


def classify_solver_attempt(
    raw_status: str,
    primal_residual: float,
    dual_residual: float,
    accepted_residual: float,
) -> tuple[SolverOutcome, bool]:
    """Classify CVXPY/native statuses without merging failure categories."""

    status = raw_status.lower().strip()
    residual_ok = bool(
        np.isfinite(primal_residual)
        and primal_residual <= accepted_residual
        and (not np.isfinite(dual_residual) or dual_residual <= accepted_residual)
    )
    if status == "optimal":
        return (
            (SolverOutcome.OPTIMAL, True)
            if residual_ok
            else (SolverOutcome.RESIDUAL_REJECT, False)
        )
    if status == "optimal_inaccurate":
        return (
            (SolverOutcome.OPTIMAL_INACCURATE_ACCEPTED, True)
            if residual_ok
            else (SolverOutcome.RESIDUAL_REJECT, False)
        )
    if "infeasible" in status and "unbounded" not in status:
        return SolverOutcome.PRIMAL_INFEASIBLE, False
    if "unbounded" in status or "dual_infeasible" in status:
        return SolverOutcome.DUAL_INFEASIBLE, False
    if "user_limit" in status or "max_iter" in status:
        return SolverOutcome.MAX_ITER, False
    return SolverOutcome.NUMERICAL_FAILURE, False


def assert_applied_action(action: np.ndarray, dimension: int) -> np.ndarray:
    vector = np.asarray(action, dtype=float).reshape(-1)
    if vector.shape != (dimension,):
        raise ValueError(f"applied action must have shape ({dimension},)")
    if not np.all(np.isfinite(vector)):
        raise ValueError("applied action must be finite")
    return vector.copy()

