from __future__ import annotations

import hashlib
from itertools import product

import pandas as pd
import pytest

from d5freq.evaluation.phase6_analysis import (
    AGGREGATE_COLUMNS,
    EXPECTED_FINAL_EPISODE_COUNT,
    EXPECTED_FINAL_METHODS,
    EXPECTED_FINAL_SEEDS,
    EXPECTED_FINAL_TRUTH_CLASS,
    OVERALL_SCENARIO_ID,
    STATISTICAL_TEST_COLUMNS,
    analyze_phase6_tables,
    build_statistical_tests,
    validate_aggregate_output,
    validate_final_coverage,
    validate_phase6_inputs,
    write_phase6_analysis,
)
from d5freq.evaluation.results_schema import EpisodeResult, episode_results_frame


def _result(
    run_id: str,
    scenario: str,
    method: str,
    seed: int,
    *,
    freq_iae: float | None,
    catastrophic: bool = False,
    diagnostic: float | None = None,
    solve_time: float | None = None,
) -> EpisodeResult:
    if freq_iae is None:
        return EpisodeResult.failed(
            run_id=run_id,
            scenario_id=scenario,
            method=method,
            seed=seed,
            failure_stage="simulation",
            failure_type="SyntheticFailure",
            failure_message="retained test failure",
            catastrophic_not_recovered=True,
        )
    return EpisodeResult(
        run_id=run_id,
        scenario_id=scenario,
        method=method,
        seed=seed,
        run_completed=True,
        metrics_complete=True,
        freq_iae=freq_iae,
        max_abs_freq_hz=freq_iae / 10.0,
        catastrophic_safety_boundary=catastrophic,
        mode_accuracy=diagnostic,
        solver_attempt_count=None if solve_time is None else 2,
        solve_time_mean_s=solve_time,
    )


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = [
        _result("a-p", "A", "P", 1, freq_iae=2.0, diagnostic=0.8, solve_time=0.2),
        _result("a-b1", "A", "B1", 1, freq_iae=4.0, solve_time=0.1),
        _result("a-b2", "A", "B2", 1, freq_iae=3.0, solve_time=0.15),
        _result("a-o", "A", "B4", 1, freq_iae=1.0, solve_time=0.08),
        _result("b-p", "B", "P", 1, freq_iae=12.0, diagnostic=0.7, solve_time=0.3),
        _result("b-b1", "B", "B1", 1, freq_iae=14.0, solve_time=0.1),
        _result("b-b2", "B", "B2", 1, freq_iae=13.0, solve_time=0.2),
        _result("b-o", "B", "B4", 1, freq_iae=10.0, solve_time=0.09),
        _result("b-p-fail", "B", "P", 2, freq_iae=None),
        _result("b-b1-2", "B", "B1", 2, freq_iae=15.0, solve_time=0.12),
        _result("b-b2-2", "B", "B2", 2, freq_iae=14.0, solve_time=0.22),
        _result("b-o-2", "B", "B4", 2, freq_iae=11.0, solve_time=0.10),
    ]
    metrics = episode_results_frame(rows)
    ledger = metrics.copy()
    ledger["stage"] = "smoke"
    ledger["truth_class"] = ledger["scenario_id"].map({"A": "known", "B": "ood"})
    ledger["solver_tier"] = "FINAL"
    ledger.loc[ledger["run_id"] == "b-b2-2", "solver_tier"] = "DEBUG"
    ledger["per_run_envelope_sha256"] = [f"sha-{index}" for index in range(len(ledger))]
    return metrics, ledger


def test_analysis_retains_failures_pairs_oracle_by_scenario_and_filters_outputs() -> None:
    metrics, ledger = _inputs()
    tables = analyze_phase6_tables(
        metrics,
        ledger,
        require_complete_final=False,
        analysis_seed=7,
        n_resamples=100,
    )

    attached = tables.episode_metrics_with_oracle_regret.set_index("run_id")
    assert attached.loc["a-p", "oracle_regret"] == 1.0
    assert attached.loc["b-p", "oracle_regret"] == 2.0
    assert pd.isna(attached.loc["b-p-fail", "oracle_regret"])
    assert len(attached) == len(metrics)

    summary = tables.summary_metrics
    overall_p_iae = summary.loc[
        (summary["aggregation_scope"] == "overall_episode")
        & (summary["method"] == "P")
        & (summary["metric"] == "freq_iae")
    ].iloc[0]
    assert overall_p_iae["scenario_id"] == OVERALL_SCENARIO_ID
    assert overall_p_iae["statistical_unit"] == "episode"
    assert overall_p_iae["n_total"] == 3
    assert overall_p_iae["n_observed"] == 2
    assert overall_p_iae["n_missing"] == 1
    assert overall_p_iae["n_run_incomplete"] == 1

    diagnostic_methods = set(tables.diagnostic_metrics["method"])
    assert diagnostic_methods == {"P"}
    delay_rows = tables.diagnostic_metrics.loc[
        tables.diagnostic_metrics["metric"] == "detection_delay_s"
    ]
    assert not delay_rows.empty
    assert set(delay_rows["qualification"]) == {
        "runtime_diagnosis_only;B4_truth_informed_excluded;"
        "detection_delays_detected_events_only;"
        "censoring_in_companion_count_and_time_metrics"
    }
    assert "B4" not in diagnostic_methods

    solver = tables.solver_metrics
    assert "B4" in set(solver["method"])
    b2_overall = solver.loc[
        (solver["method"] == "B2")
        & (solver["aggregation_scope"] == "overall_episode")
        & (solver["metric"] == "solve_time_mean_s")
    ].iloc[0]
    assert b2_overall["n_total"] == 2
    assert b2_overall["n_observed"] == 2
    # The DEBUG row is excluded from solver claims, leaving only seed 1 in A
    # and seed 1 in B.  Its episode remains present in all other outputs.
    assert b2_overall["mean"] == pytest.approx((0.15 + 0.2) / 2.0)


def test_input_validation_rejects_duplicate_triples_and_a_dropped_failure_row() -> None:
    metrics, ledger = _inputs()
    duplicate = metrics.iloc[[0]].copy()
    duplicate.loc[:, "run_id"] = "different-run-id"
    duplicated_metrics = pd.concat([metrics, duplicate], ignore_index=True)
    with pytest.raises(ValueError, match="exactly one row per"):
        validate_phase6_inputs(
            duplicated_metrics, ledger, require_complete_final=False
        )

    dropped_failure = metrics.loc[metrics["run_id"] != "b-p-fail"].copy()
    with pytest.raises(ValueError, match="dropped failure row"):
        validate_phase6_inputs(
            dropped_failure, ledger, require_complete_final=False
        )


def test_frozen_final_coverage_requires_all_8280_method_scenario_seed_rows() -> None:
    records = []
    for scenario, seeds in EXPECTED_FINAL_SEEDS.items():
        for method, seed in product(EXPECTED_FINAL_METHODS, seeds):
            records.append(
                {
                    "method": method,
                    "scenario_id": scenario,
                    "seed": seed,
                    "stage": "final",
                    "truth_class": EXPECTED_FINAL_TRUTH_CLASS[scenario],
                    "solver_tier": "FINAL",
                }
            )
    ledger = pd.DataFrame.from_records(records)
    assert len(ledger) == EXPECTED_FINAL_EPISODE_COUNT
    validate_final_coverage(ledger)

    with pytest.raises(ValueError, match="8280"):
        validate_final_coverage(ledger.iloc[:-1].copy())


def test_pair_audit_never_crosses_scenarios_and_reports_missing_partner() -> None:
    metrics, ledger = _inputs()
    joined = validate_phase6_inputs(
        metrics, ledger, require_complete_final=False
    ).joined
    joined.loc[joined["run_id"] == "a-p", "freq_iae"] = 20.0
    # Remove B1 only for B/seed 2; A/seed 2 does not exist and cannot be used
    # as a cross-scenario substitute for the missing partner.
    joined = joined.loc[joined["run_id"] != "b-b1-2"].copy()
    tests = build_statistical_tests(joined, analysis_seed=4, n_resamples=100)
    overall = tests.loc[
        (tests["metric"] == "freq_iae")
        & (tests["reference_method"] == "B1")
        & (tests["aggregation_scope"] == "overall_episode")
    ].iloc[0]
    assert overall["pairing_keys"] == "scenario_id+seed"
    assert overall["matched_pair_count"] == 2
    assert overall["unmatched_method_count"] == 1
    assert overall["unmatched_reference_count"] == 0
    assert overall["paired_observed_count"] == 2
    b2_overall = tests.loc[
        (tests["metric"] == "freq_iae")
        & (tests["reference_method"] == "B2")
        & (tests["aggregation_scope"] == "overall_episode")
    ].iloc[0]
    assert b2_overall["matched_pair_count"] == 3
    assert b2_overall["paired_observed_count"] == 2
    assert b2_overall["missing_metric_pair_count"] == 1


def test_catastrophic_mcnemar_is_exact_and_holm_is_applied_by_family() -> None:
    rows: list[EpisodeResult] = []
    p_failures = [False, False, False, False, True, True]
    b1_failures = [True, True, True, True, True, False]
    b2_failures = [True, True, False, False, True, False]
    for seed, (p_bad, b1_bad, b2_bad) in enumerate(
        zip(p_failures, b1_failures, b2_failures, strict=True), start=1
    ):
        for method, bad, cost in (
            ("P", p_bad, 1.0),
            ("B1", b1_bad, 2.0),
            ("B2", b2_bad, 3.0),
        ):
            rows.append(
                _result(
                    f"{method}-{seed}",
                    "S",
                    method,
                    seed,
                    freq_iae=cost,
                    catastrophic=bad,
                )
            )
    frame = episode_results_frame(rows)
    frame["truth_class"] = "known"
    frame["solver_tier"] = "FINAL"
    tests = build_statistical_tests(frame, analysis_seed=3, n_resamples=100)
    mcnemar = tests.loc[
        (tests["test_type"] == "exact_mcnemar")
        & (tests["aggregation_scope"] == "scenario")
    ].set_index("reference_method")
    assert bool(mcnemar.loc["B1", "test_exact"])
    assert mcnemar.loc["B1", "mcnemar_method_false_reference_true"] == 4
    assert mcnemar.loc["B1", "mcnemar_method_true_reference_false"] == 1
    assert mcnemar.loc["B1", "mcnemar_discordant_count"] == 5
    assert mcnemar.loc["B1", "pvalue_holm"] >= mcnemar.loc["B1", "pvalue_raw"]
    assert mcnemar.loc["B1", "holm_family_size"] == 2


def test_oracle_standard_diagnostics_are_rejected_and_csv_schemas_are_exact(
    tmp_path,
) -> None:
    metrics, ledger = _inputs()
    metrics.loc[metrics["method"] == "B4", "mode_accuracy"] = 1.0
    ledger.loc[ledger["method"] == "B4", "mode_accuracy"] = 1.0
    with pytest.raises(ValueError, match="truth-informed Oracle"):
        analyze_phase6_tables(
            metrics,
            ledger,
            require_complete_final=False,
            n_resamples=10,
        )

    metrics, ledger = _inputs()
    lock_path = tmp_path / "protocol_lock.json"
    lock_path.write_text('{"locked":true}\n', encoding="utf-8")
    ledger["final_protocol_lock_file_sha256"] = hashlib.sha256(
        lock_path.read_bytes()
    ).hexdigest()
    metrics_path = tmp_path / "per_episode_metrics.csv"
    ledger_path = tmp_path / "experiment_ledger.csv"
    metrics.to_csv(metrics_path, index=False)
    ledger.to_csv(ledger_path, index=False)
    artifacts = write_phase6_analysis(
        metrics_path,
        ledger_path,
        tmp_path / "review",
        require_complete_final=False,
        analysis_seed=9,
        n_resamples=50,
        protocol_lock_path=lock_path,
    )
    assert tuple(pd.read_csv(artifacts.summary_metrics_path).columns) == AGGREGATE_COLUMNS
    assert (
        tuple(pd.read_csv(artifacts.statistical_tests_path).columns)
        == STATISTICAL_TEST_COLUMNS
    )
    assert artifacts.diagnostic_metrics_path.name == "diagnostic_metrics.csv"
    assert artifacts.solver_metrics_path.name == "solver_metrics.csv"
    assert artifacts.per_episode_metrics_path.name == "per_episode_metrics.csv"
    assert artifacts.experiment_ledger_path.name == "experiment_ledger.csv"
    assert artifacts.oracle_pairing_audit_path.name == "oracle_pairing_audit.csv"
    assert artifacts.protocol_lock_path is not None
    assert artifacts.protocol_lock_path.read_bytes() == lock_path.read_bytes()
    review_metrics = pd.read_csv(artifacts.per_episode_metrics_path)
    review_ledger = pd.read_csv(artifacts.experiment_ledger_path)
    assert set(review_metrics["run_id"]) == set(metrics["run_id"])
    assert set(review_ledger["run_id"]) == set(ledger["run_id"])
    paired = review_metrics.loc[
        review_metrics["run_id"].isin(("a-p", "a-o")),
        ["run_id", "oracle_regret"],
    ].set_index("run_id")
    assert paired.loc["a-p", "oracle_regret"] == 1.0
    assert paired.loc["a-o", "oracle_regret"] == 0.0
    ledger_regret = review_ledger.set_index("run_id")["oracle_regret"]
    assert ledger_regret.loc["a-p"] == 1.0
    assert ledger_regret.loc["a-o"] == 0.0

    reordered = artifacts.tables.summary_metrics.loc[
        :, list(reversed(AGGREGATE_COLUMNS))
    ]
    with pytest.raises(ValueError, match="exactly match"):
        validate_aggregate_output(reordered, metric_family="summary")


def test_pre_controller_failure_is_retained_but_excluded_from_solver_claims() -> None:
    metrics, ledger = _inputs()
    ledger["eligible_for_final_solver_claims"] = pd.Series(
        [True] * len(ledger), dtype=object
    )
    ledger["controller_metadata_status"] = "verified"
    failed = ledger["run_id"] == "b-p-fail"
    ledger.loc[failed, "eligible_for_final_solver_claims"] = None
    ledger.loc[failed, "controller_metadata_status"] = (
        "unavailable_pre_controller_failure"
    )

    tables = analyze_phase6_tables(
        metrics,
        ledger,
        require_complete_final=False,
        analysis_seed=17,
        n_resamples=20,
    )
    p_summary = tables.summary_metrics.loc[
        (tables.summary_metrics["aggregation_scope"] == "overall_episode")
        & (tables.summary_metrics["method"] == "P")
        & (tables.summary_metrics["metric"] == "freq_iae")
    ].iloc[0]
    assert p_summary["n_total"] == 3
    p_solver = tables.solver_metrics.loc[
        (tables.solver_metrics["aggregation_scope"] == "overall_episode")
        & (tables.solver_metrics["method"] == "P")
        & (tables.solver_metrics["metric"] == "solve_time_mean_s")
    ].iloc[0]
    assert p_solver["n_total"] == 2

    invalid = ledger.copy()
    invalid.loc[failed, "controller_metadata_status"] = "verified"
    with pytest.raises(TypeError, match="may be missing only"):
        analyze_phase6_tables(
            metrics,
            invalid,
            require_complete_final=False,
            n_resamples=10,
        )
