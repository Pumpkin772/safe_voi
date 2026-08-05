from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research_outputs_closure" / "03_PAPER"


def test_c3_manuscript_is_actual_results_negative_route() -> None:
    progress = json.loads((ROOT / "progress_closure" / "C3.json").read_text(encoding="utf-8"))
    assert progress["status"] == "PASS"
    assert progress["route"] == "NEGATIVE_RESULT_MANUSCRIPT"
    assert progress["joint_positive_gate"] is False
    text = (OUT / "PAPER_DRAFT.md").read_text(encoding="utf-8")
    assert "[" + "PREDICTED" + "]" not in text
    assert "did not outperform" in text
    assert "seeds 100--159" in text


def test_c3_deliverables_and_claim_ledger() -> None:
    expected = {
        "PAPER_DRAFT.md",
        "ABSTRACT.md",
        "CONTRIBUTIONS.md",
        "RESULTS_SECTION.md",
        "LIMITATIONS.md",
        "SUPPORTED_UNSUPPORTED_CLAIMS.md",
        "REVIEWER_RISK_REGISTER.md",
        "CLAIM_LEDGER.csv",
    }
    assert expected <= {path.name for path in OUT.iterdir()}
    with (OUT / "CLAIM_LEDGER.csv").open(encoding="utf-8", newline="") as handle:
        claims = {row["claim"]: row["status"] for row in csv.DictReader(handle)}
    assert claims["DCSV_CR_MPC_SUPERIORITY"] == "NOT_SUPPORTED"
    assert claims["PERFECT_CAPABILITY_VALUE"] == "SUPPORTED_WITH_BOUNDS"
