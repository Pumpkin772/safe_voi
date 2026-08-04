from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "research_outputs_closure/01_MECHANISM"


def test_fallback_root_causes_cover_every_fallback() -> None:
    progress = json.loads((REPO / "progress_closure/C1.json").read_text("utf-8"))
    causes = pd.read_csv(OUT / "FALLBACK_ROOT_CAUSE_SUMMARY.csv")
    assert progress["status"] == "PASS"
    assert progress["fallback_calls"] == 1021
    assert causes.fallback_calls.sum() == 1021
    assert progress["fallback_explained_fraction"] == 1.0
    assert set(causes.root_cause) == {"PRIMARY_AND_RESTORATION_MATHEMATICAL_INFEASIBILITY"}


def test_online_surplus_is_empirically_negligible() -> None:
    surplus = pd.read_csv(OUT / "SURPLUS_USAGE.csv").iloc[0]
    assert surplus["scope"] == "ALL"
    assert surplus.active_calls == 2
    assert surplus.calls == 22392
    assert surplus.active_fraction < 0.0001


def test_information_value_layers_are_kept_separate() -> None:
    detail = pd.read_parquet(OUT / "INFORMATION_VALUE_DECOMPOSITION.parquet")
    required = {
        "contract_value", "causal_online_value", "model_adaptive_value",
        "perfect_capability_value", "perfect_information_improvement",
        "causal_online_improvement", "perfect_minus_online_value_gap",
    }
    assert required.issubset(detail.columns)
    assert detail.scenario_id.nunique() == 24
    assert set(detail.metric) == {"frequency_peak_hz", "ace_iae_pu_s", "tie_rms_pu"}


def test_c1_is_analysis_only_and_final_seeds_remain_unused() -> None:
    progress = json.loads((REPO / "progress_closure/C1.json").read_text("utf-8"))
    assert progress["method_or_threshold_changed"] is False
    assert progress["final_seeds_consumed"] is False
    assert progress["performance_rows_explained_fraction"] >= 0.90
