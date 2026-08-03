from __future__ import annotations

from dataclasses import fields, replace
import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction5_freq.models.terminal_window import (
    ORDERED_REASONS,
    TerminalWindowFlags,
    classify_terminal_window,
)
from direction5_freq.statistics.coverage_statistics import (
    one_sided_binomial_lower_bound,
)


REPO = Path(__file__).resolve().parents[2]


def test_every_terminal_predicate_is_mandatory_and_has_a_primary_reason() -> None:
    valid = TerminalWindowFlags(*([True] * 12))
    assert classify_terminal_window(valid) == (True, "INCLUDED", ())
    for item in fields(valid):
        invalid = replace(valid, **{item.name: False})
        included, primary, reasons = classify_terminal_window(invalid)
        assert not included
        assert primary == ORDERED_REASONS[item.name]
        assert reasons == (primary,)


def test_exact_finite_sample_lower_bound_is_not_empirical_coverage() -> None:
    lower = one_sided_binomial_lower_bound(60, 60, 0.95)
    assert 0.951 < lower < 0.952
    assert one_sided_binomial_lower_bound(0, 60, 0.95) == 0.0


def test_saved_windows_enforce_physics_domains_and_no_future_leakage() -> None:
    windows = pd.read_parquet(REPO / "results_phase_h/H4/WINDOW_LABELS.parquet")
    included = windows[windows.included]
    predicates = list(ORDERED_REASONS)
    assert len(included) == 7960
    assert included.classification.eq("SUSTAINABLE").all()
    assert included[predicates].all(axis=None)
    assert windows.no_future_leakage.all()
    physical = windows.split.eq("precontroller_physical_domain")
    assert (~windows.loc[physical, "included"]).all()
    assert windows.loc[physical, "primary_exclusion_reason"].eq(
        "DOMAIN_NOT_SUSTAINABLE"
    ).all()


def test_coverage_and_saved_sets_pass_each_plant_period_horizon() -> None:
    coverage = pd.read_csv(REPO / "results_phase_h/H4/COVERAGE_WITH_CONFIDENCE.csv")
    assert coverage.passed.all()
    assert coverage.samples.min() >= 174
    assert coverage.empirical_coverage.min() >= 0.95
    assert coverage.finite_sample_lower_bound.min() >= 0.95
    assert set(coverage.plant) == {"A", "B"}
    assert set(coverage.period_s) == {2.0, 4.0}
    assert set(coverage.horizon_steps) == {1, 2, 4, 6}
    global_set = np.load(
        REPO / "research_outputs_phase_h/03_MODEL/GLOBAL_PREDICTION_SET.npz"
    )
    local_set = np.load(
        REPO / "research_outputs_phase_h/03_MODEL/LOCAL_TERMINAL_SET.npz"
    )
    assert np.all(
        local_set["state_prediction_radii"]
        <= global_set["state_prediction_radii"] + 1e-12
    )
    assert not bool(local_set["repeated_load_accident_kicks"])


def test_h4_gate_records_repair_and_native_plant_b() -> None:
    progress = json.loads((REPO / "progress_phase_h/H4.json").read_text("utf-8"))
    assert progress["gate_passed"]
    assert progress["repairs_used"] == 1
    trajectories = pd.read_parquet(
        REPO / "results_phase_h/H4/TERMINAL_CALIBRATION_TRAJECTORIES.parquet"
    )
    assert trajectories.loc[trajectories.plant.eq("B"), "native_network"].all()
    assert trajectories.loc[
        trajectories.plant.eq("B"), "algebraic_power_balance_p99_pu"
    ].max() < 1e-6
