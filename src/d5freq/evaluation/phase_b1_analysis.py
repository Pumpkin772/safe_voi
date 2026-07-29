"""Strict Phase-B1 evidence aggregation, statistics, and decision logic."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

from d5freq.evaluation.closed_loop_scenarios import load_experiment_protocol
from d5freq.evaluation.experiment_store import PerRunExperimentStore
from d5freq.evaluation.phase_b1_execution import attempt_failure_path
from d5freq.evaluation.phase_b1_experiments import PhaseB1RunSpec
from d5freq.evaluation.phase_b1_protocol import PhaseB1Paths
from d5freq.evaluation.results_schema import EpisodeResult
from d5freq.evaluation.statistics import (
    holm_adjust,
    paired_bootstrap_mean_ci,
    sign_flip_permutation_test,
)
from d5freq.utils.config import load_yaml


REQUIRED_TABLES = (
    "problem_materiality.csv",
    "oracle_gap.csv",
    "closed_loop_prediction_error.csv",
    "constraint_activation.csv",
    "information_gramian.csv",
    "pairwise_separation.csv",
    "identifiability_delay.csv",
    "source_confusion.csv",
    "control_design_decomposition.csv",
    "per_episode_metrics.csv",
    "statistical_tests.csv",
    "solver_metrics.csv",
)

AUDIT_TABLE_NAMES = (
    "closed_loop_prediction_error",
    "constraint_activation",
    "information_gramian",
    "pairwise_separation",
    "identifiability_delay",
    "source_confusion",
)


def _read_attempt_failure(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or set(payload) != {"body", "sha256"}:
        raise RuntimeError(f"malformed Phase-B1 attempt failure: {path}")
    from d5freq.utils.hashing import sha256_json

    if sha256_json(payload["body"]) != payload["sha256"]:
        raise RuntimeError(f"attempt failure digest mismatch: {path}")
    return payload["body"]


def collect_final_evidence(
    paths: PhaseB1Paths,
    plans: Sequence[Sequence[PhaseB1RunSpec]],
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    """Load every planned canonical episode or retained pre-publication failure."""

    plan = tuple(spec for subset in plans for spec in subset)
    identities = [spec.identity.run_id for spec in plan]
    if len(identities) != len(set(identities)):
        raise ValueError("combined Phase-B1 evidence plan contains duplicate run IDs")
    protocol = load_experiment_protocol(paths.experiments_config)
    truth_classes = {
        row.scenario_id: row.truth_class for row in protocol.scenario_variants
    }
    store = PerRunExperimentStore(paths.results_root / "runs" / "final" / "per_run")
    episode_fields = tuple(field.name for field in fields(EpisodeResult))
    episode_rows: list[dict[str, Any]] = []
    solver_rows: list[dict[str, Any]] = []
    audit_rows: dict[str, list[dict[str, Any]]] = {
        name: [] for name in AUDIT_TABLE_NAMES
    }
    audit_failure_rows: list[dict[str, Any]] = []
    integrity_rows: list[dict[str, Any]] = []
    for spec in plan:
        stored = store.load(spec.identity)
        failure_path = attempt_failure_path(paths, spec)
        if stored is not None and failure_path.is_file():
            raise RuntimeError(f"run has both canonical evidence and failure receipt: {spec.identity.run_id}")
        base = {
            "stage": spec.stage,
            "sg_level": spec.sg_level,
            "truth_class": truth_classes[spec.scenario_id],
            "oracle_candidate_id": spec.oracle_candidate_id,
            "oracle_horizon_s": spec.oracle_horizon_s,
            "solver_tier": spec.solver_tier,
        }
        if stored is None:
            if not failure_path.is_file():
                raise RuntimeError(f"planned final run has no retained outcome: {spec.identity.run_id}")
            failure = _read_attempt_failure(failure_path)
            row = {name: None for name in episode_fields}
            row.update(
                {
                    "run_id": spec.identity.run_id,
                    "scenario_id": spec.scenario_id,
                    "method": spec.method_id,
                    "seed": spec.seed,
                    "run_completed": False,
                    "success": False,
                    "scientific_success": False,
                    "failure_stage": "pre_canonical_publication",
                    "failure_type": failure["failure_type"],
                    "failure_message": failure["failure_message"],
                    **base,
                    "evidence_status": "retained_attempt_failure",
                }
            )
            episode_rows.append(row)
            solver_rows.append(
                {
                    "run_id": spec.identity.run_id,
                    "scenario_id": spec.scenario_id,
                    "method": spec.method_id,
                    "seed": spec.seed,
                    "sg_level": spec.sg_level,
                    "scientific_success": False,
                    "failure_stage": "pre_canonical_publication",
                    "solver_status_counts_json": "{}",
                    "solver_outcome_counts_json": "{}",
                }
            )
            integrity_rows.append(
                {
                    "run_id": spec.identity.run_id,
                    "evidence_status": "retained_attempt_failure",
                    "evidence_sha256": json.loads(failure_path.read_text(encoding="utf-8"))["sha256"],
                }
            )
            continue
        result = stored.episode_result.to_json_dict()
        episode_rows.append({**result, **base, "evidence_status": "canonical_episode"})
        evaluation = stored.run_payload.get("evaluation_artifacts", {})
        evaluator = evaluation.get("evaluator_0", {}) if isinstance(evaluation, Mapping) else {}
        statuses = evaluator.get("solver_status_counts", {})
        outcomes = evaluator.get("solver_outcome_counts", {})
        solver_rows.append(
            {
                "run_id": spec.identity.run_id,
                "scenario_id": spec.scenario_id,
                "method": spec.method_id,
                "seed": spec.seed,
                "sg_level": spec.sg_level,
                "scientific_success": bool(result["scientific_success"]),
                "failure_stage": result["failure_stage"],
                "solve_time_mean_s": result["solve_time_mean_s"],
                "solve_time_p95_s": result["solve_time_p95_s"],
                "solve_time_max_s": result["solve_time_max_s"],
                "solver_attempt_count": result["solver_attempt_count"],
                "solver_fail_count": result["solver_fail_count"],
                "solver_timeout_count": result["solver_timeout_count"],
                "solver_infeasible_count": result["solver_infeasible_count"],
                "wall_time_s": result["wall_time_s"],
                "max_exact_mirror_error": evaluator.get("max_exact_mirror_error"),
                "mean_ibr_authority_ratio": evaluator.get("mean_ibr_authority_ratio"),
                "solver_status_counts_json": json.dumps(statuses, sort_keys=True),
                "solver_outcome_counts_json": json.dumps(outcomes, sort_keys=True),
            }
        )
        compact = evaluator.get("compact_scientific_audits", {})
        if isinstance(compact, Mapping):
            for name in AUDIT_TABLE_NAMES:
                rows = compact.get(name, ())
                if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
                    for row in rows:
                        audit_rows[name].append({"method": spec.method_id, **dict(row)})
        failures = evaluator.get("compact_scientific_audit_failures", ())
        if isinstance(failures, Sequence) and not isinstance(failures, (str, bytes, bytearray)):
            for failure in failures:
                audit_failure_rows.append(
                    {
                        "run_id": spec.identity.run_id,
                        "scenario_id": spec.scenario_id,
                        "method": spec.method_id,
                        "seed": spec.seed,
                        "sg_level": spec.sg_level,
                        **dict(failure),
                    }
                )
        integrity_rows.append(
            {
                "run_id": spec.identity.run_id,
                "evidence_status": "canonical_episode",
                "evidence_sha256": stored.sha256,
            }
        )
    episodes = pd.DataFrame.from_records(episode_rows)
    if episodes["run_id"].duplicated().any() or len(episodes) != len(plan):
        raise RuntimeError("per-episode evidence is not exactly one row per planned run")
    audits = {name: pd.DataFrame.from_records(rows) for name, rows in audit_rows.items()}
    return (
        episodes.sort_values(["scenario_id", "sg_level", "method", "seed"]),
        audits,
        pd.DataFrame.from_records(solver_rows).sort_values(
            ["scenario_id", "sg_level", "method", "seed"]
        ),
        pd.DataFrame.from_records(audit_failure_rows),
    )


def _finite_pairs(
    frame: pd.DataFrame,
    method: str,
    reference: str,
    metric: str,
    *,
    scenario_id: str | None,
    sg_level: str | None,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    subset = frame
    if scenario_id is not None:
        subset = subset.loc[subset["scenario_id"] == scenario_id]
    if sg_level is not None:
        subset = subset.loc[subset["sg_level"] == sg_level]
    columns = ["scenario_id", "seed", "sg_level", "method", metric, "scientific_success"]
    subset = subset.loc[subset["method"].isin((method, reference)), columns]
    left = subset.loc[subset["method"] == method].drop(columns="method")
    right = subset.loc[subset["method"] == reference].drop(columns="method")
    paired = left.merge(
        right,
        on=["scenario_id", "seed", "sg_level"],
        how="outer",
        suffixes=("_method", "_reference"),
        indicator=True,
        validate="one_to_one",
    )
    left_value = pd.to_numeric(paired[f"{metric}_method"], errors="coerce").to_numpy(float)
    right_value = pd.to_numeric(paired[f"{metric}_reference"], errors="coerce").to_numpy(float)
    finite = (
        paired["_merge"].eq("both").to_numpy()
        & np.isfinite(left_value)
        & np.isfinite(right_value)
        & paired["scientific_success_method"].fillna(False).to_numpy(bool)
        & paired["scientific_success_reference"].fillna(False).to_numpy(bool)
    )
    return paired, left_value[finite], right_value[finite]


def _paired_summary(
    method_values: np.ndarray,
    reference_values: np.ndarray,
    *,
    seed: int,
    resamples: int,
    relative_denominator: str,
) -> dict[str, Any]:
    if method_values.size == 0:
        return {
            "finite_pair_count": 0,
            "mean_method": None,
            "mean_reference": None,
            "mean_difference": None,
            "mean_relative_difference": None,
            "relative_ci95_low": None,
            "relative_ci95_high": None,
            "sign_flip_pvalue": None,
            "wilcoxon_pvalue": None,
        }
    if relative_denominator == "reference":
        denominator = reference_values
    elif relative_denominator == "method":
        denominator = method_values
    else:
        raise ValueError("relative_denominator must be method or reference")
    relative = np.divide(
        method_values - reference_values,
        denominator,
        out=np.full_like(method_values, np.nan),
        where=np.abs(denominator) > 1.0e-15,
    )
    relative = relative[np.isfinite(relative)]
    ci = (
        None
        if not relative.size
        else paired_bootstrap_mean_ci(
            relative, rng_seed=seed, n_resamples=resamples, confidence_level=0.95
        )
    )
    differences = method_values - reference_values
    sign = sign_flip_permutation_test(
        differences, rng_seed=seed + 1, n_resamples=resamples
    )
    try:
        wilcoxon_pvalue = (
            1.0
            if np.allclose(differences, 0.0, rtol=0.0, atol=1.0e-15)
            else float(wilcoxon(differences, zero_method="pratt").pvalue)
        )
    except ValueError:
        wilcoxon_pvalue = 1.0
    return {
        "finite_pair_count": int(method_values.size),
        "mean_method": float(np.mean(method_values)),
        "mean_reference": float(np.mean(reference_values)),
        "mean_difference": float(np.mean(differences)),
        "mean_relative_difference": None if not relative.size else float(np.mean(relative)),
        "relative_ci95_low": None if ci is None else ci.lower,
        "relative_ci95_high": None if ci is None else ci.upper,
        "sign_flip_pvalue": sign.pvalue,
        "wilcoxon_pvalue": wilcoxon_pvalue,
    }


def build_materiality_table(
    episodes: pd.DataFrame, paths: PhaseB1Paths
) -> pd.DataFrame:
    config = load_yaml(paths.audit_config)["materiality_gate"]
    rows: list[dict[str, Any]] = []
    scopes: list[tuple[str, str | None]] = [("overall", None)] + [
        ("scenario", value) for value in sorted(episodes["scenario_id"].unique())
    ]
    levels: list[str | None] = [None, "A", "B", "C"]
    for scope, scenario_id in scopes:
        for level in levels:
            pairs, b5_iae, b0_iae = _finite_pairs(
                episodes, "B5", "B0", "freq_iae", scenario_id=scenario_id, sg_level=level
            )
            _, b5_max, b0_max = _finite_pairs(
                episodes, "B5", "B0", "max_abs_freq_hz", scenario_id=scenario_id, sg_level=level
            )
            _, b5_sg, b0_sg = _finite_pairs(
                episodes, "B5", "B0", "sg_mileage", scenario_id=scenario_id, sg_level=level
            )
            iae = _paired_summary(
                b5_iae, b0_iae, seed=20260729, resamples=10000, relative_denominator="reference"
            )
            maximum = _paired_summary(
                b5_max, b0_max, seed=20260731, resamples=10000, relative_denominator="reference"
            )
            mileage = _paired_summary(
                b5_sg, b0_sg, seed=20260733, resamples=10000, relative_denominator="reference"
            )
            attempted_b5 = pairs["scientific_success_method"].notna().sum()
            success_b5 = pairs["scientific_success_method"].fillna(False).sum()
            success_rate = None if not attempted_b5 else float(success_b5 / attempted_b5)
            feasible = (
                success_rate is not None
                and success_rate >= float(config["physical_feasibility_min_success_rate"])
            )
            iae_improvement = (
                None if iae["mean_relative_difference"] is None else -iae["mean_relative_difference"]
            )
            sg_improvement = (
                None
                if mileage["mean_relative_difference"] is None
                else -mileage["mean_relative_difference"]
            )
            max_worsening = maximum["mean_relative_difference"]
            frequency_gate = bool(
                feasible
                and iae_improvement is not None
                and max_worsening is not None
                and iae_improvement
                >= float(config["frequency_iae_improvement_min_fraction"])
                and max_worsening
                <= float(config["max_frequency_worsening_max_fraction"])
            )
            resource_gate = bool(
                feasible
                and sg_improvement is not None
                and iae_improvement is not None
                and sg_improvement >= float(config["sg_mileage_improvement_min_fraction"])
                and iae_improvement >= -float(config["frequency_iae_worsening_max_fraction"])
            )
            rows.append(
                {
                    "scope": scope,
                    "scenario_id": "ALL" if scenario_id is None else scenario_id,
                    "sg_level": "ALL" if level is None else level,
                    "attempted_pair_union_count": len(pairs),
                    "finite_pair_count": iae["finite_pair_count"],
                    "b5_success_rate": success_rate,
                    "physically_feasible": feasible,
                    "mean_b0_freq_iae": iae["mean_reference"],
                    "mean_b5_freq_iae": iae["mean_method"],
                    "frequency_iae_improvement_fraction": iae_improvement,
                    "frequency_iae_improvement_ci95_low": (
                        None if iae["relative_ci95_high"] is None else -iae["relative_ci95_high"]
                    ),
                    "frequency_iae_improvement_ci95_high": (
                        None if iae["relative_ci95_low"] is None else -iae["relative_ci95_low"]
                    ),
                    "max_frequency_worsening_fraction": max_worsening,
                    "max_frequency_worsening_ci95_low": maximum["relative_ci95_low"],
                    "max_frequency_worsening_ci95_high": maximum["relative_ci95_high"],
                    "sg_mileage_improvement_fraction": sg_improvement,
                    "sg_mileage_improvement_ci95_low": (
                        None
                        if mileage["relative_ci95_high"] is None
                        else -mileage["relative_ci95_high"]
                    ),
                    "sg_mileage_improvement_ci95_high": (
                        None
                        if mileage["relative_ci95_low"] is None
                        else -mileage["relative_ci95_low"]
                    ),
                    "frequency_value_gate": frequency_gate,
                    "resource_value_gate": resource_gate,
                    "materiality_gate_passed": frequency_gate or resource_gate,
                    "iae_sign_flip_pvalue": iae["sign_flip_pvalue"],
                    "iae_wilcoxon_pvalue": iae["wilcoxon_pvalue"],
                    "max_frequency_sign_flip_pvalue": maximum["sign_flip_pvalue"],
                    "max_frequency_wilcoxon_pvalue": maximum["wilcoxon_pvalue"],
                    "sg_mileage_sign_flip_pvalue": mileage["sign_flip_pvalue"],
                    "sg_mileage_wilcoxon_pvalue": mileage["wilcoxon_pvalue"],
                }
            )
    return pd.DataFrame.from_records(rows)


def build_oracle_gap_table(episodes: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    scopes = [("overall", None)] + [
        ("scenario", value) for value in sorted(episodes["scenario_id"].unique())
    ]
    for metric in ("freq_iae", "max_abs_freq_hz", "sg_mileage", "ibr_mileage"):
        for scope, scenario_id in scopes:
            for level in (None, "A", "B", "C"):
                pairs, b4, b5 = _finite_pairs(
                    episodes, "B4", "B5", metric, scenario_id=scenario_id, sg_level=level
                )
                summary = _paired_summary(
                    b4, b5, seed=20260801, resamples=10000, relative_denominator="reference"
                )
                rows.append(
                    {
                        "scope": scope,
                        "scenario_id": "ALL" if scenario_id is None else scenario_id,
                        "sg_level": "ALL" if level is None else level,
                        "metric": metric,
                        "attempted_pair_union_count": len(pairs),
                        **summary,
                    }
                )
    return pd.DataFrame.from_records(rows)


CONTROL_COMPARISONS = (
    ("C1_true_arx_worst", "C0_true_arx_expected", "worst_mode_cost_penalty"),
    ("C2_perfect_belief_current_mpc", "C1_true_arx_worst", "constraint_tightening_penalty"),
    ("C3_current_belief_expected", "P_old", "remove_worst_mode_cost"),
    ("C4_gradual_authority", "P_old", "replace_binary_fallback"),
    ("C5_no_sticky_prior", "P_old", "remove_sticky_prior"),
    ("C2_perfect_belief_current_mpc", "P_old", "perfect_belief_total_gap"),
)


def build_control_decomposition_table(episodes: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    scopes = [("overall", None)] + [
        ("scenario", value) for value in sorted(episodes["scenario_id"].unique())
    ]
    for method, reference, factor in CONTROL_COMPARISONS:
        for metric in ("freq_iae", "max_abs_freq_hz", "sg_mileage", "ibr_mileage"):
            for scope, scenario_id in scopes:
                for level in (None, "A", "B", "C"):
                    pairs, method_values, reference_values = _finite_pairs(
                        episodes,
                        method,
                        reference,
                        metric,
                        scenario_id=scenario_id,
                        sg_level=level,
                    )
                    summary = _paired_summary(
                        method_values,
                        reference_values,
                        seed=20260805,
                        resamples=10000,
                        relative_denominator="reference",
                    )
                    rows.append(
                        {
                            "scope": scope,
                            "scenario_id": "ALL" if scenario_id is None else scenario_id,
                            "sg_level": "ALL" if level is None else level,
                            "factor": factor,
                            "method": method,
                            "reference_method": reference,
                            "metric": metric,
                            "attempted_pair_union_count": len(pairs),
                            **summary,
                        }
                    )
    return pd.DataFrame.from_records(rows)


def build_statistical_tests(
    materiality: pd.DataFrame,
    oracle_gap: pd.DataFrame,
    control: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for source, frame in (("oracle_gap", oracle_gap), ("control_design", control)):
        for index, row in frame.iterrows():
            sign_column = "sign_flip_pvalue"
            wilcoxon_column = "wilcoxon_pvalue"
            identity = {
                "source_table": source,
                "source_row": int(index),
                "scope": row.get("scope"),
                "scenario_id": row.get("scenario_id"),
                "sg_level": row.get("sg_level"),
                "metric": row.get("metric", "freq_iae"),
                "factor": row.get("factor"),
            }
            rows.append({**identity, "test": "paired_sign_flip", "pvalue_raw": row.get(sign_column)})
            rows.append({**identity, "test": "paired_wilcoxon", "pvalue_raw": row.get(wilcoxon_column)})
    materiality_metrics = (
        ("freq_iae", "iae_sign_flip_pvalue", "iae_wilcoxon_pvalue"),
        (
            "max_abs_freq_hz",
            "max_frequency_sign_flip_pvalue",
            "max_frequency_wilcoxon_pvalue",
        ),
        ("sg_mileage", "sg_mileage_sign_flip_pvalue", "sg_mileage_wilcoxon_pvalue"),
    )
    for index, row in materiality.iterrows():
        for metric, sign_column, wilcoxon_column in materiality_metrics:
            identity = {
                "source_table": "materiality",
                "source_row": int(index),
                "scope": row.get("scope"),
                "scenario_id": row.get("scenario_id"),
                "sg_level": row.get("sg_level"),
                "metric": metric,
                "factor": None,
            }
            rows.append(
                {
                    **identity,
                    "test": "paired_sign_flip",
                    "pvalue_raw": row.get(sign_column),
                }
            )
            rows.append(
                {
                    **identity,
                    "test": "paired_wilcoxon",
                    "pvalue_raw": row.get(wilcoxon_column),
                }
            )
    output = pd.DataFrame.from_records(rows)
    output["pvalue_holm"] = None
    output["reject_holm_0_05"] = None
    for (_, metric), indices in output.groupby(["test", "metric"], dropna=False).groups.items():
        selected = list(indices)
        result = holm_adjust(output.loc[selected, "pvalue_raw"].to_numpy(object), alpha=0.05)
        output.loc[selected, "pvalue_holm"] = list(result.adjusted_pvalues)
        output.loc[selected, "reject_holm_0_05"] = list(result.rejected)
    return output


def decide_bottleneck(
    materiality: pd.DataFrame,
    oracle_gap: pd.DataFrame,
    identifiability_delay: pd.DataFrame,
    control: pd.DataFrame,
    paths: PhaseB1Paths,
) -> dict[str, Any]:
    thresholds = load_yaml(paths.audit_config)["decision_operationalization"]
    level_gate = materiality.loc[
        (materiality["scope"] == "overall")
        & materiality["sg_level"].isin(("A", "B", "C"))
        & materiality["physically_feasible"].eq(True)
    ]
    material = bool(level_gate["materiality_gate_passed"].any())
    b4_row = oracle_gap.loc[
        (oracle_gap["scope"] == "overall")
        & (oracle_gap["sg_level"] == "ALL")
        & (oracle_gap["metric"] == "freq_iae")
    ]
    model_gap = None if b4_row.empty else float(b4_row.iloc[0]["mean_relative_difference"])
    model_threshold = float(
        thresholds["model_mismatch"]["b4_vs_b5_frequency_iae_gap_min_fraction"]
    )
    model_trigger = model_gap is not None and model_gap >= model_threshold

    bayes = identifiability_delay.loc[
        identifiability_delay.get("classifier", pd.Series(dtype=str)).eq(
            "evaluation_only_bayes_correct_candidates"
        )
        & identifiability_delay.get("candidate_set_contains_truth", pd.Series(dtype=bool)).eq(True)
    ]
    critical_window = float(thresholds["identifiability"]["critical_window_s"])
    if bayes.empty:
        delayed_fraction = None
    else:
        delayed = bayes["detection_censored"].astype(bool) | (
            pd.to_numeric(bayes["detection_delay_s"], errors="coerce") > critical_window
        )
        delayed_fraction = float(delayed.mean())
    ident_threshold = float(
        thresholds["identifiability"]["delayed_or_censored_switch_fraction_min"]
    )
    close_threshold = float(
        thresholds["identifiability"]["b4_vs_b5_close_gap_max_fraction"]
    )
    ident_trigger = bool(
        delayed_fraction is not None
        and delayed_fraction >= ident_threshold
        and model_gap is not None
        and model_gap < close_threshold
    )

    isolated = control.loc[
        (control["scope"] == "overall")
        & (control["sg_level"] == "ALL")
        & (control["metric"] == "freq_iae")
        & control["factor"].isin(
            ("remove_worst_mode_cost", "replace_binary_fallback", "remove_sticky_prior")
        )
    ]
    # Counterfactual-minus-P is negative when removing the factor improves IAE.
    isolated_gain = (
        None
        if isolated.empty or isolated["mean_relative_difference"].dropna().empty
        else float(-isolated["mean_relative_difference"].min())
    )
    control_threshold = float(
        thresholds["control_design"]["isolated_counterfactual_frequency_iae_gain_min_fraction"]
    )
    bayes_adequate_limit = float(
        thresholds["control_design"]["bayes_delayed_or_censored_switch_fraction_max"]
    )
    control_trigger = bool(
        isolated_gain is not None
        and isolated_gain >= control_threshold
        and delayed_fraction is not None
        and delayed_fraction < bayes_adequate_limit
        and model_gap is not None
        and model_gap < model_threshold
    )

    evidence = {
        "MODEL_MISMATCH_DOMINANT": (
            -math.inf if model_gap is None else model_gap / model_threshold
        ),
        "IDENTIFIABILITY_DOMINANT": (
            -math.inf if delayed_fraction is None else delayed_fraction / ident_threshold
        ),
        "CONTROL_DESIGN_DOMINANT": (
            -math.inf if isolated_gain is None else isolated_gain / control_threshold
        ),
    }
    triggers = {
        "MODEL_MISMATCH_DOMINANT": model_trigger,
        "IDENTIFIABILITY_DOMINANT": ident_trigger,
        "CONTROL_DESIGN_DOMINANT": control_trigger,
    }
    if not material:
        decision = "PROBLEM_NOT_MATERIAL"
    else:
        active = [label for label, enabled in triggers.items() if enabled]
        tie = {
            "MODEL_MISMATCH_DOMINANT": 0,
            "IDENTIFIABILITY_DOMINANT": 1,
            "CONTROL_DESIGN_DOMINANT": 2,
        }
        candidates = active or list(evidence)
        ranked = sorted(candidates, key=lambda label: (-evidence[label], tie[label]))
        primary = ranked[0]
        secondary_threshold = float(
            thresholds["combined"]["secondary_evidence_min_normalized_score"]
        )
        secondary_candidates = sorted(
            (
                label
                for label in evidence
                if label != primary and evidence[label] >= secondary_threshold
            ),
            key=lambda label: (-evidence[label], tie[label]),
        )
        decision = (
            primary
            if not secondary_candidates
            else f"COMBINED:{primary}+{secondary_candidates[0]}"
        )
    return {
        "decision": decision,
        "problem_material": material,
        "model_gap_b4_vs_b5_fraction": model_gap,
        "bayes_delayed_or_censored_switch_fraction": delayed_fraction,
        "best_isolated_control_gain_fraction": isolated_gain,
        "triggered_bottlenecks": triggers,
        "normalized_evidence_scores": evidence,
        "thresholds": thresholds,
    }


def write_evidence_tables(
    paths: PhaseB1Paths,
    *,
    episodes: pd.DataFrame,
    audits: Mapping[str, pd.DataFrame],
    solver: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    output = paths.results_root / "tables"
    output.mkdir(parents=True, exist_ok=True)
    materiality = build_materiality_table(episodes, paths)
    gap = build_oracle_gap_table(episodes)
    control = build_control_decomposition_table(episodes)
    tests = build_statistical_tests(materiality, gap, control)
    tables: dict[str, pd.DataFrame] = {
        "problem_materiality": materiality,
        "oracle_gap": gap,
        **dict(audits),
        "control_design_decomposition": control,
        "per_episode_metrics": episodes,
        "statistical_tests": tests,
        "solver_metrics": solver,
    }
    for name, frame in tables.items():
        frame.to_csv(output / f"{name}.csv", index=False, lineterminator="\n")
    decision = decide_bottleneck(
        materiality,
        gap,
        audits["identifiability_delay"],
        control,
        paths,
    )
    (output / "bottleneck_decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return tables, decision


__all__ = [
    "AUDIT_TABLE_NAMES",
    "CONTROL_COMPARISONS",
    "REQUIRED_TABLES",
    "build_control_decomposition_table",
    "build_materiality_table",
    "build_oracle_gap_table",
    "build_statistical_tests",
    "collect_final_evidence",
    "decide_bottleneck",
    "write_evidence_tables",
]
