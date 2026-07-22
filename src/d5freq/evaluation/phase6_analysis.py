"""Strict Phase-6 aggregation and paired statistical analysis.

The canonical ``per_episode_metrics.csv`` remains the statistical source of
truth.  Every attempted episode, including failed episodes, contributes one
row to ``n_total``.  Missing metrics are never imputed and catastrophic
failures are compared as paired binary outcomes.

The overall aggregation is deliberately named ``overall_episode``: its unit
is still an episode.  It is a descriptive episode-weighted aggregation, not a
claim that repeated seeds or scenarios are independent experimental units.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from numbers import Integral, Real
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from d5freq.evaluation.results_schema import (
    EPISODE_RESULT_COLUMNS,
    EpisodeResult,
    validate_episode_frame,
)
from d5freq.evaluation.statistics import (
    attach_oracle_regret,
    bootstrap_mean_ci,
    exact_mcnemar,
    holm_adjust,
    paired_bootstrap_mean_ci,
    sign_flip_permutation_test,
)


PHASE6_AGGREGATE_SCHEMA_VERSION = "d5freq.phase6.aggregate.v1"
PHASE6_STATISTICAL_TEST_SCHEMA_VERSION = "d5freq.phase6.statistical-tests.v1"
EXPECTED_FINAL_EPISODE_COUNT = 8_280
DEFAULT_BOOTSTRAP_RESAMPLES = 10_000
DEFAULT_ANALYSIS_SEED = 20260723
OVERALL_SCENARIO_ID = "__overall__"

EXPECTED_FINAL_METHODS: tuple[str, ...] = (
    "B0",
    "B1",
    "B2",
    "B3",
    "B4",
    "P",
    "no-worst",
    "no-OOD",
    "no-tightening",
    "fixed-K4-unlabeled",
    "labeled-library",
    "no-transition-prior",
)

_KNOWN_FINAL_SCENARIOS: tuple[str, ...] = (
    "S0_nominal_stochastic",
    "S1_step_pos_002",
    "S1_step_neg_002",
    "S1_step_pos_004",
    "S1_step_neg_004",
    "S1_step_pos_006",
    "S1_step_neg_006",
    "S1_step_pos_008",
    "S1_step_neg_008",
    "S2_sluggish_switch_050",
    "S2_sluggish_switch_060",
    "S2_sluggish_switch_090",
    "S3_derated_coincident",
    "S4_unavailable_coincident",
    "S5_multi_switch_stochastic",
    "S6_sluggish_coincident_low_noise",
    "S6_sluggish_coincident_medium_noise",
    "S6_sluggish_coincident_high_noise",
)
_OOD_FINAL_SCENARIOS: tuple[str, ...] = (
    "S7_ood_asymmetric_limit",
    "S8_ood_time_varying_delay",
)
_EXTREME_FINAL_SCENARIOS: tuple[str, ...] = (
    "S9_compound_unavailable_double_step",
)

EXPECTED_FINAL_TRUTH_CLASS: Mapping[str, str] = {
    **{scenario: "known" for scenario in _KNOWN_FINAL_SCENARIOS},
    **{scenario: "ood" for scenario in _OOD_FINAL_SCENARIOS},
    **{scenario: "extreme_known" for scenario in _EXTREME_FINAL_SCENARIOS},
}
EXPECTED_FINAL_SEEDS: Mapping[str, tuple[int, ...]] = {
    **{
        scenario: tuple(range(1000, 1030))
        for scenario in _KNOWN_FINAL_SCENARIOS
    },
    **{
        scenario: tuple(range(1000, 1050))
        for scenario in (*_OOD_FINAL_SCENARIOS, *_EXTREME_FINAL_SCENARIOS)
    },
}

RUNTIME_DIAGNOSTIC_METHODS: frozenset[str] = frozenset(
    {
        "B3",
        "P",
        "no-worst",
        "no-OOD",
        "no-tightening",
        "fixed-K4-unlabeled",
        "labeled-library",
        "no-transition-prior",
    }
)
NON_RUNTIME_DIAGNOSTIC_METHODS: frozenset[str] = frozenset(
    {"B0", "B1", "B2", "B4"}
)
SOLVER_APPLICABLE_METHODS: frozenset[str] = frozenset(
    set(EXPECTED_FINAL_METHODS) - {"B0"}
)

CONTROL_PERFORMANCE_METRICS: tuple[str, ...] = (
    "max_abs_freq_hz",
    "nadir_delta_hz",
    "zenith_delta_hz",
    "nadir_hz",
    "zenith_hz",
    "max_abs_rocof_hz_s",
    "freq_iae",
    "freq_ise",
    "settling_time_s",
    "freq_violation_duration_s",
    "rocof_violation_duration_s",
    "constraint_violation_count",
    "violation_duration_s",
    "sg_mileage",
    "ibr_mileage",
    "ibr_tracking_error",
    "sg_abs_energy_pu_s",
    "ibr_abs_energy_pu_s",
    "peak_abs_sg_command_pu",
    "peak_abs_ibr_command_pu",
    "responsibility_transfer_time_s",
    "fallback_duration_s",
    "sg_command_violation_count",
    "sg_command_violation_duration_s",
    "max_contiguous_sg_command_violation_s",
    "ibr_command_violation_count",
    "ibr_command_violation_duration_s",
    "max_contiguous_ibr_command_violation_s",
    "oracle_regret",
    "wall_time_s",
)

CENSORING_AUDIT_METRICS: tuple[str, ...] = (
    "settling_censoring_time_s",
    "responsibility_transfer_censoring_time_s",
)

STATUS_METRICS: tuple[str, ...] = (
    "run_completed",
    "metrics_complete",
    "scientific_success",
    "catastrophic_failure",
    "catastrophic_safety_boundary",
    "catastrophic_solver_without_fallback",
    "catastrophic_nan_detected",
    "catastrophic_persistent_command_violation",
    "catastrophic_not_recovered",
)

SUMMARY_METRICS: tuple[str, ...] = (
    *STATUS_METRICS,
    *CONTROL_PERFORMANCE_METRICS,
    *CENSORING_AUDIT_METRICS,
)

DIAGNOSTIC_METRICS: tuple[str, ...] = (
    "mode_accuracy",
    "macro_f1",
    "detection_delay_s",
    "detection_event_count",
    "detection_censored_count",
    "detection_censoring_time_s",
    "false_alarm_rate",
    "brier",
    "nll",
    "ece",
    "ood_auroc",
    "ood_auprc",
    "ood_detected",
    "ood_detection_delay_s",
    "ood_detection_event_count",
    "ood_detection_censored_count",
    "ood_detection_censoring_time_s",
    "diagnostic_risk_iae",
)

SOLVER_METRICS: tuple[str, ...] = (
    "solver_attempt_count",
    "solve_time_mean_s",
    "solve_time_p95_s",
    "solve_time_max_s",
    "solver_fail_count",
    "solver_timeout_count",
    "solver_timeout_rate",
    "solver_infeasible_count",
    "solver_infeasible_rate",
    "solver_inaccurate_count",
    "solver_inaccurate_rate",
    "max_freq_slack_hz",
    "max_rocof_slack_hz_s",
    "max_power_slack_pu",
)

PAIRED_CONTINUOUS_METRICS: tuple[str, ...] = (
    *CONTROL_PERFORMANCE_METRICS,
    *SOLVER_METRICS,
)

_CENSOR_COLUMN_BY_METRIC: Mapping[str, str] = {
    "settling_time_s": "settling_censored",
    "responsibility_transfer_time_s": "responsibility_transfer_censored",
}

AGGREGATE_COLUMNS: tuple[str, ...] = (
    "schema_version",
    "metric_family",
    "aggregation_scope",
    "scenario_id",
    "truth_class",
    "method",
    "metric",
    "qualification",
    "statistical_unit",
    "n_total",
    "n_observed",
    "n_missing",
    "n_run_incomplete",
    "n_scientific_failure",
    "n_censored",
    "mean",
    "median",
    "std",
    "q05",
    "q95",
    "ci95_low",
    "ci95_high",
    "confidence_level",
    "bootstrap_resamples",
    "bootstrap_seed",
)
SUMMARY_METRICS_COLUMNS = AGGREGATE_COLUMNS
DIAGNOSTIC_METRICS_COLUMNS = AGGREGATE_COLUMNS
SOLVER_METRICS_COLUMNS = AGGREGATE_COLUMNS

STATISTICAL_TEST_COLUMNS: tuple[str, ...] = (
    "schema_version",
    "holm_family_id",
    "aggregation_scope",
    "scenario_id",
    "truth_class",
    "metric",
    "test_type",
    "method",
    "reference_method",
    "difference_direction",
    "pairing_keys",
    "statistical_unit",
    "method_n_total",
    "reference_n_total",
    "key_union_count",
    "matched_pair_count",
    "paired_observed_count",
    "missing_metric_pair_count",
    "unmatched_method_count",
    "unmatched_reference_count",
    "mean_difference",
    "median_difference",
    "std_difference",
    "q05_difference",
    "q95_difference",
    "ci95_low",
    "ci95_high",
    "confidence_level",
    "bootstrap_resamples",
    "bootstrap_seed",
    "test_statistic",
    "pvalue_raw",
    "test_resamples",
    "test_exact",
    "mcnemar_both_false",
    "mcnemar_method_false_reference_true",
    "mcnemar_method_true_reference_false",
    "mcnemar_both_true",
    "mcnemar_discordant_count",
    "pvalue_holm",
    "reject_holm_0_05",
    "holm_family_size",
)


@dataclass(frozen=True, slots=True)
class ValidatedPhase6Inputs:
    episode_metrics: pd.DataFrame
    experiment_ledger: pd.DataFrame
    joined: pd.DataFrame
    failure_row_count: int


@dataclass(frozen=True, slots=True)
class Phase6AnalysisTables:
    episode_metrics_with_oracle_regret: pd.DataFrame
    oracle_pairing_audit: pd.DataFrame
    summary_metrics: pd.DataFrame
    statistical_tests: pd.DataFrame
    diagnostic_metrics: pd.DataFrame
    solver_metrics: pd.DataFrame


@dataclass(frozen=True, slots=True)
class Phase6AnalysisArtifacts:
    tables: Phase6AnalysisTables
    per_episode_metrics_path: Path
    experiment_ledger_path: Path
    summary_metrics_path: Path
    statistical_tests_path: Path
    diagnostic_metrics_path: Path
    solver_metrics_path: Path
    oracle_pairing_audit_path: Path
    protocol_lock_path: Path | None


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], name: str) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{name} must be a pandas DataFrame")
    if frame.columns.duplicated().any():
        duplicates = frame.columns[frame.columns.duplicated()].tolist()
        raise ValueError(f"{name} has duplicate columns: {duplicates!r}")
    missing = tuple(column for column in columns if column not in frame.columns)
    if missing:
        raise ValueError(f"{name} is missing columns: {missing!r}")


def _normalize_episode_rows(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for _, raw in frame.loc[:, EPISODE_RESULT_COLUMNS].iterrows():
        payload = {
            column: (None if pd.isna(value) else value)
            for column, value in raw.items()
        }
        result = EpisodeResult(**payload)
        rows[result.run_id] = result.to_row()
    return rows


def _strict_boolean(value: object, name: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{name} must contain booleans")
    return bool(value)


def _solver_eligibility_mask(frame: pd.DataFrame) -> np.ndarray:
    """Return the audited eligibility mask for FINAL-solver claims.

    A missing value is allowed only when orchestration failed before a
    controller existed, in which case there is no controller/solver execution
    to qualify.  The episode remains in the canonical result and summary
    tables; it is excluded only from solver-specific claims.
    """

    if "eligible_for_final_solver_claims" not in frame.columns:
        return np.ones(len(frame), dtype=np.bool_)
    has_status = "controller_metadata_status" in frame.columns
    values = frame["eligible_for_final_solver_claims"].tolist()
    statuses = (
        frame["controller_metadata_status"].tolist()
        if has_status
        else [None] * len(frame)
    )
    result = np.empty(len(frame), dtype=np.bool_)
    for index, (value, status) in enumerate(zip(values, statuses, strict=True)):
        if pd.isna(value):
            if status != "unavailable_pre_controller_failure":
                raise TypeError(
                    "eligible_for_final_solver_claims may be missing only for "
                    "controller_metadata_status="
                    "'unavailable_pre_controller_failure'"
                )
            result[index] = False
            continue
        if status == "unavailable_pre_controller_failure":
            raise ValueError(
                "pre-controller failure metadata cannot claim solver eligibility"
            )
        result[index] = _strict_boolean(
            value, "eligible_for_final_solver_claims"
        )
    return result


def _validate_unique_episode_keys(frame: pd.DataFrame, name: str) -> None:
    duplicated = frame.duplicated(
        subset=["method", "scenario_id", "seed"], keep=False
    )
    if duplicated.any():
        keys = frame.loc[
            duplicated, ["method", "scenario_id", "seed", "run_id"]
        ].to_dict("records")
        raise ValueError(
            f"{name} requires exactly one row per (method, scenario_id, seed): "
            f"{keys!r}"
        )


def validate_final_coverage(ledger: pd.DataFrame) -> None:
    """Validate the frozen 8,280-row Phase-6 final Cartesian run plan."""

    _require_columns(
        ledger,
        ("method", "scenario_id", "seed", "stage", "truth_class", "solver_tier"),
        "experiment_ledger",
    )
    if len(ledger) != EXPECTED_FINAL_EPISODE_COUNT:
        raise ValueError(
            "final experiment ledger must contain exactly "
            f"{EXPECTED_FINAL_EPISODE_COUNT} rows; found {len(ledger)}"
        )
    methods = set(ledger["method"].tolist())
    if methods != set(EXPECTED_FINAL_METHODS):
        raise ValueError("final method coverage differs from the frozen 12 methods")
    scenarios = set(ledger["scenario_id"].tolist())
    if scenarios != set(EXPECTED_FINAL_SEEDS):
        raise ValueError("final scenario coverage differs from the frozen 21 variants")
    if set(ledger["stage"].tolist()) != {"final"}:
        raise ValueError("complete final analysis accepts stage='final' rows only")
    if {str(value).upper() for value in ledger["solver_tier"].tolist()} != {"FINAL"}:
        raise ValueError("complete final analysis requires FINAL solver tier rows only")

    for scenario, expected_seeds in EXPECTED_FINAL_SEEDS.items():
        scenario_rows = ledger.loc[ledger["scenario_id"] == scenario]
        truth_classes = set(scenario_rows["truth_class"].tolist())
        if truth_classes != {EXPECTED_FINAL_TRUTH_CLASS[scenario]}:
            raise ValueError(f"truth_class mismatch for final scenario {scenario!r}")
        expected = set(expected_seeds)
        for method in EXPECTED_FINAL_METHODS:
            observed_rows = scenario_rows.loc[scenario_rows["method"] == method]
            observed = set(int(seed) for seed in observed_rows["seed"].tolist())
            if len(observed_rows) != len(expected_seeds) or observed != expected:
                missing = sorted(expected - observed)
                extra = sorted(observed - expected)
                raise ValueError(
                    "final seed coverage mismatch for "
                    f"method={method!r}, scenario={scenario!r}; "
                    f"missing={missing!r}, extra={extra!r}"
                )


def validate_phase6_inputs(
    episode_metrics: pd.DataFrame,
    experiment_ledger: pd.DataFrame,
    *,
    require_complete_final: bool = True,
) -> ValidatedPhase6Inputs:
    """Validate canonical episode and ledger CSV contents without dropping rows."""

    validate_episode_frame(episode_metrics, exact_columns=True)
    _require_columns(
        experiment_ledger,
        (
            *EPISODE_RESULT_COLUMNS,
            "stage",
            "truth_class",
            "solver_tier",
            "per_run_envelope_sha256",
        ),
        "experiment_ledger",
    )
    validate_episode_frame(
        experiment_ledger.loc[:, EPISODE_RESULT_COLUMNS], exact_columns=True
    )
    _validate_unique_episode_keys(episode_metrics, "per_episode_metrics")
    _validate_unique_episode_keys(experiment_ledger, "experiment_ledger")

    metrics_by_run = _normalize_episode_rows(episode_metrics)
    ledger_by_run = _normalize_episode_rows(experiment_ledger)
    if set(metrics_by_run) != set(ledger_by_run):
        missing_metrics = sorted(set(ledger_by_run) - set(metrics_by_run))
        missing_ledger = sorted(set(metrics_by_run) - set(ledger_by_run))
        raise ValueError(
            "episode/ledger run_id sets differ; this can indicate a dropped failure row; "
            f"missing_metrics={missing_metrics!r}, missing_ledger={missing_ledger!r}"
        )
    mismatched = [
        run_id
        for run_id in sorted(metrics_by_run)
        if metrics_by_run[run_id] != ledger_by_run[run_id]
    ]
    if mismatched:
        raise ValueError(
            "episode rows differ between canonical metrics and ledger for run_id(s): "
            f"{mismatched!r}"
        )

    if require_complete_final:
        validate_final_coverage(experiment_ledger)

    metadata_columns = ["run_id", "stage", "truth_class", "solver_tier"]
    if "eligible_for_final_solver_claims" in experiment_ledger.columns:
        metadata_columns.append("eligible_for_final_solver_claims")
        if "controller_metadata_status" in experiment_ledger.columns:
            metadata_columns.append("controller_metadata_status")
    metadata = experiment_ledger.loc[:, metadata_columns].copy()
    joined = episode_metrics.merge(
        metadata,
        on="run_id",
        how="left",
        validate="one_to_one",
        sort=False,
    )
    if len(joined) != len(episode_metrics):
        raise RuntimeError("one-to-one metadata join changed the episode row count")
    for scenario, group in joined.groupby("scenario_id", sort=False):
        truth_classes = group["truth_class"].dropna().unique().tolist()
        if len(truth_classes) != 1:
            raise ValueError(
                f"scenario {scenario!r} must have exactly one ledger truth_class"
            )
    failure_count = int((~joined["run_completed"].astype(bool)).sum())
    return ValidatedPhase6Inputs(
        episode_metrics=episode_metrics.copy(),
        experiment_ledger=experiment_ledger.copy(),
        joined=joined,
        failure_row_count=failure_count,
    )


def _analysis_seed(base_seed: int, *parts: object) -> int:
    if isinstance(base_seed, (bool, np.bool_)) or not isinstance(base_seed, Integral):
        raise TypeError("analysis_seed must be an integer")
    if int(base_seed) < 0:
        raise ValueError("analysis_seed must be non-negative")
    material = "\x1f".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(material).digest()
    offset = int.from_bytes(digest[:8], "big")
    return int((int(base_seed) + offset) % np.iinfo(np.uint32).max)


def _positive_resamples(value: object) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError("n_resamples must be an integer")
    normalized = int(value)
    if normalized <= 0:
        raise ValueError("n_resamples must be strictly positive")
    return normalized


def _numeric_values(series: pd.Series, name: str) -> tuple[np.ndarray, np.ndarray]:
    values = np.full(len(series), np.nan, dtype=np.float64)
    observed = np.zeros(len(series), dtype=np.bool_)
    for index, raw in enumerate(series.tolist()):
        if pd.isna(raw):
            continue
        if isinstance(raw, (bool, np.bool_)):
            values[index] = float(bool(raw))
            observed[index] = True
            continue
        if not isinstance(raw, Real):
            raise TypeError(f"{name} must contain numeric, boolean, or missing values")
        normalized = float(raw)
        if not math.isfinite(normalized):
            raise ValueError(f"{name} contains a non-finite non-missing value")
        values[index] = normalized
        observed[index] = True
    return values, observed


def _bool_mask(series: pd.Series, name: str, *, missing_value: bool) -> np.ndarray:
    result = np.empty(len(series), dtype=np.bool_)
    for index, raw in enumerate(series.tolist()):
        if pd.isna(raw):
            result[index] = missing_value
        else:
            result[index] = _strict_boolean(raw, name)
    return result


def _truth_class(group: pd.DataFrame) -> str:
    values = sorted(set(str(value) for value in group["truth_class"].tolist()))
    return values[0] if len(values) == 1 else "mixed"


def _descriptive_statistics(values: np.ndarray) -> dict[str, float | None]:
    if not values.size:
        return {
            "mean": None,
            "median": None,
            "std": None,
            "q05": None,
            "q95": None,
        }
    return {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "std": None if values.size < 2 else float(np.std(values, ddof=1)),
        "q05": float(np.quantile(values, 0.05)),
        "q95": float(np.quantile(values, 0.95)),
    }


def _aggregate_row(
    group: pd.DataFrame,
    *,
    metric: str,
    metric_family: str,
    aggregation_scope: str,
    scenario_id: str,
    method: str,
    qualification: str,
    analysis_seed: int,
    n_resamples: int,
) -> dict[str, Any]:
    values, observed = _numeric_values(group[metric], metric)
    censored = np.zeros(len(group), dtype=np.bool_)
    censor_column = _CENSOR_COLUMN_BY_METRIC.get(metric)
    if censor_column is not None:
        censored = _bool_mask(group[censor_column], censor_column, missing_value=False)
        if np.any(censored & observed):
            raise ValueError(
                f"censored rows for {metric!r} must keep the metric missing"
            )
        observed &= ~censored
    retained = values[observed]
    seed = _analysis_seed(
        analysis_seed,
        "aggregate",
        metric_family,
        aggregation_scope,
        scenario_id,
        method,
        metric,
    )
    ci_low: float | None = None
    ci_high: float | None = None
    if retained.size:
        ci = bootstrap_mean_ci(
            retained,
            rng_seed=seed,
            n_resamples=n_resamples,
            confidence_level=0.95,
        )
        ci_low, ci_high = ci.lower, ci.upper
    row: dict[str, Any] = {
        "schema_version": PHASE6_AGGREGATE_SCHEMA_VERSION,
        "metric_family": metric_family,
        "aggregation_scope": aggregation_scope,
        "scenario_id": scenario_id,
        "truth_class": _truth_class(group),
        "method": method,
        "metric": metric,
        "qualification": qualification,
        "statistical_unit": "episode",
        "n_total": int(len(group)),
        "n_observed": int(np.count_nonzero(observed)),
        "n_missing": int(len(group) - np.count_nonzero(observed)),
        "n_run_incomplete": int(
            np.count_nonzero(
                ~_bool_mask(group["run_completed"], "run_completed", missing_value=False)
            )
        ),
        "n_scientific_failure": int(
            np.count_nonzero(
                ~_bool_mask(
                    group["scientific_success"],
                    "scientific_success",
                    missing_value=False,
                )
            )
        ),
        "n_censored": int(np.count_nonzero(censored)),
        **_descriptive_statistics(retained),
        "ci95_low": ci_low,
        "ci95_high": ci_high,
        "confidence_level": 0.95,
        "bootstrap_resamples": n_resamples,
        "bootstrap_seed": seed,
    }
    return row


def _aggregate_family(
    frame: pd.DataFrame,
    metrics: Sequence[str],
    *,
    metric_family: str,
    qualification: str,
    analysis_seed: int,
    n_resamples: int,
) -> pd.DataFrame:
    _require_columns(
        frame,
        (
            "scenario_id",
            "truth_class",
            "method",
            "run_completed",
            "scientific_success",
            *metrics,
        ),
        f"{metric_family} source",
    )
    rows: list[dict[str, Any]] = []
    methods = sorted(set(str(value) for value in frame["method"].tolist()))
    scenarios = sorted(set(str(value) for value in frame["scenario_id"].tolist()))
    for scenario_id in scenarios:
        scenario = frame.loc[frame["scenario_id"] == scenario_id]
        for method in methods:
            group = scenario.loc[scenario["method"] == method]
            if group.empty:
                continue
            for metric in metrics:
                rows.append(
                    _aggregate_row(
                        group,
                        metric=metric,
                        metric_family=metric_family,
                        aggregation_scope="scenario",
                        scenario_id=scenario_id,
                        method=method,
                        qualification=qualification,
                        analysis_seed=analysis_seed,
                        n_resamples=n_resamples,
                    )
                )
    for method in methods:
        group = frame.loc[frame["method"] == method]
        if group.empty:
            continue
        for metric in metrics:
            rows.append(
                _aggregate_row(
                    group,
                    metric=metric,
                    metric_family=metric_family,
                    aggregation_scope="overall_episode",
                    scenario_id=OVERALL_SCENARIO_ID,
                    method=method,
                    qualification=qualification,
                    analysis_seed=analysis_seed,
                    n_resamples=n_resamples,
                )
            )
    result = pd.DataFrame.from_records(rows, columns=AGGREGATE_COLUMNS)
    validate_aggregate_output(result, metric_family=metric_family)
    return result


def validate_aggregate_output(frame: pd.DataFrame, *, metric_family: str) -> None:
    """Validate an exact aggregate CSV schema and its missingness invariants."""

    _require_columns(frame, AGGREGATE_COLUMNS, f"{metric_family} aggregate")
    if tuple(frame.columns) != AGGREGATE_COLUMNS:
        raise ValueError("aggregate CSV columns must exactly match AGGREGATE_COLUMNS")
    if frame.duplicated(
        ["aggregation_scope", "scenario_id", "method", "metric"]
    ).any():
        raise ValueError("aggregate CSV has duplicate method/scenario/metric rows")
    if not frame.empty:
        if set(frame["schema_version"]) != {PHASE6_AGGREGATE_SCHEMA_VERSION}:
            raise ValueError("aggregate schema_version mismatch")
        if set(frame["metric_family"]) != {metric_family}:
            raise ValueError("aggregate metric_family mismatch")
    for _, row in frame.iterrows():
        counts: dict[str, int] = {}
        for column in (
            "n_total",
            "n_observed",
            "n_missing",
            "n_run_incomplete",
            "n_scientific_failure",
            "n_censored",
            "bootstrap_resamples",
            "bootstrap_seed",
        ):
            value = row[column]
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
                raise TypeError(f"{column} must be integer-valued")
            number = float(value)
            if not math.isfinite(number) or not number.is_integer() or number < 0:
                raise ValueError(f"{column} must be a non-negative integer")
            counts[column] = int(number)
        if counts["n_observed"] + counts["n_missing"] != counts["n_total"]:
            raise ValueError("n_observed + n_missing must equal n_total")
        if counts["n_censored"] > counts["n_missing"]:
            raise ValueError("n_censored cannot exceed n_missing")
        for column in ("n_run_incomplete", "n_scientific_failure"):
            if counts[column] > counts["n_total"]:
                raise ValueError(f"{column} cannot exceed n_total")
        if counts["n_observed"] == 0 and any(
            not pd.isna(row[column])
            for column in (
                "mean",
                "median",
                "std",
                "q05",
                "q95",
                "ci95_low",
                "ci95_high",
            )
        ):
            raise ValueError("an all-missing aggregate cannot publish numerical estimates")


def _pair_table(
    frame: pd.DataFrame,
    metric: str,
    *,
    reference_method: str,
    scenario_id: str | None,
) -> tuple[pd.DataFrame, str, str]:
    if scenario_id is None:
        source = frame
        keys = ["scenario_id", "seed"]
        output_scenario = OVERALL_SCENARIO_ID
        scope = "overall_episode"
    else:
        source = frame.loc[frame["scenario_id"] == scenario_id]
        keys = ["seed"]
        output_scenario = scenario_id
        scope = "scenario"
    if metric in SOLVER_METRICS:
        final_tier = source["solver_tier"].astype(str).str.upper().eq("FINAL")
        final_tier &= _solver_eligibility_mask(source)
        source = source.loc[final_tier]
    selected = source.loc[source["method"].isin(("P", reference_method))]
    left = selected.loc[selected["method"] == "P", [*keys, metric]].copy()
    right = selected.loc[
        selected["method"] == reference_method, [*keys, metric]
    ].copy()
    if left.duplicated(keys).any() or right.duplicated(keys).any():
        raise ValueError("paired statistical rows are not unique on their pairing keys")
    paired = left.merge(
        right,
        on=keys,
        how="outer",
        suffixes=("_method", "_reference"),
        indicator="_pair_status",
        validate="one_to_one",
        sort=True,
    )
    return paired, output_scenario, scope


def _paired_audit(paired: pd.DataFrame, metric: str) -> tuple[dict[str, int], np.ndarray]:
    status = paired["_pair_status"]
    matched = status.eq("both").to_numpy(dtype=np.bool_)
    method_values, method_observed = _numeric_values(
        paired[f"{metric}_method"], f"{metric}_method"
    )
    reference_values, reference_observed = _numeric_values(
        paired[f"{metric}_reference"], f"{metric}_reference"
    )
    observed = matched & method_observed & reference_observed
    differences = method_values[observed] - reference_values[observed]
    counts = {
        "method_n_total": int(status.isin(("both", "left_only")).sum()),
        "reference_n_total": int(status.isin(("both", "right_only")).sum()),
        "key_union_count": int(len(paired)),
        "matched_pair_count": int(np.count_nonzero(matched)),
        "paired_observed_count": int(np.count_nonzero(observed)),
        "missing_metric_pair_count": int(np.count_nonzero(matched & ~observed)),
        "unmatched_method_count": int(status.eq("left_only").sum()),
        "unmatched_reference_count": int(status.eq("right_only").sum()),
    }
    return counts, differences


def _base_test_row(
    *,
    frame: pd.DataFrame,
    paired: pd.DataFrame,
    metric: str,
    reference_method: str,
    scenario_id: str,
    scope: str,
    test_type: str,
    differences: np.ndarray,
    counts: Mapping[str, int],
    analysis_seed: int,
    n_resamples: int,
) -> dict[str, Any]:
    if scenario_id == OVERALL_SCENARIO_ID:
        truth = _truth_class(frame)
    else:
        truth = _truth_class(frame.loc[frame["scenario_id"] == scenario_id])
    seed = _analysis_seed(
        analysis_seed,
        "paired-bootstrap",
        test_type,
        scope,
        scenario_id,
        metric,
        reference_method,
    )
    descriptive = _descriptive_statistics(differences)
    ci_low: float | None = None
    ci_high: float | None = None
    if differences.size:
        ci = paired_bootstrap_mean_ci(
            differences,
            rng_seed=seed,
            n_resamples=n_resamples,
            confidence_level=0.95,
        )
        ci_low, ci_high = ci.lower, ci.upper
    return {
        "schema_version": PHASE6_STATISTICAL_TEST_SCHEMA_VERSION,
        "holm_family_id": f"{test_type}|{metric}|{scope}",
        "aggregation_scope": scope,
        "scenario_id": scenario_id,
        "truth_class": truth,
        "metric": metric,
        "test_type": test_type,
        "method": "P",
        "reference_method": reference_method,
        "difference_direction": "P_minus_reference",
        "pairing_keys": "scenario_id+seed",
        "statistical_unit": "paired_episode",
        **counts,
        "mean_difference": descriptive["mean"],
        "median_difference": descriptive["median"],
        "std_difference": descriptive["std"],
        "q05_difference": descriptive["q05"],
        "q95_difference": descriptive["q95"],
        "ci95_low": ci_low,
        "ci95_high": ci_high,
        "confidence_level": 0.95,
        "bootstrap_resamples": n_resamples,
        "bootstrap_seed": seed,
        "test_statistic": None,
        "pvalue_raw": None,
        "test_resamples": 0,
        "test_exact": None,
        "mcnemar_both_false": None,
        "mcnemar_method_false_reference_true": None,
        "mcnemar_method_true_reference_false": None,
        "mcnemar_both_true": None,
        "mcnemar_discordant_count": None,
        "pvalue_holm": None,
        "reject_holm_0_05": None,
        "holm_family_size": 0,
    }


def _continuous_test_row(
    frame: pd.DataFrame,
    metric: str,
    *,
    reference_method: str,
    scenario_id: str | None,
    analysis_seed: int,
    n_resamples: int,
) -> dict[str, Any]:
    paired, output_scenario, scope = _pair_table(
        frame, metric, reference_method=reference_method, scenario_id=scenario_id
    )
    counts, differences = _paired_audit(paired, metric)
    row = _base_test_row(
        frame=frame,
        paired=paired,
        metric=metric,
        reference_method=reference_method,
        scenario_id=output_scenario,
        scope=scope,
        test_type="paired_sign_flip",
        differences=differences,
        counts=counts,
        analysis_seed=analysis_seed,
        n_resamples=n_resamples,
    )
    if differences.size:
        permutation_seed = _analysis_seed(
            analysis_seed,
            "sign-flip",
            scope,
            output_scenario,
            metric,
            reference_method,
        )
        test = sign_flip_permutation_test(
            differences, rng_seed=permutation_seed, n_resamples=n_resamples
        )
        row.update(
            test_statistic=test.statistic,
            pvalue_raw=test.pvalue,
            test_resamples=test.permutation_count,
            test_exact=test.exact,
        )
    return row


def _mcnemar_test_row(
    frame: pd.DataFrame,
    *,
    reference_method: str,
    scenario_id: str | None,
    analysis_seed: int,
    n_resamples: int,
) -> dict[str, Any]:
    metric = "catastrophic_failure"
    paired, output_scenario, scope = _pair_table(
        frame, metric, reference_method=reference_method, scenario_id=scenario_id
    )
    counts, differences = _paired_audit(paired, metric)
    row = _base_test_row(
        frame=frame,
        paired=paired,
        metric=metric,
        reference_method=reference_method,
        scenario_id=output_scenario,
        scope=scope,
        test_type="exact_mcnemar",
        differences=differences,
        counts=counts,
        analysis_seed=analysis_seed,
        n_resamples=n_resamples,
    )
    matched = paired["_pair_status"].eq("both").to_numpy(dtype=np.bool_)
    if np.any(matched):
        left = paired.loc[matched, f"{metric}_method"].tolist()
        right = paired.loc[matched, f"{metric}_reference"].tolist()
        test = exact_mcnemar(left, right)
        row.update(
            test_statistic=float(
                abs(
                    test.first_true_second_false
                    - test.first_false_second_true
                )
            ),
            pvalue_raw=test.pvalue,
            test_resamples=0,
            test_exact=True,
            mcnemar_both_false=test.both_false,
            mcnemar_method_false_reference_true=(
                test.first_false_second_true
            ),
            mcnemar_method_true_reference_false=(
                test.first_true_second_false
            ),
            mcnemar_both_true=test.both_true,
            mcnemar_discordant_count=test.discordant_count,
        )
    return row


def _apply_holm_families(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for family, indices in output.groupby("holm_family_id", sort=True).groups.items():
        _ = family
        index_list = list(indices)
        raw = output.loc[index_list, "pvalue_raw"].to_numpy(dtype=object)
        adjusted = holm_adjust(raw, alpha=0.05)
        output.loc[index_list, "pvalue_holm"] = list(adjusted.adjusted_pvalues)
        output.loc[index_list, "reject_holm_0_05"] = list(adjusted.rejected)
        family_size = sum(value is not None for value in adjusted.adjusted_pvalues)
        output.loc[index_list, "holm_family_size"] = family_size
    return output


def build_statistical_tests(
    frame: pd.DataFrame,
    *,
    analysis_seed: int = DEFAULT_ANALYSIS_SEED,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
) -> pd.DataFrame:
    """Build paired P-vs-B1/B2 tests and exact catastrophic McNemar tests."""

    resamples = _positive_resamples(n_resamples)
    _require_columns(
        frame,
        (
            "scenario_id",
            "seed",
            "method",
            "truth_class",
            "catastrophic_failure",
            "solver_tier",
            *PAIRED_CONTINUOUS_METRICS,
        ),
        "statistical source",
    )
    _validate_unique_episode_keys(frame, "statistical source")
    scenarios = sorted(set(str(value) for value in frame["scenario_id"].tolist()))
    rows: list[dict[str, Any]] = []
    for metric in PAIRED_CONTINUOUS_METRICS:
        for reference in ("B1", "B2"):
            for scenario in scenarios:
                rows.append(
                    _continuous_test_row(
                        frame,
                        metric,
                        reference_method=reference,
                        scenario_id=scenario,
                        analysis_seed=analysis_seed,
                        n_resamples=resamples,
                    )
                )
            rows.append(
                _continuous_test_row(
                    frame,
                    metric,
                    reference_method=reference,
                    scenario_id=None,
                    analysis_seed=analysis_seed,
                    n_resamples=resamples,
                )
            )
    for reference in ("B1", "B2"):
        for scenario in scenarios:
            rows.append(
                _mcnemar_test_row(
                    frame,
                    reference_method=reference,
                    scenario_id=scenario,
                    analysis_seed=analysis_seed,
                    n_resamples=resamples,
                )
            )
        rows.append(
            _mcnemar_test_row(
                frame,
                reference_method=reference,
                scenario_id=None,
                analysis_seed=analysis_seed,
                n_resamples=resamples,
            )
        )
    result = pd.DataFrame.from_records(rows, columns=STATISTICAL_TEST_COLUMNS)
    result = _apply_holm_families(result).loc[:, STATISTICAL_TEST_COLUMNS]
    validate_statistical_tests_output(result)
    return result


def validate_statistical_tests_output(frame: pd.DataFrame) -> None:
    """Validate the exact statistical-tests CSV schema and pairing audits."""

    _require_columns(frame, STATISTICAL_TEST_COLUMNS, "statistical_tests")
    if tuple(frame.columns) != STATISTICAL_TEST_COLUMNS:
        raise ValueError(
            "statistical-tests CSV columns must exactly match STATISTICAL_TEST_COLUMNS"
        )
    key = [
        "aggregation_scope",
        "scenario_id",
        "metric",
        "test_type",
        "method",
        "reference_method",
    ]
    if frame.duplicated(key).any():
        raise ValueError("statistical-tests CSV contains duplicate hypothesis rows")
    if not frame.empty and set(frame["schema_version"]) != {
        PHASE6_STATISTICAL_TEST_SCHEMA_VERSION
    }:
        raise ValueError("statistical-tests schema_version mismatch")
    for _, row in frame.iterrows():
        for column in (
            "method_n_total",
            "reference_n_total",
            "key_union_count",
            "matched_pair_count",
            "paired_observed_count",
            "missing_metric_pair_count",
            "unmatched_method_count",
            "unmatched_reference_count",
        ):
            value = row[column]
            if not isinstance(value, Real) or not float(value).is_integer() or value < 0:
                raise ValueError(f"{column} must be a non-negative integer")
        if int(row["paired_observed_count"]) + int(
            row["missing_metric_pair_count"]
        ) != int(row["matched_pair_count"]):
            raise ValueError("observed and missing paired counts must equal matched pairs")
        for column in ("pvalue_raw", "pvalue_holm"):
            value = row[column]
            if not pd.isna(value) and not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{column} must lie in [0, 1] or be missing")


def _attach_oracle(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    source = frame.copy()
    source["oracle_regret"] = np.nan
    attachment = attach_oracle_regret(
        source,
        "freq_iae",
        oracle_method="B4",
        output_column="oracle_regret",
        pairing_columns=("scenario_id", "seed"),
    )
    return attachment.table, attachment.pairing_audit


def analyze_phase6_tables(
    episode_metrics: pd.DataFrame,
    experiment_ledger: pd.DataFrame,
    *,
    require_complete_final: bool = True,
    analysis_seed: int = DEFAULT_ANALYSIS_SEED,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
) -> Phase6AnalysisTables:
    """Create all four review tables from canonical Phase-6 input tables."""

    resamples = _positive_resamples(n_resamples)
    validated = validate_phase6_inputs(
        episode_metrics,
        experiment_ledger,
        require_complete_final=require_complete_final,
    )
    augmented, oracle_audit = _attach_oracle(validated.episode_metrics)
    metadata_columns = ["run_id", "stage", "truth_class", "solver_tier"]
    if "eligible_for_final_solver_claims" in validated.experiment_ledger.columns:
        metadata_columns.append("eligible_for_final_solver_claims")
        if "controller_metadata_status" in validated.experiment_ledger.columns:
            metadata_columns.append("controller_metadata_status")
    joined = augmented.merge(
        validated.experiment_ledger.loc[:, metadata_columns],
        on="run_id",
        how="left",
        validate="one_to_one",
        sort=False,
    )

    non_runtime = joined["method"].isin(NON_RUNTIME_DIAGNOSTIC_METHODS)
    leaked_fields = joined.loc[non_runtime, DIAGNOSTIC_METRICS].notna().any(axis=1)
    if leaked_fields.any():
        methods = sorted(set(joined.loc[non_runtime].loc[leaked_fields, "method"]))
        raise ValueError(
            "standard diagnostic fields must be missing for methods without runtime "
            f"diagnosis; truth-informed Oracle is excluded: {methods!r}"
        )

    summary = _aggregate_family(
        joined,
        SUMMARY_METRICS,
        metric_family="summary",
        qualification="all_attempted_episodes;missing_not_zero",
        analysis_seed=analysis_seed,
        n_resamples=resamples,
    )
    diagnostic_source = joined.loc[
        joined["method"].isin(RUNTIME_DIAGNOSTIC_METHODS)
    ].copy()
    diagnostics = _aggregate_family(
        diagnostic_source,
        DIAGNOSTIC_METRICS,
        metric_family="diagnostic",
        qualification=(
            "runtime_diagnosis_only;B4_truth_informed_excluded;"
            "detection_delays_detected_events_only;"
            "censoring_in_companion_count_and_time_metrics"
        ),
        analysis_seed=analysis_seed,
        n_resamples=resamples,
    )

    final_tier = joined["solver_tier"].astype(str).str.upper().eq("FINAL")
    final_tier &= _solver_eligibility_mask(joined)
    solver_source = joined.loc[
        final_tier & joined["method"].isin(SOLVER_APPLICABLE_METHODS)
    ].copy()
    solvers = _aggregate_family(
        solver_source,
        SOLVER_METRICS,
        metric_family="solver",
        qualification="FINAL_solver_tier_only;optimization_methods_only",
        analysis_seed=analysis_seed,
        n_resamples=resamples,
    )
    tests = build_statistical_tests(
        joined, analysis_seed=analysis_seed, n_resamples=resamples
    )
    return Phase6AnalysisTables(
        episode_metrics_with_oracle_regret=augmented,
        oracle_pairing_audit=oracle_audit,
        summary_metrics=summary,
        statistical_tests=tests,
        diagnostic_metrics=diagnostics,
        solver_metrics=solvers,
    )


def _atomic_write_csv(frame: pd.DataFrame, destination: Path) -> Path:
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        frame.to_csv(temporary, index=False, lineterminator="\n")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def _atomic_copy_bytes(source: Path, destination: Path) -> Path:
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as reader, os.fdopen(handle, "wb") as writer:
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(block)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def write_phase6_analysis(
    per_episode_metrics_csv: str | Path,
    experiment_ledger_csv: str | Path,
    output_directory: str | Path,
    *,
    require_complete_final: bool = True,
    analysis_seed: int = DEFAULT_ANALYSIS_SEED,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    protocol_lock_path: str | Path | None = None,
) -> Phase6AnalysisArtifacts:
    """Write the complete review-spec result set from canonical Phase-6 CSVs.

    The canonical run store is never edited.  The review copy augments both
    episode metrics and the ledger with paired Oracle regret so their embedded
    :class:`EpisodeResult` rows remain identical and independently auditable.
    """

    metrics_path = Path(per_episode_metrics_csv).expanduser().resolve()
    ledger_path = Path(experiment_ledger_csv).expanduser().resolve()
    if not metrics_path.is_file():
        raise FileNotFoundError(metrics_path)
    if not ledger_path.is_file():
        raise FileNotFoundError(ledger_path)
    metrics = pd.read_csv(metrics_path)
    ledger = pd.read_csv(ledger_path)
    tables = analyze_phase6_tables(
        metrics,
        ledger,
        require_complete_final=require_complete_final,
        analysis_seed=analysis_seed,
        n_resamples=n_resamples,
    )
    augmented_metrics = tables.episode_metrics_with_oracle_regret.loc[
        :, EPISODE_RESULT_COLUMNS
    ].copy()
    regret_by_run = augmented_metrics.set_index("run_id")["oracle_regret"]
    review_ledger = ledger.copy()
    review_ledger["oracle_regret"] = review_ledger["run_id"].map(regret_by_run)
    # Re-run the strict identity audit after adding the derived column.  This
    # prevents a packaging-only transform from dropping or changing failures.
    validate_phase6_inputs(
        augmented_metrics,
        review_ledger,
        require_complete_final=require_complete_final,
    )
    output = Path(output_directory).expanduser().resolve()
    published_protocol_lock: Path | None = None
    if protocol_lock_path is not None:
        source_lock = Path(protocol_lock_path).expanduser().resolve()
        if not source_lock.is_file():
            raise FileNotFoundError(source_lock)
        if "final_protocol_lock_file_sha256" not in ledger.columns:
            raise ValueError(
                "a published protocol lock requires its SHA-256 ledger column"
            )
        declared = {
            str(value).strip().lower()
            for value in ledger["final_protocol_lock_file_sha256"].dropna()
        }
        observed = hashlib.sha256(source_lock.read_bytes()).hexdigest()
        if declared != {observed}:
            raise ValueError(
                "protocol lock SHA-256 differs from the unique ledger binding"
            )
        published_protocol_lock = _atomic_copy_bytes(
            source_lock, output / "protocol_lock.json"
        )
    return Phase6AnalysisArtifacts(
        tables=tables,
        per_episode_metrics_path=_atomic_write_csv(
            augmented_metrics, output / "per_episode_metrics.csv"
        ),
        experiment_ledger_path=_atomic_write_csv(
            review_ledger, output / "experiment_ledger.csv"
        ),
        summary_metrics_path=_atomic_write_csv(
            tables.summary_metrics, output / "summary_metrics.csv"
        ),
        statistical_tests_path=_atomic_write_csv(
            tables.statistical_tests, output / "statistical_tests.csv"
        ),
        diagnostic_metrics_path=_atomic_write_csv(
            tables.diagnostic_metrics, output / "diagnostic_metrics.csv"
        ),
        solver_metrics_path=_atomic_write_csv(
            tables.solver_metrics, output / "solver_metrics.csv"
        ),
        oracle_pairing_audit_path=_atomic_write_csv(
            tables.oracle_pairing_audit, output / "oracle_pairing_audit.csv"
        ),
        protocol_lock_path=published_protocol_lock,
    )


__all__ = [
    "AGGREGATE_COLUMNS",
    "CENSORING_AUDIT_METRICS",
    "CONTROL_PERFORMANCE_METRICS",
    "DEFAULT_ANALYSIS_SEED",
    "DEFAULT_BOOTSTRAP_RESAMPLES",
    "DIAGNOSTIC_METRICS",
    "DIAGNOSTIC_METRICS_COLUMNS",
    "EXPECTED_FINAL_EPISODE_COUNT",
    "EXPECTED_FINAL_METHODS",
    "EXPECTED_FINAL_SEEDS",
    "EXPECTED_FINAL_TRUTH_CLASS",
    "OVERALL_SCENARIO_ID",
    "PAIRED_CONTINUOUS_METRICS",
    "PHASE6_AGGREGATE_SCHEMA_VERSION",
    "PHASE6_STATISTICAL_TEST_SCHEMA_VERSION",
    "Phase6AnalysisArtifacts",
    "Phase6AnalysisTables",
    "SOLVER_METRICS",
    "SOLVER_METRICS_COLUMNS",
    "STATISTICAL_TEST_COLUMNS",
    "SUMMARY_METRICS",
    "SUMMARY_METRICS_COLUMNS",
    "ValidatedPhase6Inputs",
    "analyze_phase6_tables",
    "build_statistical_tests",
    "validate_aggregate_output",
    "validate_final_coverage",
    "validate_phase6_inputs",
    "validate_statistical_tests_output",
    "write_phase6_analysis",
]
