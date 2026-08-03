from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]


def test_h7_negative_gate_is_complete_and_final_was_not_entered() -> None:
    progress = json.loads((REPO / "progress_phase_h/H7.json").read_text("utf-8"))
    lock = json.loads(
        (REPO / "configs/phase_h/H7_FINAL_LOCK.json").read_text("utf-8")
    )
    assert not progress["gate_passed"]
    assert progress["repairs_used"] == 2
    assert len(progress["failures"]) == 3
    assert not progress["gate_components"][
        "at_least_two_of_three_metrics_improve_8pct_positive_ci"
    ]
    assert not progress["gate_components"]["unsolved_fraction_at_most_0_1pct"]
    assert not lock["locked"]
    assert not lock["final_seeds_consumed"]


def test_h7_preserves_infeasibility_and_solver_outcomes() -> None:
    episodes = pd.read_parquet(
        REPO / "results_phase_h/H7/H7_VALIDATION_EPISODES.parquet"
    )
    infeasible = episodes[episodes.physically_infeasible_preclassified]
    ordinary = episodes[~episodes.physically_infeasible_preclassified]
    assert len(infeasible) > 0
    assert infeasible.physical_success.isna().all()
    assert not infeasible.ordinary_controller_failure.any()
    assert not ordinary.hard_violation.any()
    assert int(ordinary.unsolved_calls.sum()) == 13
    assert int(ordinary.fallback_calls.sum()) == 13
    assert int(ordinary.restoration_calls.sum()) == 0
    assert int(ordinary.action_history_mismatches.sum()) == 0


def test_h7_registered_statistics_are_not_reinterpreted() -> None:
    metrics = pd.read_csv(REPO / "results_phase_h/H7/H7_PAIRED_METRICS.csv")
    assert len(metrics) == 3
    assert int(metrics.passes_8pct_and_positive_ci.sum()) == 0
    progress = json.loads((REPO / "progress_phase_h/H7.json").read_text("utf-8"))
    summary = progress["paired_validation_summary"]
    assert summary["dcsv_success_rate"] == summary["baseline_success_rate"] == 1.0
    assert summary["dcsv_failure_aware_cost"] < summary["baseline_failure_aware_cost"]


def test_h8_is_not_evaluated_not_failed_or_passed() -> None:
    progress = json.loads((REPO / "progress_phase_h/H8.json").read_text("utf-8"))
    assert progress["status"] == "NOT_EVALUATED"
    assert progress["gate_passed"] is None
    assert not progress["final_seeds_consumed"]
    assert progress["known_result"] == "NOT_EVALUATED"
    assert progress["ood_result"] == "NOT_EVALUATED"
