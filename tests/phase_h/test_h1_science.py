from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def test_literature_gate_has_current_formal_primary_basis() -> None:
    registry = pd.read_csv(
        ROOT / "research_outputs_phase_h/02_LITERATURE/CORE_LITERATURE_REGISTRY.csv"
    )
    assert len(registry) >= 50
    assert registry.year.between(2019, 2026).all()
    assert registry.formal_or_official.mean() >= 0.80
    assert not registry.covers_complete_dcsv_intersection.any()


def test_hypotheses_and_claim_evidence_are_locked() -> None:
    text = (
        ROOT / "research_outputs_phase_h/01_SCIENCE/HYPOTHESES_H1_H6.md"
    ).read_text()
    for index in range(1, 7):
        assert f"H{index}:" in text
    claims = pd.read_csv(
        ROOT / "research_outputs_phase_h/02_LITERATURE/CLAIM_CLOSEST_GAP.csv"
    )
    assert len(claims) == 5
    assert claims.required_evidence.str.len().gt(0).all()


def test_h1_progress_preserves_final_firewall() -> None:
    progress = json.loads((ROOT / "progress_phase_h/H1.json").read_text())
    assert progress["gate_passed"] is True
    assert progress["final_seeds_consumed"] is False
    assert progress["next_stage"] == "H2"
