from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research_outputs_phase_d" / "literature"


def test_d1_literature_gate() -> None:
    with (OUT / "LITERATURE_MATRIX.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) >= 50
    assert sum(int(row["year"]) >= 2022 for row in rows) >= 30
    assert sum(row["formal_peer_reviewed_or_standard"] == "True" for row in rows) / len(rows) >= 0.8
    assert all(row["metadata_verification"] for row in rows)


def test_d1_required_anchors_and_metadata_correction() -> None:
    evidence = json.loads((OUT / "METADATA_VERIFICATION.json").read_text(encoding="utf-8"))
    assert evidence["gate"] == "PASS"
    assert all(evidence["anchors"].values())
    assert "ACC, not TCST" in evidence["launch_metadata_correction"]

