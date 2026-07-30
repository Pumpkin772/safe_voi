"""Success-first, scenario-balanced statistics for Phase B2.

The helpers in this module intentionally never average episode-wise relative
ratios and never rank inactive bottleneck triggers.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from d5freq.evaluation.statistics import sign_flip_permutation_test


PAIR_KEYS = ("scenario_id", "seed", "sg_level")
CONTROL_COMPARISONS = (
    ("C1_true_arx_worst", "C0_true_arx_expected", "worst_mode_cost_penalty"),
    (
        "C2_perfect_belief_current_mpc",
        "C1_true_arx_worst",
        "constraint_tightening_penalty",
    ),
    ("C3_current_belief_expected", "P_old", "remove_worst_mode_cost"),
    ("C4_gradual_authority", "P_old", "replace_binary_fallback"),
    ("C5_no_sticky_prior", "P_old", "remove_sticky_prior"),
    ("C2_perfect_belief_current_mpc", "P_old", "perfect_belief_total_gap"),
)


@dataclass(frozen=True, slots=True)
class ScenarioBalancedEffect:
    method_mean: float | None
    reference_mean: float | None
    absolute_effect: float | None
    relative_effect: float | None
    absolute_ci95_low: float | None
    absolute_ci95_high: float | None
    relative_ci95_low: float | None
    relative_ci95_high: float | None
    scenario_count: int
    observation_count: int
    sign_flip_pvalue: float | None


def _coerce_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series.dtype):
        return series.fillna(False).astype(bool)
    lowered = series.astype("string").str.strip().str.lower()
    mapped = lowered.map(
        {
            "true": True,
            "false": False,
            "1": True,
            "0": False,
            "yes": True,
            "no": False,
        }
    )
    numeric = pd.to_numeric(series, errors="coerce")
    mapped = mapped.where(mapped.notna(), numeric.ne(0).where(numeric.notna()))
    return mapped.fillna(False).astype(bool)


def strict_bottleneck_decision(
    *,
    problem_material: bool,
    triggers: Mapping[str, bool],
    normalized_scores: Mapping[str, float],
) -> str:
    """Return a decision using active triggers only."""

    if not problem_material:
        return "PROBLEM_NOT_MATERIAL"
    active = [name for name, value in triggers.items() if bool(value)]
    if not active:
        return "INCONCLUSIVE_REQUIRES_MORE_EVIDENCE"
    active.sort(key=lambda name: (-float(normalized_scores[name]), name))
    if len(active) == 1:
        return active[0]
    return f"COMBINED:{active[0]}+{active[1]}"


def add_total_cost_columns(
    episodes: pd.DataFrame,
    *,
    ratios: Sequence[float],
    sg_energy_weight: float,
    sg_mileage_weight: float,
) -> tuple[pd.DataFrame, dict[float, str]]:
    """Add normalized total costs containing both SG and IBR effort."""

    required = {
        "sg_abs_energy_pu_s",
        "ibr_abs_energy_pu_s",
        "sg_mileage",
        "ibr_mileage",
    }
    missing = required - set(episodes.columns)
    if missing:
        raise KeyError(f"missing cost columns: {sorted(missing)}")
    output = episodes.copy()
    numeric = {
        name: pd.to_numeric(output[name], errors="coerce") for name in sorted(required)
    }
    columns: dict[float, str] = {}
    for ratio in ratios:
        ratio_value = float(ratio)
        if not math.isfinite(ratio_value) or ratio_value <= 0.0:
            raise ValueError("IBR-to-SG cost ratios must be positive and finite")
        token = f"{ratio_value:g}".replace(".", "p")
        name = f"total_cost_ratio_{token}"
        output[name] = (
            float(sg_energy_weight) * numeric["sg_abs_energy_pu_s"]
            + ratio_value * float(sg_energy_weight) * numeric["ibr_abs_energy_pu_s"]
            + float(sg_mileage_weight) * numeric["sg_mileage"]
            + ratio_value * float(sg_mileage_weight) * numeric["ibr_mileage"]
        )
        columns[ratio_value] = name
    return output, columns


def pair_methods(
    episodes: pd.DataFrame,
    *,
    method: str,
    reference: str,
    metrics: Iterable[str],
    keys: Sequence[str] = PAIR_KEYS,
) -> pd.DataFrame:
    """Outer-pair two methods and retain every missing or failed outcome."""

    keys = tuple(keys)
    metrics = tuple(dict.fromkeys(metrics))
    required = {
        *keys,
        "method",
        "scientific_success",
        "catastrophic_failure",
        *metrics,
    }
    missing = required - set(episodes.columns)
    if missing:
        raise KeyError(f"missing pairing columns: {sorted(missing)}")
    subset = episodes.loc[
        episodes["method"].isin((method, reference)),
        [*keys, "method", "scientific_success", "catastrophic_failure", *metrics],
    ].copy()
    if subset.duplicated([*keys, "method"]).any():
        raise ValueError("method evidence is not unique on the registered pairing keys")
    left = subset.loc[subset["method"] == method].drop(columns="method")
    right = subset.loc[subset["method"] == reference].drop(columns="method")
    paired = left.merge(
        right,
        on=list(keys),
        how="outer",
        suffixes=("_method", "_reference"),
        indicator=True,
        validate="one_to_one",
    )
    paired.insert(0, "method", method)
    paired.insert(1, "reference_method", reference)
    paired["method_present"] = paired["_merge"].isin(("left_only", "both"))
    paired["reference_present"] = paired["_merge"].isin(("right_only", "both"))
    method_success = _coerce_bool(paired["scientific_success_method"]) & paired[
        "method_present"
    ]
    reference_success = _coerce_bool(
        paired["scientific_success_reference"]
    ) & paired["reference_present"]
    paired["method_success"] = method_success
    paired["reference_success"] = reference_success
    paired["both_success"] = method_success & reference_success
    paired["method_only_failure"] = (~method_success) & reference_success
    paired["reference_only_failure"] = method_success & (~reference_success)
    paired["both_failure"] = (~method_success) & (~reference_success)
    paired["method_safety_failure"] = (
        _coerce_bool(paired["catastrophic_failure_method"])
        | (~paired["method_present"])
    )
    paired["reference_safety_failure"] = (
        _coerce_bool(paired["catastrophic_failure_reference"])
        | (~paired["reference_present"])
    )
    return paired.drop(columns="_merge")


def _scenario_means(
    frame: pd.DataFrame,
    *,
    method_col: str,
    reference_col: str,
    strata: Sequence[str],
) -> pd.DataFrame:
    numeric = frame[[*strata, method_col, reference_col]].copy()
    numeric[method_col] = pd.to_numeric(numeric[method_col], errors="coerce")
    numeric[reference_col] = pd.to_numeric(numeric[reference_col], errors="coerce")
    numeric = numeric.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[method_col, reference_col]
    )
    return numeric.groupby(list(strata), sort=True, dropna=False)[
        [method_col, reference_col]
    ].mean()


def scenario_balanced_effect(
    paired: pd.DataFrame,
    *,
    method_col: str,
    reference_col: str,
    strata: Sequence[str] = ("scenario_id",),
    eligible: pd.Series | np.ndarray | None = None,
    epsilon: float = 1.0e-8,
    bootstrap_resamples: int = 10000,
    bootstrap_seed: int = 0,
) -> ScenarioBalancedEffect:
    """Estimate a paired effect as a ratio of scenario-balanced means."""

    if eligible is None:
        selected = paired
    else:
        mask = np.asarray(eligible, dtype=bool)
        if mask.size != len(paired):
            raise ValueError("eligible mask length does not match paired evidence")
        selected = paired.loc[mask]
    means = _scenario_means(
        selected,
        method_col=method_col,
        reference_col=reference_col,
        strata=strata,
    )
    if means.empty:
        return ScenarioBalancedEffect(
            None, None, None, None, None, None, None, None, 0, 0, None
        )
    method_mean = float(means[method_col].mean())
    reference_mean = float(means[reference_col].mean())
    absolute = method_mean - reference_mean
    relative = absolute / max(abs(reference_mean), float(epsilon))
    absolute_low = absolute_high = relative_low = relative_high = None
    if bootstrap_resamples > 0:
        rng = np.random.default_rng(int(bootstrap_seed))
        method_values = means[method_col].to_numpy(float)
        reference_values = means[reference_col].to_numpy(float)
        indices = rng.integers(
            0,
            len(means),
            size=(int(bootstrap_resamples), len(means)),
            endpoint=False,
        )
        method_boot = method_values[indices].mean(axis=1)
        reference_boot = reference_values[indices].mean(axis=1)
        absolute_boot = method_boot - reference_boot
        relative_boot = absolute_boot / np.maximum(
            np.abs(reference_boot), float(epsilon)
        )
        absolute_low, absolute_high = (
            float(value) for value in np.quantile(absolute_boot, (0.025, 0.975))
        )
        relative_low, relative_high = (
            float(value) for value in np.quantile(relative_boot, (0.025, 0.975))
        )
    scenario_differences = (
        means[method_col].to_numpy(float) - means[reference_col].to_numpy(float)
    )
    sign = sign_flip_permutation_test(
        scenario_differences,
        rng_seed=int(bootstrap_seed) + 1,
        n_resamples=max(int(bootstrap_resamples), 1000),
    )
    return ScenarioBalancedEffect(
        method_mean=method_mean,
        reference_mean=reference_mean,
        absolute_effect=absolute,
        relative_effect=relative,
        absolute_ci95_low=absolute_low,
        absolute_ci95_high=absolute_high,
        relative_ci95_low=relative_low,
        relative_ci95_high=relative_high,
        scenario_count=int(len(means)),
        observation_count=int(len(selected)),
        sign_flip_pvalue=float(sign.pvalue),
    )


def _balanced_rate(
    frame: pd.DataFrame, column: str, *, strata: Sequence[str]
) -> float:
    if frame.empty:
        return float("nan")
    values = _coerce_bool(frame[column]).astype(float)
    temporary = frame.loc[:, list(strata)].copy()
    temporary["value"] = values.to_numpy(float)
    return float(
        temporary.groupby(list(strata), sort=True, dropna=False)["value"]
        .mean()
        .mean()
    )


def summarize_metric(
    paired: pd.DataFrame,
    *,
    metric: str,
    strata: Sequence[str],
    bootstrap_resamples: int,
    bootstrap_seed: int,
    failure_penalty_multiplier: float,
) -> dict[str, Any]:
    method_col = f"{metric}_method"
    reference_col = f"{metric}_reference"
    method_values = pd.to_numeric(paired[method_col], errors="coerce")
    reference_values = pd.to_numeric(paired[reference_col], errors="coerce")
    finite = np.isfinite(method_values.to_numpy(float)) & np.isfinite(
        reference_values.to_numpy(float)
    )
    both_success = _coerce_bool(paired["both_success"]).to_numpy(bool)
    eligible = finite & both_success
    effect = scenario_balanced_effect(
        paired,
        method_col=method_col,
        reference_col=reference_col,
        strata=strata,
        eligible=eligible,
        bootstrap_resamples=bootstrap_resamples,
        bootstrap_seed=bootstrap_seed,
    )
    episode_ratios = np.divide(
        method_values.to_numpy(float) - reference_values.to_numpy(float),
        reference_values.to_numpy(float),
        out=np.full(len(paired), np.nan),
        where=np.abs(reference_values.to_numpy(float)) > 1.0e-12,
    )
    episode_ratio_mean = (
        None
        if not np.isfinite(episode_ratios[eligible]).any()
        else float(np.nanmean(episode_ratios[eligible]))
    )
    combined = np.concatenate(
        (
            method_values[np.isfinite(method_values)].to_numpy(float),
            reference_values[np.isfinite(reference_values)].to_numpy(float),
        )
    )
    penalty = (
        1.0
        if combined.size == 0
        else max(float(np.max(combined)), 1.0e-9) * float(failure_penalty_multiplier)
    )
    penalized = paired.copy()
    penalized[method_col] = method_values.where(
        _coerce_bool(paired["method_success"]) & np.isfinite(method_values), penalty
    )
    penalized[reference_col] = reference_values.where(
        _coerce_bool(paired["reference_success"]) & np.isfinite(reference_values),
        penalty,
    )
    penalty_effect = scenario_balanced_effect(
        penalized,
        method_col=method_col,
        reference_col=reference_col,
        strata=strata,
        bootstrap_resamples=bootstrap_resamples,
        bootstrap_seed=bootstrap_seed + 17,
    )
    outcome_counts = {
        name: int(_coerce_bool(paired[name]).sum())
        for name in (
            "both_success",
            "method_only_failure",
            "reference_only_failure",
            "both_failure",
        )
    }
    method_failure_rate = _balanced_rate(
        paired.assign(method_failure=~_coerce_bool(paired["method_success"])),
        "method_failure",
        strata=strata,
    )
    reference_failure_rate = _balanced_rate(
        paired.assign(reference_failure=~_coerce_bool(paired["reference_success"])),
        "reference_failure",
        strata=strata,
    )
    method_safety_rate = _balanced_rate(
        paired, "method_safety_failure", strata=strata
    )
    reference_safety_rate = _balanced_rate(
        paired, "reference_safety_failure", strata=strata
    )
    return {
        "attempted_pair_count": int(len(paired)),
        **outcome_counts,
        "method_failure_rate": method_failure_rate,
        "reference_failure_rate": reference_failure_rate,
        "failure_rate_difference": method_failure_rate - reference_failure_rate,
        "method_safety_failure_rate": method_safety_rate,
        "reference_safety_failure_rate": reference_safety_rate,
        "safety_failure_rate_difference": method_safety_rate - reference_safety_rate,
        "common_success_pair_count": effect.observation_count,
        "scenario_count": effect.scenario_count,
        "method_scenario_balanced_mean": effect.method_mean,
        "reference_scenario_balanced_mean": effect.reference_mean,
        "scenario_balanced_absolute_effect": effect.absolute_effect,
        "scenario_balanced_relative_effect": effect.relative_effect,
        "absolute_ci95_low": effect.absolute_ci95_low,
        "absolute_ci95_high": effect.absolute_ci95_high,
        "relative_ci95_low": effect.relative_ci95_low,
        "relative_ci95_high": effect.relative_ci95_high,
        "sign_flip_pvalue": effect.sign_flip_pvalue,
        "episode_ratio_mean_diagnostic_only": episode_ratio_mean,
        "episode_ratio_minus_primary": (
            None
            if episode_ratio_mean is None or effect.relative_effect is None
            else episode_ratio_mean - effect.relative_effect
        ),
        "failure_penalty_value": penalty,
        "penalized_method_mean": penalty_effect.method_mean,
        "penalized_reference_mean": penalty_effect.reference_mean,
        "penalized_relative_effect": penalty_effect.relative_effect,
        "primary_estimator": "scenario_balanced_paired_difference_and_ratio_of_means",
    }


def build_corrected_comparison_table(
    episodes: pd.DataFrame,
    *,
    comparisons: Sequence[tuple[str, str, str]],
    metrics: Sequence[str],
    bootstrap_resamples: int,
    bootstrap_seed: int,
    failure_penalty_multiplier: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    counter = 0
    for method, reference, factor in comparisons:
        paired = pair_methods(
            episodes,
            method=method,
            reference=reference,
            metrics=metrics,
        )
        for level in ("ALL", "A", "B", "C"):
            selected = paired if level == "ALL" else paired.loc[paired["sg_level"] == level]
            strata = ("sg_level", "scenario_id") if level == "ALL" else ("scenario_id",)
            for metric in metrics:
                summary = summarize_metric(
                    selected,
                    metric=metric,
                    strata=strata,
                    bootstrap_resamples=bootstrap_resamples,
                    bootstrap_seed=bootstrap_seed + counter * 101,
                    failure_penalty_multiplier=failure_penalty_multiplier,
                )
                counter += 1
                rows.append(
                    {
                        "scope": "overall",
                        "scenario_id": "ALL",
                        "sg_level": level,
                        "factor": factor,
                        "method": method,
                        "reference_method": reference,
                        "metric": metric,
                        **summary,
                    }
                )
            if level == "ALL":
                continue
            for scenario_id in sorted(selected["scenario_id"].dropna().unique()):
                scenario = selected.loc[selected["scenario_id"] == scenario_id]
                for metric in metrics:
                    summary = summarize_metric(
                        scenario,
                        metric=metric,
                        strata=("scenario_id",),
                        bootstrap_resamples=0,
                        bootstrap_seed=bootstrap_seed + counter * 101,
                        failure_penalty_multiplier=failure_penalty_multiplier,
                    )
                    counter += 1
                    rows.append(
                        {
                            "scope": "scenario",
                            "scenario_id": scenario_id,
                            "sg_level": level,
                            "factor": factor,
                            "method": method,
                            "reference_method": reference,
                            "metric": metric,
                            **summary,
                        }
                    )
    return pd.DataFrame.from_records(rows)


def build_paired_failure_outcomes(
    episodes: pd.DataFrame,
    comparisons: Sequence[tuple[str, str, str]],
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for method, reference, factor in comparisons:
        paired = pair_methods(
            episodes,
            method=method,
            reference=reference,
            metrics=(),
        )
        selected = paired[
            [
                *PAIR_KEYS,
                "method",
                "reference_method",
                "method_present",
                "reference_present",
                "method_success",
                "reference_success",
                "both_success",
                "method_only_failure",
                "reference_only_failure",
                "both_failure",
                "method_safety_failure",
                "reference_safety_failure",
            ]
        ].copy()
        selected.insert(2, "factor", factor)
        rows.append(selected)
    return pd.concat(rows, ignore_index=True)


def build_corrected_materiality_table(
    comparison: pd.DataFrame,
    *,
    cost_columns: Mapping[float, str],
    thresholds: Mapping[str, Any],
    b5_classification: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for level in ("A", "B", "C"):
        overall = comparison.loc[
            (comparison["scope"] == "overall")
            & (comparison["sg_level"] == level)
        ]
        iae = overall.loc[overall["metric"] == "freq_iae"].iloc[0]
        maximum = overall.loc[overall["metric"] == "max_abs_freq_hz"].iloc[0]
        provisional: list[dict[str, Any]] = []
        for ratio, column in cost_columns.items():
            cost = overall.loc[overall["metric"] == column].iloc[0]
            failure_ok = float(iae["failure_rate_difference"]) <= float(
                thresholds["failure_rate_noninferiority_tolerance"]
            )
            safety_ok = float(iae["safety_failure_rate_difference"]) <= float(
                thresholds["safety_rate_noninferiority_tolerance"]
            )
            iae_improvement = -float(iae["scenario_balanced_relative_effect"])
            max_improvement = -float(maximum["scenario_balanced_relative_effect"])
            cost_improvement = -float(cost["scenario_balanced_relative_effect"])
            frequency_value = bool(
                failure_ok
                and safety_ok
                and max(iae_improvement, max_improvement)
                >= float(thresholds["frequency_improvement_min_fraction"])
                and -cost_improvement
                <= float(thresholds["total_cost_noninferiority_tolerance_fraction"])
            )
            cost_value = bool(
                failure_ok
                and safety_ok
                and -iae_improvement
                <= float(thresholds["frequency_noninferiority_tolerance_fraction"])
                and cost_improvement
                >= float(thresholds["total_cost_improvement_min_fraction"])
            )
            provisional.append(
                {
                    "sg_level": level,
                    "cost_ratio_ibr_to_sg": ratio,
                    "attempted_pair_count": int(iae["attempted_pair_count"]),
                    "both_success": int(iae["both_success"]),
                    "method_only_failure": int(iae["method_only_failure"]),
                    "reference_only_failure": int(iae["reference_only_failure"]),
                    "both_failure": int(iae["both_failure"]),
                    "b5_failure_rate": float(iae["method_failure_rate"]),
                    "b0_failure_rate": float(iae["reference_failure_rate"]),
                    "failure_rate_difference": float(iae["failure_rate_difference"]),
                    "safety_rate_difference": float(
                        iae["safety_failure_rate_difference"]
                    ),
                    "frequency_iae_improvement_fraction": iae_improvement,
                    "frequency_iae_ci95_low": -float(iae["relative_ci95_high"]),
                    "frequency_iae_ci95_high": -float(iae["relative_ci95_low"]),
                    "max_frequency_improvement_fraction": max_improvement,
                    "total_cost_improvement_fraction": cost_improvement,
                    "penalized_frequency_iae_improvement_fraction": -float(
                        iae["penalized_relative_effect"]
                    ),
                    "failure_noninferior": failure_ok,
                    "safety_noninferior": safety_ok,
                    "frequency_value_candidate": frequency_value,
                    "cost_value_candidate": cost_value,
                    "candidate_gate": frequency_value or cost_value,
                    "b5_benchmark_classification": b5_classification,
                    "b5_is_exact_optimal_oracle": False,
                }
            )
        support = sum(bool(row["candidate_gate"]) for row in provisional)
        material = support >= int(thresholds["minimum_supporting_cost_ratios"])
        for row in provisional:
            row["supporting_cost_ratio_count"] = support
            row["materiality_gate_passed"] = material
            row["interpretation"] = (
                "candidate_materiality_but_b5_not_a_credible_optimal_ceiling"
                if material
                else "materiality_not_established_by_corrected_phase_b1"
            )
            rows.append(row)
    return pd.DataFrame.from_records(rows)


def build_corrected_phase_b1_decision(
    *,
    materiality: pd.DataFrame,
    oracle_gap: pd.DataFrame,
    control: pd.DataFrame,
    identifiability: pd.DataFrame,
    original_decision: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    b5_classification: str,
) -> dict[str, Any]:
    model_row = oracle_gap.loc[
        (oracle_gap["scope"] == "overall")
        & (oracle_gap["sg_level"] == "ALL")
        & (oracle_gap["metric"] == "freq_iae")
    ].iloc[0]
    model_gap = max(0.0, float(model_row["scenario_balanced_relative_effect"]))
    model_failure_ok = float(model_row["failure_rate_difference"]) <= 0.0
    model_trigger = bool(
        model_failure_ok
        and model_gap >= float(thresholds["model_mismatch_min_fraction"])
    )

    truth = _coerce_bool(identifiability["candidate_set_contains_truth"])
    bayes = identifiability.loc[
        identifiability["classifier"].eq(
            "evaluation_only_bayes_correct_candidates"
        )
        & truth
    ].copy()
    delayed = _coerce_bool(bayes["detection_censored"]) | (
        pd.to_numeric(bayes["detection_delay_s"], errors="coerce")
        > float(thresholds["critical_window_s"])
    )
    delayed_fraction = None if bayes.empty else float(delayed.mean())
    ident_trigger = bool(
        delayed_fraction is not None
        and delayed_fraction
        >= float(thresholds["delayed_or_censored_fraction_min"])
        and model_gap < float(thresholds["model_mismatch_min_fraction"])
    )

    isolated = control.loc[
        (control["scope"] == "overall")
        & (control["sg_level"] == "ALL")
        & (control["metric"] == "freq_iae")
        & control["factor"].isin(
            ("remove_worst_mode_cost", "replace_binary_fallback", "remove_sticky_prior")
        )
    ].copy()
    isolated["eligible_success_first"] = (
        pd.to_numeric(isolated["failure_rate_difference"], errors="coerce") <= 0.0
    ) & (
        pd.to_numeric(isolated["safety_failure_rate_difference"], errors="coerce")
        <= 0.0
    )
    eligible = isolated.loc[isolated["eligible_success_first"]]
    gains = -pd.to_numeric(
        eligible["scenario_balanced_relative_effect"], errors="coerce"
    )
    best_control_gain = 0.0 if gains.dropna().empty else max(0.0, float(gains.max()))
    control_trigger = bool(
        best_control_gain
        >= float(thresholds["isolated_control_gain_min_fraction"])
        and delayed_fraction is not None
        and delayed_fraction < float(thresholds["bayes_adequate_max_fraction"])
        and model_gap < float(thresholds["model_mismatch_min_fraction"])
    )
    triggers = {
        "MODEL_MISMATCH_DOMINANT": model_trigger,
        "IDENTIFIABILITY_DOMINANT": ident_trigger,
        "CONTROL_DESIGN_DOMINANT": control_trigger,
    }
    scores = {
        "MODEL_MISMATCH_DOMINANT": model_gap
        / float(thresholds["model_mismatch_min_fraction"]),
        "IDENTIFIABILITY_DOMINANT": (
            0.0
            if delayed_fraction is None
            else delayed_fraction
            / float(thresholds["delayed_or_censored_fraction_min"])
        ),
        "CONTROL_DESIGN_DOMINANT": best_control_gain
        / float(thresholds["isolated_control_gain_min_fraction"]),
    }
    active = [name for name, value in triggers.items() if value]
    if not active:
        corrected = "INCONCLUSIVE_NO_DOMINANT_BOTTLENECK"
        strict_mapping = "INCONCLUSIVE_REQUIRES_MORE_EVIDENCE"
    else:
        strict_mapping = strict_bottleneck_decision(
            problem_material=True,
            triggers=triggers,
            normalized_scores=scores,
        )
        corrected = strict_mapping
    return {
        "schema_version": "d5freq.phase_b2.corrected_phase_b1_decision.v1",
        "analysis_source": "existing_phase_b1_csv_only_no_episode_rerun",
        "original_phase_b1_decision": original_decision.get("decision"),
        "original_triggered_bottlenecks": original_decision.get(
            "triggered_bottlenecks"
        ),
        "corrected_phase_b1_decision": corrected,
        "strict_protocol_mapping": strict_mapping,
        "corrected_materiality_gate_any": bool(
            _coerce_bool(materiality["materiality_gate_passed"]).any()
        ),
        "materiality_status": "INCONCLUSIVE_WEAK_B5_BENCHMARK",
        "b5_benchmark_classification": b5_classification,
        "b5_is_exact_optimal_oracle": False,
        "model_gap_fraction": model_gap,
        "bayes_delayed_or_censored_fraction": delayed_fraction,
        "best_success_first_isolated_control_gain_fraction": best_control_gain,
        "triggers": triggers,
        "active_triggers": active,
        "normalized_scores": scores,
        "thresholds": dict(thresholds),
        "decision_rule": "no_fallback_ranking_and_combined_uses_active_triggers_only",
    }


__all__ = [
    "CONTROL_COMPARISONS",
    "PAIR_KEYS",
    "ScenarioBalancedEffect",
    "add_total_cost_columns",
    "build_corrected_comparison_table",
    "build_corrected_materiality_table",
    "build_corrected_phase_b1_decision",
    "build_paired_failure_outcomes",
    "pair_methods",
    "scenario_balanced_effect",
    "strict_bottleneck_decision",
    "summarize_metric",
]
