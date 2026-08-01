from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from scripts.phase_f.run_f0_forensic import (
    decompose_frozen_e6,
    reproduce_action_history_mismatch,
)


ROOT = Path(__file__).resolve().parents[2]


def test_phase_e_rejection_and_fallback_leave_stale_candidate() -> None:
    evidence = reproduce_action_history_mismatch()
    assert set(evidence["case"]) == {
        "candidate_solved_then_forced_solver_failure",
        "successful_candidate_terminal_rejected",
        "second_consecutive_terminal_reject",
    }
    assert evidence["fallback_used"].all()
    assert (~evidence["history_match"]).all()
    assert np.all(evidence["mismatch_inf_norm"] > 0.0)


def test_legacy_trace_cannot_support_mathematical_infeasibility_claim() -> None:
    _decomposition, summary = decompose_frozen_e6()
    row = summary.iloc[0]
    assert row["layer_classification_fraction"] >= 0.95
    assert not bool(row["mathematical_vs_numerical_identifiable"])
    assert not bool(row["actual_model_action_match_identifiable"])


def test_f0_progress_records_withdrawn_overclaim() -> None:
    progress = json.loads((ROOT / "progress_phase_f" / "F0.json").read_text())
    assert progress["gate_passed"] is True
    assert progress["claim_correction"] == (
        "METHOD_IMPLEMENTATION_AND_CERTIFICATE_INCOMPLETE"
    )

