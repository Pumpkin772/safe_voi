from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCIENCE = ROOT / "research_outputs_phase_e" / "01_SCIENCE"
LITERATURE = ROOT / "research_outputs_phase_e" / "02_LITERATURE"
THEMES = (
    "theme_black_box_ibr_multimode",
    "theme_data_driven_frequency_control",
    "theme_set_adaptive_tube_mpc",
    "theme_active_dual_safe_identification",
    "theme_multi_area_agc_ace_constrained",
)


def load_rows() -> list[dict[str, str]]:
    with (LITERATURE / "LITERATURE_MATRIX.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_e1_formal_verified_corpus_and_no_duplicates() -> None:
    rows = load_rows()
    assert len(rows) >= 50
    assert sum(row["formal_peer_reviewed_or_standard"] == "True" for row in rows) >= 50
    assert all(row["metadata_verification"] for row in rows)
    dois = [row["doi"].casefold() for row in rows if row["doi"]]
    titles = [" ".join(row["title"].casefold().split()) for row in rows]
    assert len(dois) == len(set(dois))
    assert len(titles) == len(set(titles))


def test_e1_preregistered_family_quotas() -> None:
    rows = load_rows()
    counts = {theme: sum(row[theme] == "True" for row in rows) for theme in THEMES}
    assert counts[THEMES[0]] >= 10
    assert counts[THEMES[1]] >= 10
    assert counts[THEMES[2]] >= 10
    assert counts[THEMES[3]] >= 8
    assert counts[THEMES[4]] >= 10


def test_e1_hypotheses_information_and_branch_boundaries_are_frozen() -> None:
    question = (SCIENCE / "SCIENTIFIC_QUESTION_AND_HYPOTHESES.md").read_text(encoding="utf-8")
    claims = (SCIENCE / "CLAIM_BOUNDARY.md").read_text(encoding="utf-8")
    for hypothesis in ("H1", "H2", "H3", "H4", "H5"):
        assert hypothesis in question
    for forbidden in ("true capability regime", "true net load", "future load", "final-seed"):
        assert forbidden in question
    for branch in ("**P**", "**A**", "**R**"):
        assert branch in question
    assert "first MPC/AI/set estimator" in claims


def test_e1_closest_works_and_claim_evidence_mapping() -> None:
    novelty = (LITERATURE / "NOVELTY_COMPARISON.md").read_text(encoding="utf-8")
    assert novelty.count("| Huang et al.") == 1
    assert novelty.count("| Rezaei et al.") == 1
    assert novelty.count("| Parsi et al.") == 1
    with (SCIENCE / "CLAIM_EVIDENCE_MATRIX.csv").open(encoding="utf-8", newline="") as stream:
        claims = list(csv.DictReader(stream))
    assert len(claims) == 5
    assert {row["claim_id"] for row in claims} == {"C1", "C2", "C3", "C4", "C5"}


def test_e1_progress_and_metadata_gate() -> None:
    evidence = json.loads((LITERATURE / "METADATA_VERIFICATION.json").read_text(encoding="utf-8"))
    progress = json.loads((ROOT / "progress_phase_e" / "E1.json").read_text(encoding="utf-8"))
    assert evidence["gate"] == "PASS"
    assert evidence["novelty_result"] == "CONDITIONAL_INTERSECTION_SUPPORTED_FOR_TESTING"
    assert evidence["closest_work_rows"] >= 3
    assert progress["gate_passed"] is True
    assert progress["next_stage"] == "E2"
