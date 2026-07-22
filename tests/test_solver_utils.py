from __future__ import annotations

from types import SimpleNamespace
import time

import cvxpy as cp
import numpy as np
import pytest

import d5freq.optimization.solver_utils as solver_utils
from d5freq.optimization.solver_utils import (
    SolverOutcome,
    shift_warm_start_sequence,
    solve_cvxpy_problem,
)


def _scalar_problem() -> tuple[cp.Problem, cp.Variable]:
    variable = cp.Variable(name="u")
    problem = cp.Problem(cp.Minimize(cp.square(variable - 2.0)))
    return problem, variable


def _fake_stats(*, solve_time: float = 0.002, iterations: int = 7) -> SimpleNamespace:
    return SimpleNamespace(
        solver_name="FAKE",
        solve_time=solve_time,
        setup_time=0.001,
        num_iters=iterations,
    )


def _set_fake_solution(
    problem: cp.Problem,
    variable: cp.Variable,
    *,
    status: str,
    value: float | None,
    objective: float | None,
) -> None:
    problem._status = status
    problem._value = objective
    problem._solver_stats = _fake_stats()
    variable.value = value


def test_shift_warm_start_sequence_left_shifts_and_repeats_terminal() -> None:
    sequence = np.array([[1.0, 2.0, 3.0], [-1.0, -2.0, -3.0]])

    shifted = shift_warm_start_sequence(sequence)

    np.testing.assert_array_equal(
        shifted,
        np.array([[2.0, 3.0, 3.0], [-2.0, -3.0, -3.0]]),
    )
    sequence[:] = 99.0
    assert shifted[0, 0] == 2.0


def test_shift_warm_start_sequence_validates_shared_input_shape_and_finiteness() -> None:
    np.testing.assert_array_equal(
        shift_warm_start_sequence(np.array([[1.0], [-1.0]])),
        np.array([[1.0], [-1.0]]),
    )
    for invalid in (
        np.zeros((3, 2)),
        np.zeros((2, 0)),
        np.zeros(2),
        np.array([[0.0, np.nan], [0.0, 0.0]]),
    ):
        with pytest.raises(ValueError):
            shift_warm_start_sequence(invalid)


def test_real_convex_problem_records_availability_stats_and_total_wall_time() -> None:
    problem, variable = _scalar_problem()

    result = solve_cvxpy_problem(
        problem,
        solution_variables={"u": variable, "twice_u": lambda: 2.0 * variable.value},
        solver_priority=("NOT_INSTALLED", "CLARABEL"),
        installed_solvers=("CLARABEL",),
    )

    assert result.success
    assert result.status == cp.OPTIMAL
    assert result.solver == "CLARABEL"
    assert result.total_wall_time_s >= 0.0
    assert result.solver_solve_time_s is not None
    assert result.iterations is not None
    assert [attempt.outcome for attempt in result.attempts] == [
        SolverOutcome.UNAVAILABLE,
        SolverOutcome.SUCCESS,
    ]
    assert result.value("u") == pytest.approx(2.0, abs=1.0e-7)
    assert result.value("twice_u") == pytest.approx(4.0, abs=2.0e-7)
    log = result.to_log_dict()
    assert log["success"] is True
    assert len(log["attempts"]) == 2


def test_optimal_inaccurate_is_failure_and_falls_through_to_next_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem, variable = _scalar_problem()
    calls: list[str] = []

    def fake_solve(*, solver: str, **_: object) -> float:
        calls.append(solver)
        if solver == "FIRST":
            _set_fake_solution(
                problem,
                variable,
                status=cp.OPTIMAL_INACCURATE,
                value=91.0,
                objective=4.0,
            )
            return 4.0
        assert variable.value is None
        _set_fake_solution(
            problem,
            variable,
            status=cp.OPTIMAL,
            value=2.0,
            objective=0.0,
        )
        return 0.0

    monkeypatch.setattr(problem, "solve", fake_solve)
    result = solve_cvxpy_problem(
        problem,
        solution_variables={"u": variable},
        solver_priority=("FIRST", "SECOND"),
        installed_solvers=("FIRST", "SECOND"),
        warm_start=False,
    )

    assert calls == ["FIRST", "SECOND"]
    assert result.success
    assert result.value("u") == pytest.approx(2.0)
    assert [attempt.outcome for attempt in result.attempts] == [
        SolverOutcome.INACCURATE,
        SolverOutcome.SUCCESS,
    ]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (cp.OPTIMAL_INACCURATE, SolverOutcome.INACCURATE),
        (cp.INFEASIBLE, SolverOutcome.INFEASIBLE),
        (cp.INFEASIBLE_INACCURATE, SolverOutcome.INFEASIBLE),
        (cp.UNBOUNDED, SolverOutcome.UNBOUNDED),
        (cp.USER_LIMIT, SolverOutcome.TIMEOUT),
    ],
)
def test_nonoptimal_statuses_never_return_warm_or_solver_values(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected: SolverOutcome,
) -> None:
    problem, variable = _scalar_problem()
    warm_value = np.asarray(17.0)

    def fake_solve(**_: object) -> float:
        assert variable.value == pytest.approx(17.0)
        _set_fake_solution(
            problem,
            variable,
            status=status,
            value=123.0,
            objective=1.0,
        )
        return 1.0

    monkeypatch.setattr(problem, "solve", fake_solve)
    result = solve_cvxpy_problem(
        problem,
        solution_variables={"u": variable},
        solver_priority=("FAKE",),
        installed_solvers=("FAKE",),
        warm_start_values={variable: warm_value},
    )

    assert not result.success
    assert result.outcome is expected
    assert dict(result.values) == {}
    assert variable.value is None
    with pytest.raises(RuntimeError, match="no executable"):
        result.value("u")


def test_solver_exception_is_classified_and_clears_stale_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem, variable = _scalar_problem()
    variable.value = 55.0

    def fake_solve(**_: object) -> float:
        raise RuntimeError("license unavailable")

    monkeypatch.setattr(problem, "solve", fake_solve)
    result = solve_cvxpy_problem(
        problem,
        solution_variables={"u": variable},
        solver_priority=("FAKE",),
        installed_solvers=("FAKE",),
    )

    assert result.outcome is SolverOutcome.ERROR
    assert result.status == "solver_error"
    assert result.error_type == "RuntimeError"
    assert "license unavailable" in (result.error_message or "")
    assert variable.value is None
    assert not result.values


@pytest.mark.parametrize("bad_location", ["objective", "return", "solution"])
def test_exact_optimal_with_any_nan_is_nonfinite_failure(
    monkeypatch: pytest.MonkeyPatch,
    bad_location: str,
) -> None:
    problem, variable = _scalar_problem()

    def fake_solve(**_: object) -> float:
        objective = np.nan if bad_location == "objective" else 0.0
        _set_fake_solution(
            problem,
            variable,
            status=cp.OPTIMAL,
            value=2.0,
            objective=objective,
        )
        return np.nan if bad_location == "return" else objective

    monkeypatch.setattr(problem, "solve", fake_solve)
    result = solve_cvxpy_problem(
        problem,
        solution_variables={
            "u": (lambda: np.nan) if bad_location == "solution" else variable
        },
        solver_priority=("FAKE",),
        installed_solvers=("FAKE",),
    )

    assert result.outcome is SolverOutcome.NONFINITE
    assert result.status == "nonfinite_solution"
    assert not result.values
    assert variable.value is None


def test_timeout_is_total_wall_budget_and_rejects_late_optimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem, variable = _scalar_problem()
    received_options: dict[str, object] = {}

    def slow_solve(**kwargs: object) -> float:
        received_options.update(kwargs)
        time.sleep(0.01)
        _set_fake_solution(
            problem,
            variable,
            status=cp.OPTIMAL,
            value=2.0,
            objective=0.0,
        )
        return 0.0

    monkeypatch.setattr(problem, "solve", slow_solve)
    result = solve_cvxpy_problem(
        problem,
        solution_variables={"u": variable},
        solver_priority=("CLARABEL", "SECOND"),
        installed_solvers=("CLARABEL", "SECOND"),
        timeout_s=0.001,
    )

    assert result.outcome is SolverOutcome.TIMEOUT
    assert result.timed_out
    assert result.status == "timeout"
    assert result.total_wall_time_s >= 0.001
    assert len(result.attempts) == 1
    assert received_options["time_limit"] <= 0.001
    assert variable.value is None
    assert not result.values


def test_timeout_budget_includes_pre_solver_orchestration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem, variable = _scalar_problem()
    variable.value = 17.0
    original_collect = solver_utils._collect_warm_start_values
    solve_called = False

    def slow_collect(*args: object, **kwargs: object) -> dict[int, np.ndarray]:
        time.sleep(0.01)
        return original_collect(*args, **kwargs)  # type: ignore[arg-type]

    def forbidden_solve(**_: object) -> float:
        nonlocal solve_called
        solve_called = True
        raise AssertionError("backend must not start after orchestration exhausts budget")

    monkeypatch.setattr(solver_utils, "_collect_warm_start_values", slow_collect)
    monkeypatch.setattr(problem, "solve", forbidden_solve)
    result = solve_cvxpy_problem(
        problem,
        solution_variables={"u": variable},
        solver_priority=("FAKE",),
        installed_solvers=("FAKE",),
        timeout_s=0.001,
    )

    assert not solve_called
    assert result.outcome is SolverOutcome.TIMEOUT
    assert result.total_wall_time_s >= 0.01
    assert len(result.attempts) == 1
    assert result.attempts[0].wall_time_s == 0.0
    assert variable.value is None
    assert not result.values


def test_no_available_solver_is_auditable_failure() -> None:
    problem, variable = _scalar_problem()

    result = solve_cvxpy_problem(
        problem,
        solution_variables={"u": variable},
        solver_priority=("A", "B"),
        installed_solvers=(),
    )

    assert result.outcome is SolverOutcome.UNAVAILABLE
    assert result.status == "no_solver_available"
    assert result.solver is None
    assert [attempt.solver for attempt in result.attempts] == ["A", "B"]
    assert all(not attempt.available for attempt in result.attempts)


def test_user_options_are_not_mutated_and_timeout_uses_tighter_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem, variable = _scalar_problem()
    original = {"GUROBI": {"TimeLimit": 99.0, "Threads": 1}}
    received: dict[str, object] = {}

    def fake_solve(**kwargs: object) -> float:
        received.update(kwargs)
        _set_fake_solution(
            problem,
            variable,
            status=cp.INFEASIBLE,
            value=None,
            objective=float("inf"),
        )
        return float("inf")

    monkeypatch.setattr(problem, "solve", fake_solve)
    result = solve_cvxpy_problem(
        problem,
        solution_variables={"u": variable},
        solver_priority=("GUROBI",),
        solver_options=original,
        timeout_s=2.0,
        installed_solvers=("GUROBI",),
    )

    assert result.outcome is SolverOutcome.INFEASIBLE
    assert received["Threads"] == 1
    assert 0.0 < float(received["TimeLimit"]) <= 2.0
    assert original == {"GUROBI": {"TimeLimit": 99.0, "Threads": 1}}


def test_invalid_warm_start_is_rejected_before_solve() -> None:
    problem, variable = _scalar_problem()
    unrelated = cp.Variable(2, name="unrelated")

    with pytest.raises(ValueError, match="owned by problem"):
        solve_cvxpy_problem(
            problem,
            solution_variables={"u": variable},
            solver_priority=("CLARABEL",),
            warm_start_values={unrelated: np.zeros(2)},
        )
    with pytest.raises(ValueError, match="finite"):
        solve_cvxpy_problem(
            problem,
            solution_variables={"u": variable},
            solver_priority=("CLARABEL",),
            warm_start_values={variable: np.asarray(np.nan)},
        )


def test_duplicate_priority_and_nonpositive_timeout_are_rejected() -> None:
    problem, variable = _scalar_problem()
    with pytest.raises(ValueError, match="duplicate"):
        solve_cvxpy_problem(
            problem,
            solution_variables={"u": variable},
            solver_priority=("SCS", "scs"),
        )
    with pytest.raises(ValueError, match="positive"):
        solve_cvxpy_problem(
            problem,
            solution_variables={"u": variable},
            timeout_s=0.0,
        )
