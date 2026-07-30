from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
FORENSIC = ROOT / "research_outputs_phase_e" / "forensic"


def test_independent_audit_matches_registered_expected_output() -> None:
    comparison = pd.read_csv(FORENSIC / "INDEPENDENT_AUDIT_COMPARISON.csv")
    assert len(comparison) >= 30
    assert comparison["match"].all()
    actual = json.loads((FORENSIC / "INDEPENDENT_AUDIT_RESULTS.json").read_text(encoding="utf-8"))
    delay = actual["delay_update_replay"]
    assert delay["first_correct_singleton_delay_set_s"] == 45.6
    assert delay["first_cusum_alarm_s"] is None
    assert delay["phase_d_evaluator_update_time_s"] is None


def test_phase_d_archive_is_complete_and_immutable_by_index() -> None:
    index = pd.read_csv(FORENSIC / "PHASE_D_EVIDENCE_INDEX.csv")
    assert len(index) == 240
    assert index["hash_match"].all()
    assert set(index["retention"]) == {"read_only_phase_d_archive"}


def test_phase_d_gate_is_explicitly_invalidated_not_generalized() -> None:
    payload = json.loads((FORENSIC / "PHASE_D_INVALIDATED_CLAIMS.json").read_text(encoding="utf-8"))
    assert payload["phase_d_revised_status"] == "PHASE_D_GATE_INVALIDATED_BY_CLOSED_LOOP_AND_EVALUATION_DEFECTS"
    assert payload["phase_d_h2_scientific_gate_valid"] is False
    assert payload["general_passive_impossibility_supported"] is False
    assert all(payload["source_findings"].values())


def test_frozen_tag_and_phase_e_branch() -> None:
    tag_commit = subprocess.check_output(
        ["git", "rev-list", "-n", "1", "direction1-phase-d-negative-reviewed"], cwd=ROOT, text=True
    ).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    assert tag_commit == "11f0379e0e7bd9b1ddf97be8d88b7f918bbb52e9"
    assert branch == "direction1-phase-e-science-recovery"
