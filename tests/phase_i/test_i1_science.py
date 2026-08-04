from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]


def test_i1_registry_is_current_formal_and_has_no_complete_prior_intersection() -> None:
    registry = pd.read_csv(REPO / "research_outputs_phase_i/02_LITERATURE/CORE_LITERATURE_REGISTRY.csv")
    assert len(registry) >= 60
    assert registry.year.between(2019, 2026).all()
    assert registry.access_date.eq("2026-08-04").all()
    assert registry.formal_or_official.astype(bool).mean() >= 0.9
    assert not registry.covers_complete_dcsv_intersection.astype(bool).any()


def test_i1_scope_uses_actual_poi_and_only_power_ramp_delay_are_hidden() -> None:
    question = (REPO / "research_outputs_phase_i/01_SCIENCE/LOCKED_SCIENTIFIC_QUESTION.md").read_text("utf-8")
    assert "actual BESS POI power" in question
    assert "{P+, P-, R+, R-, delay}" in question
    assert "Energy is computed from measured SoC" in question
    assert "Availability is not estimated" in question


def test_i1_hypotheses_and_impossibility_boundary_are_falsifiable() -> None:
    hypotheses = (REPO / "research_outputs_phase_i/01_SCIENCE/HYPOTHESES_H1_H6.md").read_text("utf-8")
    for hypothesis in ("H1", "H2", "H3", "H4", "H5", "H6"):
        assert f"| {hypothesis} |" in hypotheses
    assert ">=95%" in hypotheses
    assert "<=1%" in hypotheses
    boundary = (REPO / "research_outputs_phase_i/01_SCIENCE/IMPOSSIBILITY_BOUNDARY.md").read_text("utf-8")
    assert "identical public input/output histories" in boundary
    assert "no history-only controller" in boundary
    assert "contract violation" in boundary


def test_i1_novelty_is_bounded_and_mapped() -> None:
    novelty = pd.read_csv(REPO / "research_outputs_phase_i/02_LITERATURE/NOVELTY_MATRIX.csv")
    assert len(novelty) >= 5
    assert novelty.novelty_boundary.eq("intersection contribution only").all()
    assert not novelty.exact_complete_prior_work_found.astype(bool).any()
    assert novelty.required_evidence.notna().all()
    progress = json.loads((REPO / "progress_phase_i/I1.json").read_text("utf-8"))
    assert progress["gate_passed"]
    assert progress["novelty_claim"] == "INTERSECTION_CONTRIBUTION_ONLY"
    assert not progress["final_seeds_consumed"]
