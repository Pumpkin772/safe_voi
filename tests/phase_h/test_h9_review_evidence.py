from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]


def test_control_cycle_export_matches_frozen_h7_taxonomy() -> None:
    summary = json.loads(
        (REPO / "results_phase_h/H9/CONTROL_CYCLE_EVIDENCE_SUMMARY.json").read_text("utf-8")
    )
    assert summary["rows"] == 75131
    assert summary["scenarios"] == 48
    assert summary["methods"] == 7
    assert summary["failed_solver_cycle_rows"] == 13
    assert summary["frozen_h7_decision_unchanged"]
    failed = pd.read_parquet(
        REPO / "results_phase_h/H9/H7_ALL_FAILED_SOLVER_CYCLE_TRACES.parquet"
    )
    assert len(failed) == 13
    assert not failed.physical_infeasibility_preclassified.any()
    assert failed.fallback_used.all()


def test_trace_replay_preserves_every_frozen_episode_metric() -> None:
    audit = pd.read_csv(REPO / "results_phase_h/H9/H7_TRACE_REPLAY_AUDIT.csv")
    assert len(audit) == 44 * 7 * 4
    assert audit.matches_frozen.all()
    assert audit.absolute_difference.max() <= 1e-9


def test_final_status_never_reinterprets_h7_or_h8() -> None:
    status = json.loads(
        (REPO / "results_phase_h/final/FINAL_STATUS.json").read_text("utf-8")
    )
    assert status["project_upper"] == "DIRECTION5"
    assert status["method"] == "DCSV-MPC"
    assert status["gates"]["H7"] == "FAIL"
    assert status["gates"]["H8"] == "NOT_EVALUATED"
    assert status["hypotheses"]["H5"].startswith("NOT_SUPPORTED")
    assert not status["final_seeds_consumed"]
    assert not status["theory"]["unqualified_recursive_feasibility_certified"]


def test_review_figures_have_all_registered_formats_and_source_data() -> None:
    bases = ("DOMAIN_PARTITION_COUNTS", "TERMINAL_COVERAGE", "H7_PAIRED_VALIDATION")
    for base in bases:
        for suffix in (".svg", ".pdf", ".png"):
            path = REPO / f"figures_phase_h/H9/{base}{suffix}"
            assert path.stat().st_size > 1000
    assert len(list((REPO / "figures_phase_h/H9").glob("*_SOURCE.csv"))) == 2


def test_h9_pass_requires_fresh_extract_trial_verification() -> None:
    progress = json.loads((REPO / "progress_phase_h/H9.json").read_text("utf-8"))
    if progress["status"] == "PASS":
        assert progress["gate_passed"]
        assert all(progress["gate_components"].values())
        verification = json.loads(
            (REPO / "results_phase_h/H9/TRIAL_PACKAGE_VERIFICATION.json").read_text(
                "utf-8"
            )
        )
        assert verification["fresh_extract_manifest_verified"]
        assert verification["fresh_extract_minimal_replay_verified"]
        assert verification["packaged_phase_h_tests"] == "40 passed"
