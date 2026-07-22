"""Export a sanitized Phase 0 environment and solver-readiness record."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from importlib import metadata
import io
import json
from pathlib import Path
import time
from typing import Any

import cvxpy as cp

from d5freq.utils.environment import collect_environment_info, write_environment_info


def sanitized_package_inventory() -> list[str]:
    """Return installed distributions as sorted ``name==version`` records."""

    packages = {
        f"{dist.metadata.get('Name', 'unknown')}=={dist.version}"
        for dist in metadata.distributions()
    }
    return sorted(packages, key=str.casefold)


def probe_solver(solver: str) -> dict[str, Any]:
    """Solve a tiny convex QCQP without retaining solver console output."""

    x = cp.Variable(name="x")
    problem = cp.Problem(
        cp.Minimize(cp.square(x - 1.0)),
        [x >= 0.0, cp.square(x) <= 4.0],
    )
    started = time.perf_counter()
    try:
        # Commercial solvers can print license routing details even with
        # verbose=False. Suppress them and never persist captured text.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            objective = problem.solve(solver=solver, verbose=False)
        return {
            "solver": solver,
            "status": problem.status,
            "objective": float(objective),
            "x": float(x.value),
            "elapsed_s": time.perf_counter() - started,
        }
    except Exception as exc:  # Failure is evidence and must be retained.
        return {
            "solver": solver,
            "status": "error",
            "error_type": type(exc).__name__,
            "elapsed_s": time.perf_counter() - started,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("progress"))
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    environment = collect_environment_info(
        extra={
            "project_environment": "topo_sfr",
            "environment_reuse_approved_by_user": True,
        }
    )
    write_environment_info(output_dir / "environment_phase0.json", environment)

    probes = {
        "schema_version": 1,
        "problem_class": "convex_qcqp",
        "results": [
            probe_solver(solver) for solver in ("MOSEK", "GUROBI", "CLARABEL")
        ],
    }
    (output_dir / "solver_smoke_phase0.json").write_text(
        json.dumps(probes, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "packages_phase0.txt").write_text(
        "\n".join(sanitized_package_inventory()) + "\n",
        encoding="utf-8",
    )
    return 0 if all(item["status"] == "optimal" for item in probes["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

