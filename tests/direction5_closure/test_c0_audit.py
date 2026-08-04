from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]


def test_c0_independent_replication_is_exact() -> None:
    result = json.loads((REPO / "results_closure/C0/C0_REPLICATION.json").read_text("utf-8"))
    assert result["status"] == "PASS"
    assert result["zip_sha_matches"] is True
    assert result["manifest_verified"] is True
    assert result["fresh_extract_minimal_replay"]["passed"] is True
    assert result["statistics_comparisons"] == result["statistics_within_tolerance"] == 262
    assert result["optimization_decisions"] == 20271
    assert result["raw_solver_invocations"] == 21293
    assert result["final_seeds_unused"] is True


def test_c0_gate_and_semantic_decisions_match() -> None:
    gates = pd.read_csv(REPO / "research_outputs_closure/00_AUDIT/RECOMPUTED_GATES.csv")
    semantics = pd.read_csv(REPO / "research_outputs_closure/00_AUDIT/CODE_SEMANTICS_AUDIT.csv")
    assert len(gates) == 19
    assert gates.matches.all()
    assert len(semantics) == 8
    assert semantics.passed.all()


def test_c0_did_not_consume_final_seeds_or_change_method() -> None:
    progress = json.loads((REPO / "progress_closure/C0.json").read_text("utf-8"))
    assert progress["deterministic_bug_found"] is False
    assert progress["method_or_threshold_changed"] is False
    assert progress["final_seeds_consumed"] is False
