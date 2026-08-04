from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from direction5freq.evaluation.corrected_statistics import (
    corrected_metric_summary,
    hierarchical_bootstrap,
    paired_failure_rows,
    paired_failure_table,
    solver_denominator_audit,
)


REPO = Path(__file__).resolve().parents[2]


def _synthetic_rows() -> pd.DataFrame:
    rows = []
    for cell, seeds, proposed, baseline in (
        ("power", range(4), 8.0, 10.0),
        ("delay", range(20), 18.0, 20.0),
    ):
        for seed in seeds:
            scenario = f"{cell}-{seed}"
            for method, value in (("proposed", proposed), ("baseline", baseline)):
                rows.append({
                    "scenario_id": scenario,
                    "method": method,
                    "evaluation_status": "EVALUATED",
                    "physical_success": True,
                    "seed": seed,
                    "plant": "A",
                    "mechanism": cell,
                    "sg_tension": "low",
                    "period_s": 2.0,
                    "frequency_peak_hz": value,
                    "ace_iae_pu_s": value,
                    "tie_rms_pu": value,
                })
    return pd.DataFrame(rows)


def test_scenario_balanced_primary_metric_and_hierarchical_pairing() -> None:
    rows = paired_failure_rows(_synthetic_rows(), "proposed", "baseline")
    summary, bootstrap, pairs = corrected_metric_summary(
        rows, "proposed", "baseline", resamples=200, bootstrap_seed=17
    )
    peak = summary[(summary.metric == "frequency_peak_hz") & summary.primary_metric].iloc[0]
    assert np.isclose(peak.scenario_balanced_proposed_mean, 13.0)
    assert np.isclose(peak.scenario_balanced_baseline_mean, 15.0)
    assert np.isclose(peak.aggregate_mean_relative_improvement, 2.0 / 15.0)
    assert "diagnostic_only_mean_episode_relative_ratio" in summary.columns
    interval = bootstrap[(bootstrap.metric == "frequency_peak_hz") & (bootstrap.analysis == "both_success")].iloc[0]
    assert interval.relative_improvement_lower > 0.0
    direct = hierarchical_bootstrap(
        pairs[(pairs.metric == "frequency_peak_hz") & (pairs.analysis == "both_success")],
        resamples=200,
        random_seed=17,
    )
    assert direct.absolute_difference_lower > 0.0


def test_failure_table_keeps_physical_infeasibility_separate() -> None:
    frame = _synthetic_rows()
    mask = frame.scenario_id.eq("power-0")
    frame.loc[mask, "evaluation_status"] = "PHYSICALLY_INFEASIBLE_CERTIFIED"
    frame.loc[mask, "physical_success"] = False
    rows = paired_failure_rows(frame, "proposed", "baseline")
    table = paired_failure_table(rows)
    count = table[(table.scope == "ALL") & (table.category == "physically_infeasible")].scenarios.iloc[0]
    assert count == 1


def test_phase_i_solver_denominator_includes_fallback_attempts() -> None:
    i6 = REPO / "results_phase_i/I6"
    episodes = pd.read_parquet(i6 / "VALIDATION_EPISODES.parquet")
    normal = pd.read_parquet(i6 / "NORMAL1H_EPISODES.parquet")
    cycles = pd.read_parquet(i6 / "VALIDATION_CYCLES.parquet")
    audit = solver_denominator_audit(episodes, normal, cycles, "dcsv_mpc")
    values = dict(zip(audit.quantity, audit["count"]))
    assert values["omitted_backup_actions_in_phase_i_denominator"] == 712
    assert values["attempted_optimization_decisions"] == 20273
    assert values["inferred_raw_solver_invocations"] == 21097
    assert audit.unresolved_fraction_of_attempted_decisions.iloc[0] > 0.001


def test_phase_i_normal1h_anomaly_is_shared_and_was_not_quality_gated() -> None:
    normal = pd.read_parquet(REPO / "results_phase_i/I6/NORMAL1H_EPISODES.parquet")
    anomaly = normal[normal.scenario_id.eq("I6-N-02")]
    assert set(anomaly.method) == {"dcsv_mpc", "fixed_allocation_pi"}
    assert (anomaly.frequency_peak_hz > 2.0).all()
    source = (REPO / "scripts/phase_i/run_i6_validation.py").read_text("utf-8")
    assert "normal_episodes.groupby(\"method\").size().min() >= 6" in source
    assert "normal_episodes.frequency_peak_hz" not in source

