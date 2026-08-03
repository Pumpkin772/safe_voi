"""Run the package-local minimal replay without any external repository file."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "06_SOURCE/repository"


def main() -> None:
    status = json.loads((ROOT / "17_FINAL_STATUS/FINAL_STATUS.json").read_text("utf-8"))
    assert status["project_upper"] == "DIRECTION5"
    assert status["method"] == "DCSV-MPC"
    assert status["gates"]["H7"] == "FAIL"
    assert status["gates"]["H8"] == "NOT_EVALUATED"
    assert not status["final_seeds_consumed"]
    assert status["known_result"] == "NOT_EVALUATED"
    assert status["ood_result"] == "NOT_EVALUATED"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(SNAPSHOT / "src") + os.pathsep + str(SNAPSHOT)
    certificate = subprocess.run(
        [sys.executable, "research_outputs_phase_h/05_THEORY/REPRODUCE_CERTIFICATES.py"],
        cwd=SNAPSHOT,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    if "H6_CERTIFICATES_REPLAYED 58 26" not in certificate.stdout:
        raise SystemExit("certificate replay marker missing")
    tests = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/phase_h", "-q"],
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
    if "39 passed" not in tests.stdout:
        raise SystemExit(f"unexpected packaged test result: {tests.stdout}")
    print("DIRECTION5_PHASE_H_MINIMAL_REPLAY_OK 39_tests final_seeds=false")


if __name__ == "__main__":
    main()
