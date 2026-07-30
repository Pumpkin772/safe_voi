from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def test_binding_final_status_and_hypotheses() -> None:
    status = json.loads((ROOT / "research_outputs_phase_d" / "final" / "FINAL_STATUS.json").read_text(encoding="utf-8"))
    assert status["final_research_status"] == "PASSIVE_CAPABILITY_SET_NOT_SUPPORTED"
    assert status["H2"] == "REJECTED"
    assert status["H1"].startswith("NOT_EVALUATED")
    assert status["H3"].startswith("NOT_EVALUATED")
    assert status["H4"].startswith("NOT_EVALUATED")
    assert status["best_baseline"] == "NOT_EVALUATED"
    assert status["executed_final_episode_count"] == 0
    assert status["failures_deleted"] is False


def test_every_d3_validation_episode_and_failure_is_retained() -> None:
    original = pd.read_parquet(ROOT / "results_phase_d" / "D3" / "validation_episode_summary.parquet")
    retained = pd.read_parquet(ROOT / "results_phase_d" / "D8" / "all_d3_validation_episode_metrics.parquet")
    failures = pd.read_parquet(ROOT / "results_phase_d" / "D8" / "all_failed_d3_episodes.parquet")
    assert len(retained) == len(original) == 120
    expected_failures = retained[retained["scientific_status"] != "success"]
    assert len(failures) == len(expected_failures)
    assert set(zip(failures["seed"], failures["scenario"])) == set(zip(expected_failures["seed"], expected_failures["scenario"]))
    assert not failures.empty


def test_not_evaluated_is_separate_and_figures_are_nonempty() -> None:
    manifest = pd.read_csv(ROOT / "results_phase_d" / "D7" / "SCENARIO_MANIFEST.csv")
    assert set(manifest["execution_status"]) == {"not_evaluated"}
    assert not (manifest["execution_status"].str.contains("failure")).any()
    catalog = pd.read_csv(ROOT / "results_phase_d" / "D8" / "FIGURE_CATALOG.csv")
    for filename in catalog["figure"]:
        path = ROOT / "figures_phase_d" / "D8" / filename
        assert path.stat().st_size > 10_000


def test_required_final_reports_are_well_formed() -> None:
    required = [
        "LOCKED_SCIENCE_AND_DECISIONS.md",
        "SUPPORTED_AND_UNSUPPORTED_CLAIMS.md",
        "DECISION_LOG.md",
        "THEORY_NOT_EVALUATED.md",
        "ORACLE_AND_CONTROLLER_NOT_EVALUATED.md",
        "FINAL_RESULTS_INTERPRETATION.md",
        "PAPER_OUTLINE.md",
    ]
    for filename in required:
        path = ROOT / "research_outputs_phase_d" / "final" / filename
        assert path.stat().st_size > 150
        text = path.read_text(encoding="utf-8")
        assert "write_text(" not in text
        assert 'encoding="utf-8"' not in text
