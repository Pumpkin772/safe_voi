from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_certificate_is_recomputable_and_does_not_overclaim() -> None:
    script = (
        ROOT
        / "research_outputs_phase_f"
        / "05_THEORY"
        / "NUMERICAL_CERTIFICATE_REPRODUCTION.py"
    )
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    certificate = json.loads(
        (
            ROOT
            / "research_outputs_phase_f"
            / "05_THEORY"
            / "ROBUST_BACKUP_SET_CERTIFICATE.json"
        ).read_text()
    )
    assert certificate["certificate_status"] == "FINITE_HORIZON_ONLY"
    assert certificate["recursive_feasibility_certified"] is False
    assert certificate["robust_switching_safety_certified"] is False


def test_f5_stop_rule_is_recorded_not_silently_relaxed() -> None:
    progress = json.loads((ROOT / "progress_phase_f" / "F5.json").read_text())
    assert progress["gate_passed"] is False
    assert progress["stop_status"] == "NO_NONEMPTY_ROBUST_BACKUP_SET"
    assert progress["next_stage"] == "F9_NEGATIVE_PACKAGE"

