from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def test_historical_phase_g_is_reclassified_without_overwrite() -> None:
    progress = json.loads((ROOT / "progress_phase_h/H0.json").read_text())
    assert progress["gate_passed"] is True
    assert (
        progress["final_reclassification"]
        == "TERMINAL_SET_CALIBRATION_PREMATURE_AND_MISSPECIFIED"
    )
    assert progress["final_seeds_consumed"] is False
    assert (ROOT / "progress_phase_g/G2.json").is_file()


def test_every_historical_included_window_has_full_forensic_labels() -> None:
    audit = pd.read_parquet(
        ROOT / "results_phase_h/H0/NEAR_TERMINAL_VALIDITY_AUDIT.parquet"
    )
    old = pd.read_parquet(
        ROOT / "results_phase_g/G2/G2_STRUCTURED_RESIDUAL_WINDOWS.parquet"
    )
    assert len(audit) == int(old.terminal_window_included.sum())
    assert audit.primary_exclusion_reason_h0.notna().all()
    assert audit.all_exclusion_reasons_h0.notna().all()
    assert audit.h0_domain_label_is_forensic_not_h2_registered.all()


def test_phase_g_zip_cannot_fully_rebuild_g2_without_external_scripts() -> None:
    audit = pd.read_csv(ROOT / "results_phase_h/H0/G2_DEPENDENCY_AUDIT.csv")
    assert len(audit) == 2
    assert audit.repository_present.all()
    assert not audit.phase_g_package_present.any()
    assert not audit.full_g2_replay_from_phase_g_zip_only.any()


def test_large_residual_sources_meet_registered_explanation_gate() -> None:
    result = json.loads(
        (ROOT / "results_phase_h/H0/CURRENT_CERTIFICATE_REPRODUCTION.json").read_text()
    )
    assert result["scenarios_replayed"] == 40
    assert result["periods_replayed_s"] == [2.0, 4.0]
    assert result["large_residual_source_explained_fraction"] >= 0.95
