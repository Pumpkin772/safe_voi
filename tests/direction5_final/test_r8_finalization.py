from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]


def test_unique_final_state_and_stopping_path() -> None:
    status = json.loads((REPO / "results_final/final/FINAL_STATUS.json").read_text("utf-8"))
    assert status["final_status"] == "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE"
    assert status["R0_R8"]["R5"] == "FAIL"
    assert status["R0_R8"]["R6"] == "NOT_EVALUATED"
    assert status["R0_R8"]["R7"] == "NOT_EVALUATED"
    assert status["final_seeds_consumed"] is False


def test_h5_is_not_supported_without_erasing_bounded_findings() -> None:
    hypotheses = pd.read_csv(REPO / "results_final/final/HYPOTHESES_H1_H6.csv")
    states = dict(zip(hypotheses.hypothesis, hypotheses.status))
    assert states["H5"] == "NOT_SUPPORTED"
    assert states["H1"] == "SUPPORTED"
    assert states["H2"] == "SUPPORTED"
    assert states["H6"] == "SUPPORTED_WITH_CONDITIONAL_SCOPE"


def test_r6_r7_are_not_evaluated_and_final_seeds_are_unused() -> None:
    for stage in ("R6", "R7"):
        record = json.loads((REPO / f"progress_final/{stage}.json").read_text("utf-8"))
        assert record["status"] == "NOT_EVALUATED"
        assert record["not_evaluated_is_not_failure_or_success"] is True
        assert record["final_seeds_consumed"] is False


def test_review_package_replay_scripts_are_stdlib_only() -> None:
    for name in ("package_verify_manifest.py", "package_reproduce_minimal.py"):
        text = (REPO / "scripts/direction5_final" / name).read_text("utf-8")
        assert "pandas" not in text
        assert "numpy" not in text
        assert "if __name__ == \"__main__\":" in text
