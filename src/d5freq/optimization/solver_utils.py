"""Strict, auditable CVXPY solver orchestration for online MPC.

Only an exact CVXPY ``optimal`` status with a finite objective and finite
requested solution values is executable.  In particular,
``optimal_inaccurate`` is deliberately a failure for the proposed controller.
This module also clears CVXPY variable values after every unsuccessful solve so
that a warm start can never be mistaken for a newly executable action.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import importlib
import math
from time import perf_counter
from types import MappingProxyType
from typing import TypeAlias

import cvxpy as cp
import numpy as np
from numpy.typing import ArrayLike, NDArray


FloatArray = NDArray[np.float64]
SolutionValue: TypeAlias = float | FloatArray
SolutionSource: TypeAlias = cp.Expression | Callable[[], ArrayLike | float]
DEFAULT_SOLVER_PRIORITY = ("MOSEK", "GUROBI", "CLARABEL", "SCS")


class SolverOutcome(str, Enum):
    """Controller-facing classification of a solver attempt or solve call."""

    SUCCESS = "success"
    INACCURATE = "inaccurate"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"
    TIMEOUT = "timeout"
    NONFINITE = "nonfinite"
    ERROR = "error"
    FAILED_STATUS = "failed_status"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SolverAttempt:
    """One solver-priority entry, including skipped unavailable solvers."""

    solver: str
    solver_version: str | None
    available: bool
    status: str | None
    outcome: SolverOutcome
    wall_time_s: float
    solver_solve_time_s: float | None = None
    solver_setup_time_s: float | None = None
    iterations: int | None = None
    objective: float | None = None
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.solver:
            raise ValueError("solver must not be empty")
        for name in ("wall_time_s", "solver_solve_time_s", "solver_setup_time_s"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value < 0.0):
                raise ValueError(f"{name} must be finite and non-negative")
        if self.iterations is not None and self.iterations < 0:
            raise ValueError("iterations must be non-negative")
        if self.objective is not None and not math.isfinite(self.objective):
            raise ValueError("objective must be finite when recorded")

    @property
    def success(self) -> bool:
        """Whether this attempt produced an exactly optimal finite solution."""

        return self.outcome is SolverOutcome.SUCCESS and self.status == cp.OPTIMAL

    def to_log_dict(self) -> dict[str, object]:
        """Return a JSON-compatible record for per-step solver logs."""

        return {
            "solver": self.solver,
            "solver_version": self.solver_version,
            "available": self.available,
            "status": self.status,
            "outcome": self.outcome.value,
            "wall_time_s": self.wall_time_s,
            "solver_solve_time_s": self.solver_solve_time_s,
            "solver_setup_time_s": self.solver_setup_time_s,
            "iterations": self.iterations,
            "objective": self.objective,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass(frozen=True, slots=True)
class SolverResult:
    """Strict solve result; failed results contain no solution values."""

    status: str
    outcome: SolverOutcome
    solver: str | None
    solver_version: str | None
    total_wall_time_s: float
    objective: float | None
    values: Mapping[str, SolutionValue]
    attempts: tuple[SolverAttempt, ...]
    solver_solve_time_s: float | None = None
    solver_setup_time_s: float | None = None
    iterations: int | None = None
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.status:
            raise ValueError("status must not be empty")
        if not math.isfinite(self.total_wall_time_s) or self.total_wall_time_s < 0.0:
            raise ValueError("total_wall_time_s must be finite and non-negative")
        if self.objective is not None and not math.isfinite(self.objective):
            raise ValueError("objective must be finite when recorded")
        copied: dict[str, SolutionValue] = {}
        for name, value in self.values.items():
            copied[name] = _copy_solution_value(value)
        if self.outcome is not SolverOutcome.SUCCESS and copied:
            raise ValueError("failed solver results must not contain solution values")
        if self.outcome is SolverOutcome.SUCCESS:
            if self.status != cp.OPTIMAL or self.solver is None or self.objective is None:
                raise ValueError("successful solver result must be exactly optimal")
        object.__setattr__(self, "values", MappingProxyType(copied))

    @property
    def success(self) -> bool:
        """Whether the result contains a newly solved executable solution."""

        return self.outcome is SolverOutcome.SUCCESS and self.status == cp.OPTIMAL

    @property
    def timed_out(self) -> bool:
        return self.outcome is SolverOutcome.TIMEOUT

    def value(self, name: str) -> SolutionValue:
        """Return an owned solution copy, refusing access after every failure."""

        if not self.success:
            raise RuntimeError("solver result has no executable solution")
        if name not in self.values:
            raise KeyError(name)
        return _copy_solution_value(self.values[name])

    def to_log_dict(self) -> dict[str, object]:
        """Return scalar metadata suitable for JSON/Parquet logging."""

        return {
            "status": self.status,
            "outcome": self.outcome.value,
            "success": self.success,
            "solver": self.solver,
            "solver_version": self.solver_version,
            "total_wall_time_s": self.total_wall_time_s,
            "objective": self.objective,
            "solver_solve_time_s": self.solver_solve_time_s,
            "solver_setup_time_s": self.solver_setup_time_s,
            "iterations": self.iterations,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "value_shapes": {
                name: list(value.shape) if isinstance(value, np.ndarray) else []
                for name, value in self.values.items()
            },
            "attempts": [attempt.to_log_dict() for attempt in self.attempts],
        }


def shift_warm_start_sequence(control_sequence: ArrayLike) -> FloatArray:
    """Left-shift a finite shared ``(2, horizon)`` SG/IBR input sequence.

    The terminal action is repeated, i.e.
    ``[U[:, 1], ..., U[:, -1], U[:, -1]]``.  The returned array owns its
    storage, so later modification of the solved sequence cannot alter it.
    """

    controls = np.asarray(control_sequence, dtype=float)
    if controls.ndim != 2 or controls.shape[0] != 2 or controls.shape[1] < 1:
        raise ValueError("control_sequence must have shape (2, horizon) with horizon >= 1")
    if not np.all(np.isfinite(controls)):
        raise ValueError("control_sequence must contain only finite values")
    if controls.shape[1] == 1:
        return controls.copy()
    return np.concatenate((controls[:, 1:], controls[:, -1:]), axis=1)


def solve_cvxpy_problem(
    problem: cp.Problem,
    *,
    solution_variables: Mapping[str, SolutionSource],
    solver_priority: Sequence[str] = DEFAULT_SOLVER_PRIORITY,
    solver_options: Mapping[str, Mapping[str, object]] | None = None,
    timeout_s: float | None = None,
    warm_start: bool = True,
    warm_start_values: Mapping[cp.Variable, ArrayLike] | None = None,
    verbose: bool = False,
    installed_solvers: Sequence[str] | None = None,
) -> SolverResult:
    """Solve a CVXPY problem using an auditable strict solver policy.

    Solvers are attempted in priority order.  Unavailable solvers are logged
    and skipped.  Only exact ``optimal`` is accepted; inaccurate, infeasible,
    unbounded, solver-error, timeout, missing, and non-finite solutions remain
    explicit failures and may fall through to the next available solver while
    budget remains.  ``timeout_s`` is one cooperative wall-time budget for the
    complete call, not a fresh budget for every solver.  The adapter passes the
    remaining budget through each supported solver's native time-limit option
    and rejects/clears even an exact optimum returned after the deadline.  It
    does not preempt a solver process: a backend that ignores its native limit
    can therefore return late, after which its solution is still rejected.

    ``solution_variables`` may map names either to CVXPY expressions or to
    zero-argument extractors.  On failure, the returned mapping is empty and
    every variable owned by ``problem`` has value ``None``.  This is the key
    safety boundary preventing an old warm start from becoming an action.
    """

    total_start = perf_counter()
    if not isinstance(problem, cp.Problem):
        raise TypeError("problem must be a cvxpy.Problem")
    normalized_priority = _normalize_priority(solver_priority)
    normalized_sources = _normalize_solution_sources(solution_variables)
    normalized_options = _normalize_solver_options(solver_options)
    timeout = _normalize_timeout(timeout_s)
    installed = {
        str(name).strip().upper()
        for name in (cp.installed_solvers() if installed_solvers is None else installed_solvers)
    }
    warm_values = _collect_warm_start_values(
        problem,
        explicit=warm_start_values,
        enabled=bool(warm_start),
    )
    attempts: list[SolverAttempt] = []
    final_attempt: SolverAttempt | None = None

    for solver in normalized_priority:
        version = solver_version(solver) if solver in installed else None
        if solver not in installed:
            attempt = SolverAttempt(
                solver=solver,
                solver_version=None,
                available=False,
                status=None,
                outcome=SolverOutcome.UNAVAILABLE,
                wall_time_s=0.0,
                error_type="SolverNotInstalled",
                error_message=f"{solver} is not installed",
            )
            attempts.append(attempt)
            continue

        elapsed = perf_counter() - total_start
        remaining = None if timeout is None else timeout - elapsed
        if remaining is not None and remaining <= 0.0:
            attempt = SolverAttempt(
                solver=solver,
                solver_version=version,
                available=True,
                status="timeout",
                outcome=SolverOutcome.TIMEOUT,
                wall_time_s=0.0,
                error_type="TimeoutError",
                error_message="total solver wall-time budget exhausted before attempt",
            )
            attempts.append(attempt)
            final_attempt = attempt
            break

        _clear_problem_values(problem)
        _restore_warm_start_values(problem, warm_values)
        options = dict(normalized_options.get(solver, {}))
        if remaining is not None:
            options = _apply_solver_timeout(solver, options, remaining)
        attempt_start = perf_counter()
        solve_return: object = None
        try:
            solve_return = problem.solve(
                solver=solver,
                warm_start=bool(warm_start),
                verbose=bool(verbose),
                **options,
            )
        except Exception as exc:  # Solver failures are first-class audit data.
            attempt = SolverAttempt(
                solver=solver,
                solver_version=version,
                available=True,
                status=None,
                outcome=SolverOutcome.ERROR,
                wall_time_s=perf_counter() - attempt_start,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            attempts.append(attempt)
            final_attempt = attempt
            _clear_problem_values(problem)
            if timeout is not None and perf_counter() - total_start >= timeout:
                final_attempt = _replace_as_timeout(attempt)
                attempts[-1] = final_attempt
                break
            continue

        attempt_wall = perf_counter() - attempt_start
        status = None if problem.status is None else str(problem.status).lower()
        stats = _read_solver_stats(problem)
        if timeout is not None and perf_counter() - total_start >= timeout:
            attempt = SolverAttempt(
                solver=solver,
                solver_version=version,
                available=True,
                status=status,
                outcome=SolverOutcome.TIMEOUT,
                wall_time_s=attempt_wall,
                solver_solve_time_s=stats[0],
                solver_setup_time_s=stats[1],
                iterations=stats[2],
                error_type="TimeoutError",
                error_message="solver exceeded the total wall-time budget",
            )
            attempts.append(attempt)
            final_attempt = attempt
            _clear_problem_values(problem)
            break

        outcome = _classify_status(status)
        if outcome is not SolverOutcome.SUCCESS:
            attempt = SolverAttempt(
                solver=solver,
                solver_version=version,
                available=True,
                status=status,
                outcome=outcome,
                wall_time_s=attempt_wall,
                solver_solve_time_s=stats[0],
                solver_setup_time_s=stats[1],
                iterations=stats[2],
            )
            attempts.append(attempt)
            final_attempt = attempt
            _clear_problem_values(problem)
            continue

        try:
            objective = _finite_objective(problem.value, solve_return)
            values = _extract_solution_values(normalized_sources)
        except Exception as exc:
            outcome = (
                SolverOutcome.NONFINITE
                if isinstance(exc, (FloatingPointError, ValueError))
                else SolverOutcome.ERROR
            )
            attempt = SolverAttempt(
                solver=solver,
                solver_version=version,
                available=True,
                status=status,
                outcome=outcome,
                wall_time_s=attempt_wall,
                solver_solve_time_s=stats[0],
                solver_setup_time_s=stats[1],
                iterations=stats[2],
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            attempts.append(attempt)
            final_attempt = attempt
            _clear_problem_values(problem)
            continue

        attempt = SolverAttempt(
            solver=solver,
            solver_version=version,
            available=True,
            status=status,
            outcome=SolverOutcome.SUCCESS,
            wall_time_s=attempt_wall,
            solver_solve_time_s=stats[0],
            solver_setup_time_s=stats[1],
            iterations=stats[2],
            objective=objective,
        )
        attempts.append(attempt)
        return SolverResult(
            status=cp.OPTIMAL,
            outcome=SolverOutcome.SUCCESS,
            solver=solver,
            solver_version=version,
            total_wall_time_s=perf_counter() - total_start,
            objective=objective,
            values=values,
            attempts=tuple(attempts),
            solver_solve_time_s=stats[0],
            solver_setup_time_s=stats[1],
            iterations=stats[2],
        )

    _clear_problem_values(problem)
    total_wall = perf_counter() - total_start
    if final_attempt is None:
        return SolverResult(
            status="no_solver_available",
            outcome=SolverOutcome.UNAVAILABLE,
            solver=None,
            solver_version=None,
            total_wall_time_s=total_wall,
            objective=None,
            values={},
            attempts=tuple(attempts),
            error_type="SolverNotInstalled",
            error_message="none of the requested solvers is installed",
        )
    status = (
        final_attempt.status
        if final_attempt.outcome
        in {
            SolverOutcome.INACCURATE,
            SolverOutcome.INFEASIBLE,
            SolverOutcome.UNBOUNDED,
        }
        and final_attempt.status is not None
        else _failure_status(final_attempt.outcome)
    )
    return SolverResult(
        status=status,
        outcome=final_attempt.outcome,
        solver=final_attempt.solver,
        solver_version=final_attempt.solver_version,
        total_wall_time_s=total_wall,
        objective=None,
        values={},
        attempts=tuple(attempts),
        solver_solve_time_s=final_attempt.solver_solve_time_s,
        solver_setup_time_s=final_attempt.solver_setup_time_s,
        iterations=final_attempt.iterations,
        error_type=final_attempt.error_type,
        error_message=final_attempt.error_message,
    )


def solver_version(solver: str) -> str | None:
    """Best-effort package/runtime version for a normalized CVXPY solver."""

    normalized = str(solver).strip().upper()
    module_names = {
        "MOSEK": ("mosek",),
        "GUROBI": ("gurobipy",),
        "CLARABEL": ("clarabel",),
        "SCS": ("scs",),
        "OSQP": ("osqp",),
        "SCIPY": ("scipy",),
        "HIGHS": ("highspy",),
    }.get(normalized, (normalized.lower(),))
    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        version = getattr(module, "__version__", None)
        if version is not None:
            return str(version)
        if normalized == "GUROBI":
            try:
                parts = module.gurobi.version()
                return ".".join(str(part) for part in parts)
            except Exception:
                pass
        if normalized == "MOSEK":
            try:
                parts = module.Env.getversion()
                return ".".join(str(part) for part in parts)
            except Exception:
                pass
    return None


def _normalize_priority(solver_priority: Sequence[str]) -> tuple[str, ...]:
    if isinstance(solver_priority, (str, bytes)):
        raise TypeError("solver_priority must be a sequence of solver names")
    normalized = tuple(str(name).strip().upper() for name in solver_priority)
    if not normalized or any(not name for name in normalized):
        raise ValueError("solver_priority must contain non-empty solver names")
    if len(set(normalized)) != len(normalized):
        raise ValueError("solver_priority must not contain duplicate solvers")
    return normalized


def _normalize_solution_sources(
    sources: Mapping[str, SolutionSource],
) -> dict[str, SolutionSource]:
    if not isinstance(sources, Mapping):
        raise TypeError("solution_variables must be a mapping")
    normalized: dict[str, SolutionSource] = {}
    for raw_name, source in sources.items():
        name = str(raw_name).strip()
        if not name:
            raise ValueError("solution variable names must not be empty")
        if not isinstance(source, cp.Expression) and not callable(source):
            raise TypeError("solution sources must be CVXPY expressions or callables")
        if name in normalized:
            raise ValueError(f"duplicate solution variable name: {name}")
        normalized[name] = source
    return normalized


def _normalize_solver_options(
    solver_options: Mapping[str, Mapping[str, object]] | None,
) -> dict[str, dict[str, object]]:
    if solver_options is None:
        return {}
    normalized: dict[str, dict[str, object]] = {}
    for raw_solver, options in solver_options.items():
        solver = str(raw_solver).strip().upper()
        if not solver:
            raise ValueError("solver option keys must not be empty")
        if not isinstance(options, Mapping):
            raise TypeError("each solver options entry must be a mapping")
        normalized[solver] = dict(options)
    return normalized


def _normalize_timeout(timeout_s: float | None) -> float | None:
    if timeout_s is None:
        return None
    timeout = float(timeout_s)
    if not math.isfinite(timeout) or timeout <= 0.0:
        raise ValueError("timeout_s must be finite and positive")
    return timeout


def _collect_warm_start_values(
    problem: cp.Problem,
    *,
    explicit: Mapping[cp.Variable, ArrayLike] | None,
    enabled: bool,
) -> dict[int, FloatArray]:
    if explicit is not None and not enabled:
        raise ValueError("warm_start_values require warm_start=True")
    variables = {variable.id: variable for variable in problem.variables()}
    collected: dict[int, FloatArray] = {}
    if enabled:
        for variable_id, variable in variables.items():
            if variable.value is None:
                continue
            value = np.asarray(variable.value, dtype=float)
            if value.shape == variable.shape and np.all(np.isfinite(value)):
                collected[variable_id] = value.copy()
    if explicit is None:
        return collected
    for variable, raw_value in explicit.items():
        if not isinstance(variable, cp.Variable) or variable.id not in variables:
            raise ValueError("each warm-start key must be a variable owned by problem")
        value = np.asarray(raw_value, dtype=float)
        if value.shape != variable.shape:
            raise ValueError(
                f"warm start for {variable.name()} must have shape {variable.shape}"
            )
        if not np.all(np.isfinite(value)):
            raise ValueError(f"warm start for {variable.name()} must be finite")
        collected[variable.id] = value.copy()
    return collected


def _clear_problem_values(problem: cp.Problem) -> None:
    for variable in problem.variables():
        variable.value = None


def _restore_warm_start_values(
    problem: cp.Problem,
    values: Mapping[int, FloatArray],
) -> None:
    for variable in problem.variables():
        if variable.id in values:
            variable.value = values[variable.id].copy()


def _apply_solver_timeout(
    solver: str,
    options: dict[str, object],
    remaining_s: float,
) -> dict[str, object]:
    bounded = max(float(remaining_s), np.finfo(float).eps)
    if solver == "MOSEK":
        params = dict(options.get("mosek_params", {}))
        existing = params.get("MSK_DPAR_OPTIMIZER_MAX_TIME")
        params["MSK_DPAR_OPTIMIZER_MAX_TIME"] = _minimum_limit(existing, bounded)
        options["mosek_params"] = params
    elif solver == "GUROBI":
        options["TimeLimit"] = _minimum_limit(options.get("TimeLimit"), bounded)
    elif solver == "CLARABEL":
        options["time_limit"] = _minimum_limit(options.get("time_limit"), bounded)
    elif solver == "SCS":
        options["time_limit_secs"] = _minimum_limit(
            options.get("time_limit_secs"), bounded
        )
    elif solver == "OSQP":
        options["time_limit"] = _minimum_limit(options.get("time_limit"), bounded)
    return options


def _minimum_limit(existing: object, bounded: float) -> float:
    if existing is None:
        return bounded
    try:
        value = float(existing)
    except (TypeError, ValueError):
        return bounded
    if not math.isfinite(value) or value <= 0.0:
        return bounded
    return min(value, bounded)


def _read_solver_stats(
    problem: cp.Problem,
) -> tuple[float | None, float | None, int | None]:
    stats = problem.solver_stats
    if stats is None:
        return None, None, None
    solve_time = _nonnegative_finite_or_none(getattr(stats, "solve_time", None))
    setup_time = _nonnegative_finite_or_none(getattr(stats, "setup_time", None))
    raw_iterations = getattr(stats, "num_iters", None)
    iterations: int | None = None
    if raw_iterations is not None:
        try:
            candidate = int(raw_iterations)
            if candidate >= 0:
                iterations = candidate
        except (TypeError, ValueError, OverflowError):
            pass
    return solve_time, setup_time, iterations


def _nonnegative_finite_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        candidate = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return candidate if math.isfinite(candidate) and candidate >= 0.0 else None


def _classify_status(status: str | None) -> SolverOutcome:
    if status == cp.OPTIMAL:
        return SolverOutcome.SUCCESS
    if status == cp.OPTIMAL_INACCURATE:
        return SolverOutcome.INACCURATE
    if status in {cp.INFEASIBLE, cp.INFEASIBLE_INACCURATE}:
        return SolverOutcome.INFEASIBLE
    if status in {cp.UNBOUNDED, cp.UNBOUNDED_INACCURATE}:
        return SolverOutcome.UNBOUNDED
    if status == cp.USER_LIMIT:
        return SolverOutcome.TIMEOUT
    return SolverOutcome.FAILED_STATUS


def _finite_objective(problem_value: object, solve_return: object) -> float:
    if problem_value is None:
        raise ValueError("optimal problem has no objective value")
    objective = float(problem_value)
    if not math.isfinite(objective):
        raise FloatingPointError("objective is not finite")
    if solve_return is not None:
        returned = float(solve_return)
        if not math.isfinite(returned):
            raise FloatingPointError("solver returned a non-finite objective")
    return objective


def _extract_solution_values(
    sources: Mapping[str, SolutionSource],
) -> dict[str, SolutionValue]:
    values: dict[str, SolutionValue] = {}
    for name, source in sources.items():
        raw_value = source() if callable(source) else source.value
        if raw_value is None:
            raise ValueError(f"solution value {name!r} is missing")
        array = np.asarray(raw_value, dtype=float)
        if not np.all(np.isfinite(array)):
            raise FloatingPointError(f"solution value {name!r} is non-finite")
        if array.ndim == 0:
            values[name] = float(array)
        else:
            copied = array.copy()
            copied.setflags(write=False)
            values[name] = copied
    return values


def _copy_solution_value(value: SolutionValue) -> SolutionValue:
    if isinstance(value, np.ndarray):
        copied = np.asarray(value, dtype=float).copy()
        copied.setflags(write=False)
        return copied
    scalar = float(value)
    if not math.isfinite(scalar):
        raise ValueError("solution scalar must be finite")
    return scalar


def _replace_as_timeout(attempt: SolverAttempt) -> SolverAttempt:
    return SolverAttempt(
        solver=attempt.solver,
        solver_version=attempt.solver_version,
        available=attempt.available,
        status=attempt.status,
        outcome=SolverOutcome.TIMEOUT,
        wall_time_s=attempt.wall_time_s,
        solver_solve_time_s=attempt.solver_solve_time_s,
        solver_setup_time_s=attempt.solver_setup_time_s,
        iterations=attempt.iterations,
        error_type="TimeoutError",
        error_message="solver exhausted the total wall-time budget while failing",
    )


def _failure_status(outcome: SolverOutcome) -> str:
    return {
        SolverOutcome.INACCURATE: cp.OPTIMAL_INACCURATE,
        SolverOutcome.INFEASIBLE: cp.INFEASIBLE,
        SolverOutcome.UNBOUNDED: cp.UNBOUNDED,
        SolverOutcome.TIMEOUT: "timeout",
        SolverOutcome.NONFINITE: "nonfinite_solution",
        SolverOutcome.ERROR: "solver_error",
        SolverOutcome.FAILED_STATUS: "solver_failed",
        SolverOutcome.UNAVAILABLE: "no_solver_available",
        SolverOutcome.SUCCESS: cp.OPTIMAL,
    }[outcome]


__all__ = [
    "DEFAULT_SOLVER_PRIORITY",
    "SolutionSource",
    "SolutionValue",
    "SolverAttempt",
    "SolverOutcome",
    "SolverResult",
    "shift_warm_start_sequence",
    "solve_cvxpy_problem",
    "solver_version",
]
