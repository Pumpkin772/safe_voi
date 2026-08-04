"""Run a package-local Phase-I replay with explicit dependency diagnostics."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "06_SOURCE/repository"
ALLOWED_OUTCOMES = {
    "PAPER_READY_WITH_BOUNDED_CLAIMS",
    "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE",
}
REQUIRED_MODULES = ("numpy", "pandas", "pyarrow", "scipy", "cvxpy", "andes", "yaml", "pytest")


def require_dependencies() -> None:
    missing = []
    for module in REQUIRED_MODULES:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(module)
    if missing:
        print("Missing package-local replay dependencies: " + ", ".join(missing), file=sys.stderr)
        print(
            "Create/update the registered environment with: "
            "conda env update --name topo_sfr --file "
            "06_SOURCE/repository/environment.yml --prune",
            file=sys.stderr,
        )
        print(
            "Then run: conda run -n topo_sfr python "
            "15_REPRODUCIBILITY/reproduce_minimal.py",
            file=sys.stderr,
        )
        raise SystemExit(2)


def main() -> None:
    require_dependencies()
    status_path = ROOT / "17_FINAL_STATUS/FINAL_STATUS.json"
    status = json.loads(status_path.read_text("utf-8"))
    assert status["project_upper"] == "DIRECTION5"
    assert status["method"] == "DCSV-MPC"
    assert status["final_research_status"] in ALLOWED_OUTCOMES
    assert status["phase_h_h7_method_evidence_withdrawn"]
    assert status["certificate_status"] == "CONDITIONAL_LOCAL_RPI_PLUS_FINITE_HORIZON_BRIDGE"
    assert status["gates"]["I0"] == "PASS"
    assert status["gates"]["I1"] == "PASS"
    assert status["gates"]["I2"] == "PASS"
    assert status["gates"]["I3"] == "PASS"
    assert status["gates"]["I4"] == "PASS"
    assert status["gates"]["I5"] == "PASS"
    assert status["gates"]["I6"] in {"PASS", "FAIL"}
    if status["gates"]["I6"] == "FAIL":
        assert status["gates"]["I7"] == "NOT_EVALUATED"
        assert not status["final_seeds_consumed"]
        assert status["final_research_status"] == "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE"

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(SNAPSHOT / "src") + os.pathsep + str(SNAPSHOT)
    expected = json.loads((ROOT / "08_TESTS_VERIFICATION/TEST_RESULT.json").read_text("utf-8"))
    tests = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/phase_i", "-q"],
        cwd=SNAPSHOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if tests.returncode != 0:
        print(tests.stdout)
        print(tests.stderr, file=sys.stderr)
        raise SystemExit(tests.returncode)
    marker = f"{expected['passed']} passed"
    if marker not in tests.stdout:
        raise SystemExit(f"unexpected packaged test result; wanted {marker}: {tests.stdout}")

    theory = json.loads((ROOT / "10_RAW_RESULTS/progress_phase_i/I5.json").read_text("utf-8"))
    assert theory["certificate_status"] == "CONDITIONAL_LOCAL_RPI_PLUS_FINITE_HORIZON_BRIDGE"
    assert theory["dense_delay_points"] >= 100
    assert theory["native_plant_b_theory"] == "EMPIRICAL_VALIDATION_ONLY"
    print(
        "DIRECTION5_PHASE_I_MINIMAL_REPLAY_OK "
        f"{marker.replace(' ', '_')} outcome={status['final_research_status']} "
        f"final_seeds={str(status['final_seeds_consumed']).lower()}"
    )


if __name__ == "__main__":
    main()
