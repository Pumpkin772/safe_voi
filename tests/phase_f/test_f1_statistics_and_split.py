from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction1freq.evaluation.failure_aware_statistics import (
    aggregate_mean_improvement,
    paired_failure_counts,
)
from scripts.phase_f.run_f1_corrected_science import assign_frozen_e3_split


ROOT = Path(__file__).resolve().parents[2]


def test_aggregate_mean_ratio_is_not_mean_episode_ratio() -> None:
    baseline = np.array([1.0, 100.0])
    proposed = np.array([0.5, 90.0])
    result = aggregate_mean_improvement(baseline, proposed)
    mean_episode_ratio = np.mean(1.0 - proposed / baseline)
    assert np.isclose(result, 1.0 - proposed.mean() / baseline.mean())
    assert not np.isclose(result, mean_episode_ratio)


def test_not_evaluated_is_not_a_failure() -> None:
    baseline = pd.DataFrame({"physical_success": [True, False]}, index=["a", "b"])
    proposed = pd.DataFrame({"physical_success": [True, True]}, index=["a", "c"])
    counts = paired_failure_counts(baseline, proposed)
    assert counts == {
        "both_success": 1,
        "only_proposed_fails": 0,
        "only_baseline_fails": 0,
        "both_fail": 0,
        "not_evaluated": 2,
    }


def test_frozen_split_and_selection_do_not_use_legacy_validation() -> None:
    source = pd.read_parquet(
        ROOT / "results_phase_e" / "E3" / "full" / "E3_MATERIALITY_EPISODES.parquet"
    )
    split = assign_frozen_e3_split(source)
    assert (split[source.load_seed < 10] == "legacy_development").all()
    assert (split[source.load_seed >= 10] == "legacy_validation").all()
    selection = pd.read_csv(
        ROOT / "results_phase_f" / "F1" / "BASELINE_SELECTION_DEVELOPMENT_ONLY.csv"
    )
    assert not selection.validation_used_for_selection.any()
    assert selection.loc[selection.selected, "method"].item() == "fixed_allocation_pi"


def test_f1_claims_are_limited_and_gate_passes() -> None:
    progress = json.loads((ROOT / "progress_phase_f" / "F1.json").read_text())
    assert progress["gate_passed"] is True
    assert progress["mechanisms_passing"] >= 2
    assert progress["sg_tensions_passing"] >= 2
    assert progress["h2_status"].startswith("TESTED_PASSIVE_ESTIMATORS")
    assert progress["h3_status"] == "TESTED_ACTIVE_PROBE_NOT_SAFE"

