"""Run auditable one-variable MOSEK and GUROBI license/solver smoke checks."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import cvxpy as cp


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", type=Path, default=Path.cwd())
    return result


def _solve(solver: str) -> dict[str, object]:
    variable = cp.Variable(name="x")
    problem = cp.Problem(cp.Minimize(cp.square(variable - 1.0)), [variable >= 0.0])
    start = time.perf_counter()
    try:
        value = problem.solve(solver=solver, verbose=False)
        return {
            "solver": solver,
            "success": problem.status in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE},
            "status": problem.status,
            "objective": None if value is None else float(value),
            "x": None if variable.value is None else float(variable.value),
            "wall_time_s": time.perf_counter() - start,
            "failure_type": None,
            "failure_message": None,
        }
    except Exception as error:
        return {
            "solver": solver,
            "success": False,
            "status": "exception",
            "objective": None,
            "x": None,
            "wall_time_s": time.perf_counter() - start,
            "failure_type": type(error).__name__,
            "failure_message": str(error),
        }


def main() -> int:
    arguments = parser().parse_args()
    root = arguments.repo_root.resolve()
    payload = {
        "schema_version": "d5freq.phase_b1.solver_smoke.v1",
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "installed_solvers": sorted(cp.installed_solvers()),
        "checks": [_solve("MOSEK"), _solve("GUROBI")],
    }
    destination = root / "logs_phase_b1" / "solver_smoke.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0 if all(row["success"] for row in payload["checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
