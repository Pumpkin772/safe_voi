"""Lexicographic performance-only feasibility restoration.

Physical input and slew constraints are immutable.  Stage one minimizes the
performance-envelope L1 slack; stage two fixes that optimum (within tolerance)
and minimizes deviation from the requested action.
"""

from __future__ import annotations

from dataclasses import dataclass

import cvxpy as cp
import numpy as np


@dataclass(frozen=True, slots=True)
class RestorationResult:
    action: np.ndarray
    succeeded: bool
    stage1_status: str
    stage2_status: str
    minimum_performance_slack_l1: float
    hard_constraint_residual: float
    physical_constraints_softened: bool = False


def restore_action_lexicographically(
    reference_action: np.ndarray,
    previous_applied_action: np.ndarray,
    input_lower: np.ndarray,
    input_upper: np.ndarray,
    command_slew: np.ndarray,
    performance_matrix: np.ndarray,
    performance_target: np.ndarray,
    performance_limit: np.ndarray,
    *,
    tolerance: float = 1e-8,
) -> RestorationResult:
    """Solve a compact transaction-level restoration used by F2 diagnostics."""

    reference = np.asarray(reference_action, dtype=float)
    previous = np.asarray(previous_applied_action, dtype=float)
    lower = np.asarray(input_lower, dtype=float)
    upper = np.asarray(input_upper, dtype=float)
    slew = np.asarray(command_slew, dtype=float)
    matrix = np.asarray(performance_matrix, dtype=float)
    target = np.asarray(performance_target, dtype=float)
    limit = np.asarray(performance_limit, dtype=float)
    dimension = len(reference)
    action = cp.Variable(dimension)
    slack = cp.Variable(len(target), nonneg=True)
    hard = [
        action >= lower,
        action <= upper,
        cp.abs(action - previous) <= slew,
    ]
    performance = [cp.abs(matrix @ action - target) <= limit + slack]
    stage1 = cp.Problem(cp.Minimize(cp.sum(slack)), hard + performance)
    try:
        minimum = stage1.solve(
            solver=cp.CLARABEL,
            tol_gap_abs=tolerance,
            tol_gap_rel=tolerance,
            tol_feas=tolerance,
            verbose=False,
        )
        stage1_status = str(stage1.status)
    except Exception as error:
        minimum = float("nan")
        stage1_status = f"exception:{type(error).__name__}"
    if stage1_status not in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE}:
        return RestorationResult(
            np.zeros(dimension),
            False,
            stage1_status,
            "not_run",
            float("inf"),
            float("inf"),
        )
    minimum_value = max(float(minimum), 0.0)
    stage2 = cp.Problem(
        cp.Minimize(cp.sum_squares(action - reference)),
        hard + performance + [cp.sum(slack) <= minimum_value + 10.0 * tolerance],
    )
    try:
        stage2.solve(
            solver=cp.CLARABEL,
            tol_gap_abs=tolerance,
            tol_gap_rel=tolerance,
            tol_feas=tolerance,
            verbose=False,
        )
        stage2_status = str(stage2.status)
    except Exception as error:
        stage2_status = f"exception:{type(error).__name__}"
    succeeded = bool(
        stage2_status in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE}
        and action.value is not None
    )
    result = np.asarray(action.value).ravel() if succeeded else np.zeros(dimension)
    hard_residual = max(
        float(np.max(lower - result)),
        float(np.max(result - upper)),
        float(np.max(np.abs(result - previous) - slew)),
        0.0,
    )
    return RestorationResult(
        result.copy(),
        bool(succeeded and hard_residual <= 100.0 * tolerance),
        stage1_status,
        stage2_status,
        minimum_value,
        hard_residual,
    )

