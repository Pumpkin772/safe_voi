from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.phase_f.run_f0_forensic import decompose_frozen_e6


ROOT = Path(__file__).resolve().parents[2]


def test_phase_e_rejection_and_fallback_leave_stale_candidate() -> None:
    # F0 is frozen evidence.  The live implementation is intentionally fixed
    # in F2, so rerunning the pre-fix controller would be the wrong test.
    evidence = pd.read_csv(
        ROOT / "results_phase_f" / "F0" / "ACTION_HISTORY_MISMATCH.csv"
    )
    assert set(evidence["case"]) == {
        "candidate_solved_then_forced_solver_failure",
        "successful_candidate_terminal_rejected",
        "second_consecutive_terminal_reject",
    }
    assert evidence["fallback_used"].all()
    assert (~evidence["history_match"].astype(bool)).all()
    assert (evidence["mismatch_inf_norm"] > 0.0).all()


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
