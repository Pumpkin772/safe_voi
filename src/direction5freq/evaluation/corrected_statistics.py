"""Corrected paired statistics for Direction5 final repair and decision.

The primary summaries in this module deliberately avoid means of episode-wise
relative ratios.  Methods remain paired within a scenario, design cells receive
equal weight, and uncertainty is resampled hierarchically by design cell and
seed cluster.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


CORE_METRICS = ("frequency_peak_hz", "ace_iae_pu_s", "tie_rms_pu")
DEFAULT_CELL_COLUMNS = ("plant", "mechanism", "sg_tension", "period_s")


def add_design_cell(
    frame: pd.DataFrame,
    columns: Iterable[str] = DEFAULT_CELL_COLUMNS,
) -> pd.DataFrame:
    """Return a copy with an explicit, factor-readable design-cell label."""

    result = frame.copy()
    names = tuple(columns)
    missing = [name for name in names if name not in result.columns]
    if missing:
        raise ValueError(f"missing design-cell columns: {missing}")
    result["design_cell"] = result.loc[:, names].astype(str).agg("|".join, axis=1)
    return result


def _method_wide(
    episodes: pd.DataFrame,
    proposed: str,
    baseline: str,
) -> pd.DataFrame:
    required = {
        "scenario_id", "method", "evaluation_status", "physical_success",
        "seed", *DEFAULT_CELL_COLUMNS, *CORE_METRICS,
    }
    missing = sorted(required.difference(episodes.columns))
    if missing:
        raise ValueError(f"episode table is missing required columns: {missing}")
    selected = add_design_cell(episodes)
    selected = selected[selected.method.isin((proposed, baseline))].copy()
    duplicates = selected.duplicated(("scenario_id", "method"), keep=False)
    if duplicates.any():
        bad = selected.loc[duplicates, ["scenario_id", "method"]]
        raise ValueError(f"duplicate scenario/method rows: {bad.to_dict('records')[:5]}")
    metadata = selected.groupby("scenario_id", sort=True).first()[
        ["seed", "design_cell", *DEFAULT_CELL_COLUMNS]
    ]
    pieces: list[pd.DataFrame] = []
    for column in ("evaluation_status", "physical_success", *CORE_METRICS):
        pivot = selected.pivot(index="scenario_id", columns="method", values=column)
        pivot.columns = [f"{column}__{method}" for method in pivot.columns]
        pieces.append(pivot)
    return metadata.join(pieces, how="outer").reset_index()


def paired_failure_rows(
    episodes: pd.DataFrame,
    proposed: str,
    baseline: str,
) -> pd.DataFrame:
    """Classify every paired scenario before computing continuous metrics."""

    wide = _method_wide(episodes, proposed, baseline)
    p_status = wide.get(f"evaluation_status__{proposed}")
    b_status = wide.get(f"evaluation_status__{baseline}")
    p_success = wide.get(f"physical_success__{proposed}").fillna(False).astype(bool)
    b_success = wide.get(f"physical_success__{baseline}").fillna(False).astype(bool)
    categories: list[str] = []
    for index in range(len(wide)):
        statuses = {str(p_status.iloc[index]), str(b_status.iloc[index])}
        if any("PHYSICALLY_INFEASIBLE" in status for status in statuses):
            category = "physically_infeasible"
        elif any("CONTRACT_VIOLATION" in status for status in statuses):
            category = "contract_violation"
        elif (
            pd.isna(p_status.iloc[index])
            or pd.isna(b_status.iloc[index])
            or p_status.iloc[index] != "EVALUATED"
            or b_status.iloc[index] != "EVALUATED"
        ):
            category = "not_evaluated"
        elif p_success.iloc[index] and b_success.iloc[index]:
            category = "both_success"
        elif not p_success.iloc[index] and b_success.iloc[index]:
            category = "only_proposed_fails"
        elif p_success.iloc[index] and not b_success.iloc[index]:
            category = "only_baseline_fails"
        else:
            category = "both_fail"
        categories.append(category)
    wide["failure_category"] = categories
    return wide


def paired_failure_table(rows: pd.DataFrame) -> pd.DataFrame:
    """Count failure categories overall and by plant without imputing N/E."""

    categories = (
        "both_success", "only_proposed_fails", "only_baseline_fails",
        "both_fail", "not_evaluated", "physically_infeasible",
        "contract_violation",
    )
    records: list[dict[str, object]] = []
    for scope, block in [("ALL", rows), *[(str(p), g) for p, g in rows.groupby("plant")]]:
        counts = block.failure_category.value_counts()
        for category in categories:
            records.append({
                "scope": scope,
                "category": category,
                "scenarios": int(counts.get(category, 0)),
            })
    return pd.DataFrame(records)


def _balanced_means(frame: pd.DataFrame, proposed_col: str, baseline_col: str) -> tuple[float, float]:
    cell_means = frame.groupby("design_cell")[[proposed_col, baseline_col]].mean()
    if cell_means.empty:
        raise ValueError("no design cells available for balanced aggregation")
    return float(cell_means[proposed_col].mean()), float(cell_means[baseline_col].mean())


def metric_pairs(
    failure_rows: pd.DataFrame,
    metric: str,
    proposed: str,
    baseline: str,
    analysis: str,
    penalty_multiplier: float = 2.0,
) -> pd.DataFrame:
    """Build paired values for both-success or failure-aware analysis."""

    p_col = f"{metric}__{proposed}"
    b_col = f"{metric}__{baseline}"
    frame = failure_rows[
        failure_rows.failure_category.isin(
            ("both_success", "only_proposed_fails", "only_baseline_fails", "both_fail")
        )
    ].copy()
    if analysis == "both_success":
        frame = frame[frame.failure_category.eq("both_success")].copy()
        frame["proposed_value"] = pd.to_numeric(frame[p_col], errors="coerce")
        frame["baseline_value"] = pd.to_numeric(frame[b_col], errors="coerce")
        penalty = np.nan
    elif analysis == "failure_aware":
        successful_values: list[np.ndarray] = []
        for method, value_column in ((proposed, p_col), (baseline, b_col)):
            success = frame[f"physical_success__{method}"].fillna(False).astype(bool)
            values = pd.to_numeric(frame.loc[success, value_column], errors="coerce").dropna().to_numpy(float)
            if values.size:
                successful_values.append(values)
        pooled = np.concatenate(successful_values) if successful_values else np.array([1.0])
        penalty = max(float(np.quantile(pooled, 0.95)) * float(penalty_multiplier), 1e-12)
        p_success = frame[f"physical_success__{proposed}"].fillna(False).astype(bool)
        b_success = frame[f"physical_success__{baseline}"].fillna(False).astype(bool)
        p_values = pd.to_numeric(frame[p_col], errors="coerce")
        b_values = pd.to_numeric(frame[b_col], errors="coerce")
        frame["proposed_value"] = np.where(p_success & p_values.notna(), p_values, penalty)
        frame["baseline_value"] = np.where(b_success & b_values.notna(), b_values, penalty)
    else:
        raise ValueError(f"unknown analysis: {analysis}")
    frame = frame[np.isfinite(frame.proposed_value) & np.isfinite(frame.baseline_value)].copy()
    frame["paired_absolute_difference"] = frame.baseline_value - frame.proposed_value
    frame["metric"] = metric
    frame["analysis"] = analysis
    frame["penalty_multiplier"] = float(penalty_multiplier) if analysis == "failure_aware" else np.nan
    frame["penalty_value"] = penalty
    return frame


@dataclass(frozen=True)
class BootstrapSummary:
    absolute_difference_lower: float
    absolute_difference_median: float
    absolute_difference_upper: float
    relative_improvement_lower: float
    relative_improvement_median: float
    relative_improvement_upper: float


def hierarchical_bootstrap(
    pairs: pd.DataFrame,
    *,
    resamples: int = 5000,
    random_seed: int = 20260804,
) -> BootstrapSummary:
    """Resample design cells, then paired seed clusters within sampled cells."""

    if resamples < 100:
        raise ValueError("at least 100 resamples are required")
    required = {"design_cell", "seed", "proposed_value", "baseline_value"}
    missing = sorted(required.difference(pairs.columns))
    if missing:
        raise ValueError(f"bootstrap pairs are missing: {missing}")
    cells = np.asarray(sorted(pairs.design_cell.unique()))
    if not len(cells):
        raise ValueError("no design cells available for bootstrap")
    cell_blocks: list[tuple[np.ndarray, np.ndarray]] = []
    for cell in cells:
        # A seed is the cluster unit.  Pre-aggregation preserves the exact
        # hierarchical estimand while avoiding repeated pandas filtering in
        # every bootstrap draw.
        seed_means = pairs[pairs.design_cell.eq(cell)].groupby("seed")[[
            "proposed_value", "baseline_value"
        ]].mean()
        cell_blocks.append((
            seed_means.proposed_value.to_numpy(float),
            seed_means.baseline_value.to_numpy(float),
        ))
    rng = np.random.default_rng(random_seed)
    absolute = np.empty(resamples)
    relative = np.empty(resamples)
    for iteration in range(resamples):
        sampled_cell_indices = rng.integers(0, len(cells), size=len(cells))
        proposed_cell_means: list[float] = []
        baseline_cell_means: list[float] = []
        for cell_index in sampled_cell_indices:
            p_seed_means, b_seed_means = cell_blocks[int(cell_index)]
            sampled_seed_indices = rng.integers(0, len(p_seed_means), size=len(p_seed_means))
            proposed_cell_means.append(float(np.mean(p_seed_means[sampled_seed_indices])))
            baseline_cell_means.append(float(np.mean(b_seed_means[sampled_seed_indices])))
        proposed_mean = float(np.mean(proposed_cell_means))
        baseline_mean = float(np.mean(baseline_cell_means))
        absolute[iteration] = baseline_mean - proposed_mean
        relative[iteration] = absolute[iteration] / max(abs(baseline_mean), 1e-12)
    quantiles = (0.025, 0.5, 0.975)
    abs_q = np.quantile(absolute, quantiles)
    rel_q = np.quantile(relative, quantiles)
    return BootstrapSummary(*map(float, (*abs_q, *rel_q)))


def corrected_metric_summary(
    failure_rows: pd.DataFrame,
    proposed: str,
    baseline: str,
    *,
    resamples: int = 5000,
    bootstrap_seed: int = 20260804,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return primary summaries, bootstrap intervals and auditable pair rows."""

    summary_rows: list[dict[str, object]] = []
    bootstrap_rows: list[dict[str, object]] = []
    pair_frames: list[pd.DataFrame] = []
    for metric_index, metric in enumerate(CORE_METRICS):
        analyses = [("both_success", np.nan), *(('failure_aware', value) for value in (1.5, 2.0, 3.0))]
        for analysis_index, (analysis, multiplier) in enumerate(analyses):
            effective_multiplier = 2.0 if np.isnan(multiplier) else float(multiplier)
            pairs = metric_pairs(
                failure_rows, metric, proposed, baseline,
                analysis=analysis, penalty_multiplier=effective_multiplier,
            )
            p_mean, b_mean = _balanced_means(pairs, "proposed_value", "baseline_value")
            difference = b_mean - p_mean
            relative = difference / max(abs(b_mean), 1e-12)
            unstable_episode_ratio = float(np.mean(
                (pairs.baseline_value - pairs.proposed_value)
                / np.maximum(np.abs(pairs.baseline_value), 1e-12)
            ))
            summary_rows.append({
                "metric": metric,
                "analysis": analysis,
                "penalty_multiplier": multiplier,
                "paired_scenarios": int(len(pairs)),
                "design_cells": int(pairs.design_cell.nunique()),
                "scenario_balanced_proposed_mean": p_mean,
                "scenario_balanced_baseline_mean": b_mean,
                "paired_absolute_difference": difference,
                "aggregate_mean_relative_improvement": relative,
                "diagnostic_only_mean_episode_relative_ratio": unstable_episode_ratio,
                "primary_metric": analysis == "both_success",
            })
            boot = hierarchical_bootstrap(
                pairs,
                resamples=resamples,
                random_seed=bootstrap_seed + 100 * metric_index + analysis_index,
            )
            bootstrap_rows.append({
                "metric": metric,
                "analysis": analysis,
                "penalty_multiplier": multiplier,
                "resamples": resamples,
                **boot.__dict__,
            })
            pair_frames.append(pairs[[
                "scenario_id", "seed", "design_cell", *DEFAULT_CELL_COLUMNS,
                "failure_category", "metric", "analysis", "penalty_multiplier",
                "penalty_value", "proposed_value", "baseline_value",
                "paired_absolute_difference",
            ]])
    return pd.DataFrame(summary_rows), pd.DataFrame(bootstrap_rows), pd.concat(pair_frames, ignore_index=True)


def solver_denominator_audit(
    episodes: pd.DataFrame,
    normal_episodes: pd.DataFrame,
    cycles: pd.DataFrame,
    proposed: str,
) -> pd.DataFrame:
    """Reconstruct action-outcome and raw-solve denominators for Phase I.

    Plant-A statuses are available per decision.  Native Plant-B stores the
    attempted-decision total in the episode summary.  A fallback is known from
    the frozen controller code to execute both primary and restoration solves;
    an accepted restoration also executes both.  Both denominators are reported
    rather than silently conflated.
    """

    method_cycles = cycles[cycles.method.eq(proposed) & cycles.solver_status.notna()].copy()
    status_counts = method_cycles.solver_status.value_counts()
    accepted = int(status_counts.get("optimal", 0) + status_counts.get("optimal_inaccurate", 0))
    backups = int(status_counts.get("SAFE_FALLBACK", 0))
    preclassified = int(status_counts.get("PHYSICAL_INFEASIBILITY_CERTIFICATE", 0))
    core_native = episodes[(episodes.method.eq(proposed)) & episodes.plant.str.contains("B_native", na=False)]
    native_attempted = int(core_native.controller_calls.sum())
    native_fallback = int(core_native.fallback_calls.sum())
    native_accepted = native_attempted - native_fallback
    core_episodes = episodes[episodes.method.eq(proposed)]
    normal_method = normal_episodes[normal_episodes.method.eq(proposed)]
    reported_solver = int(core_episodes.solver_calls.sum() + normal_method.solver_calls.sum())
    restoration_accepted = int(core_episodes.restoration_calls.sum() + normal_method.restoration_calls.sum())
    unresolved = int(core_episodes.unresolved_math_infeasibility.sum() + normal_method.unresolved_math_infeasibility.sum())
    primary_or_restored_accepted = accepted + native_accepted
    all_backups = backups + native_fallback
    attempted_decisions = primary_or_restored_accepted + all_backups
    primary_accepted = primary_or_restored_accepted - restoration_accepted
    inferred_raw_solve_attempts = primary_accepted + 2 * restoration_accepted + 2 * all_backups
    rows = [
        {"quantity": "primary_accepted_actions", "count": primary_accepted, "included_in_attempted_decision_denominator": True},
        {"quantity": "restoration_accepted_actions", "count": restoration_accepted, "included_in_attempted_decision_denominator": True},
        {"quantity": "backup_actions", "count": all_backups, "included_in_attempted_decision_denominator": True},
        {"quantity": "unhandled_actions", "count": 0, "included_in_attempted_decision_denominator": True},
        {"quantity": "physical_infeasibility_preclassification", "count": preclassified, "included_in_attempted_decision_denominator": False},
        {"quantity": "attempted_optimization_decisions", "count": attempted_decisions, "included_in_attempted_decision_denominator": True},
        {"quantity": "inferred_raw_solver_invocations", "count": inferred_raw_solve_attempts, "included_in_attempted_decision_denominator": False},
        {"quantity": "phase_i_reported_success_only_solver_calls", "count": reported_solver, "included_in_attempted_decision_denominator": False},
        {"quantity": "omitted_backup_actions_in_phase_i_denominator", "count": attempted_decisions - reported_solver, "included_in_attempted_decision_denominator": False},
        {"quantity": "unresolved_mathematical_infeasibility", "count": unresolved, "included_in_attempted_decision_denominator": False},
    ]
    result = pd.DataFrame(rows)
    result["attempted_decision_denominator"] = attempted_decisions
    result["raw_solver_invocation_denominator"] = inferred_raw_solve_attempts
    result["unresolved_fraction_of_attempted_decisions"] = unresolved / max(attempted_decisions, 1)
    result["unresolved_fraction_of_raw_solver_invocations"] = unresolved / max(inferred_raw_solve_attempts, 1)
    result["fallback_fraction_of_attempted_decisions"] = all_backups / max(attempted_decisions, 1)
    return result
