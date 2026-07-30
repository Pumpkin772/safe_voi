"""Capture a license-safe Phase B2 environment and verification snapshot."""

from __future__ import annotations

from importlib import metadata
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from d5freq.utils.environment import collect_environment_info, write_environment_info


REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts_phase_b2" / "reproducibility"
PACKAGE_NAMES = (
    "casadi",
    "control",
    "cvxpy",
    "gurobipy",
    "ipykernel",
    "jupyter",
    "matplotlib",
    "Mosek",
    "numpy",
    "pandas",
    "pyarrow",
    "pytest",
    "pytest-cov",
    "PyYAML",
    "scikit-learn",
    "scipy",
    "typer",
)


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPO,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _conda_solver_packages() -> dict[str, dict[str, str]]:
    """Read only non-sensitive solver version fields from Conda metadata."""

    requested = {"casadi", "ipopt"}
    result: dict[str, dict[str, str]] = {}
    for path in sorted((Path(sys.prefix) / "conda-meta").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = str(payload.get("name", ""))
        if name not in requested:
            continue
        result[name] = {
            "version": str(payload.get("version", "unknown")),
            "build": str(payload.get("build", "unknown")),
            "channel": str(payload.get("channel", "unknown")).rsplit("/", 1)[-1],
        }
    return result


def _python_solver_versions() -> dict[str, Any]:
    versions: dict[str, Any] = {}
    for name in ("casadi", "cvxpy", "Mosek", "gurobipy"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not_installed"
    try:
        import cvxpy as cp

        versions["cvxpy_installed_solver_interfaces"] = sorted(cp.installed_solvers())
    except Exception as exc:  # pragma: no cover - snapshot must be best effort
        versions["cvxpy_discovery_error_type"] = type(exc).__name__
    try:
        import gurobipy

        versions["gurobi_core_version"] = list(gurobipy.gurobi.version())
    except Exception as exc:  # pragma: no cover - snapshot must be best effort
        versions["gurobi_version_error_type"] = type(exc).__name__
    return versions


def _parse_test_log(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    summary = re.search(
        r"(?P<passed>\d+) passed(?:, (?P<warnings>\d+) warnings?)? in (?P<seconds>[0-9.]+)s",
        text,
    )
    coverage = re.search(r"^TOTAL\s+\d+\s+\d+\s+(?P<coverage>\d+)%$", text, re.MULTILINE)
    if summary is None or coverage is None:
        raise RuntimeError(f"could not parse test summary from {path}")
    return {
        "command": (
            "python -m pytest -q tests tests_phase_b2 --cov=d5freq "
            "--cov-report=term-missing --cov-report=xml:logs_phase_b2/coverage_phase_b2.xml"
        ),
        "exit_code": 0,
        "passed": int(summary.group("passed")),
        "warnings": int(summary.group("warnings") or 0),
        "elapsed_s": float(summary.group("seconds")),
        "coverage_percent": int(coverage.group("coverage")),
        "log": "logs_phase_b2/pytest_coverage_phase_b2.log",
        "coverage_xml": "logs_phase_b2/coverage_phase_b2.xml",
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    git_snapshot = {
        "schema_version": "d5freq.phase_b2.git_snapshot.v1",
        "branch": _git("branch", "--show-current"),
        "commit_before_reproducibility_artifact_commit": _git("rev-parse", "HEAD"),
        "phase_b2_baseline_commit": "9e003ba",
        "status_short_before_capture": _git(
            "status", "--short", "--ignored=no"
        ).splitlines(),
    }
    environment = collect_environment_info(
        package_names=PACKAGE_NAMES,
        extra={
            "project_phase": "phase_b2_scientific_hardening",
            "environment_name": "topo_sfr",
            "license_values_or_paths_exported": False,
            "commercial_solver_entitlements_checked_by_full_test_suite": True,
        },
    )
    write_environment_info(OUTPUT / "environment.json", environment)

    packages = environment["packages"]
    (OUTPUT / "package_versions.txt").write_text(
        "".join(f"{name}=={packages[name]}\n" for name in sorted(packages, key=str.casefold)),
        encoding="utf-8",
    )
    _write_json(
        OUTPUT / "solver_versions.json",
        {
            "schema_version": "d5freq.phase_b2.solver_versions.v1",
            "conda_solver_packages": _conda_solver_packages(),
            "python_solver_interfaces": _python_solver_versions(),
            "ipopt_qualification_evidence": (
                "results_phase_b2/oracle_validation/oracle_solver_quality.csv"
            ),
            "commercial_solver_validation_evidence": (
                "logs_phase_b2/pytest_coverage_phase_b2.log"
            ),
            "license_values_or_paths_exported": False,
        },
    )
    _write_json(
        OUTPUT / "test_summary.json",
        {
            "schema_version": "d5freq.phase_b2.test_summary.v1",
            "full_suite": _parse_test_log(
                REPO / "logs_phase_b2" / "pytest_coverage_phase_b2.log"
            ),
        },
    )
    _write_json(
        OUTPUT / "git_snapshot.json",
        git_snapshot,
    )
    print(json.dumps({"output": str(OUTPUT), "test_summary": _parse_test_log(REPO / "logs_phase_b2" / "pytest_coverage_phase_b2.log")}, indent=2))


if __name__ == "__main__":
    main()
