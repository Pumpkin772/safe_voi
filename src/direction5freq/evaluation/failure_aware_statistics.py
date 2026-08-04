"""Paired, failure-aware and cluster-bootstrap statistics."""

from __future__ import annotations

import numpy as np
import pandas as pd


CORE_METRICS = ("frequency_peak_hz", "ace_iae_pu_s", "tie_rms_pu")


def compare_against_baseline(
    episodes: pd.DataFrame,
    proposed: str = "dcsv_mpc",
    baseline: str = "fixed_allocation_pi",
    bootstrap_seed: int = 20260804,
    resamples: int = 2000,
) -> tuple[pd.DataFrame, dict[str, float | bool]]:
    eligible = episodes[
        episodes.evaluation_status.eq("EVALUATED")
        & episodes.method.isin([proposed, baseline])
    ].copy()
    wide = eligible.pivot(index="scenario_id", columns="method")
    common = wide.index
    if len(common) == 0:
        raise ValueError("no paired evaluated scenarios")
    proposed_success = wide["physical_success"][proposed].astype(bool)
    baseline_success = wide["physical_success"][baseline].astype(bool)
    success_difference = float(proposed_success.mean() - baseline_success.mean())
    rng = np.random.default_rng(bootstrap_seed)
    rows = []
    failure_aware_proposed = 0.0
    failure_aware_baseline = 0.0
    for metric in CORE_METRICS:
        p = wide[metric][proposed].to_numpy(float)
        b = wide[metric][baseline].to_numpy(float)
        finite = np.isfinite(p) & np.isfinite(b)
        scale = float(np.nanquantile(np.r_[p[finite], b[finite]], 0.95)) if finite.any() else 1.0
        penalty = max(scale * 2.0, 1e-9)
        p_fa = np.where(proposed_success.to_numpy() & np.isfinite(p), p, penalty)
        b_fa = np.where(baseline_success.to_numpy() & np.isfinite(b), b, penalty)
        failure_aware_proposed += float(np.mean(p_fa / penalty))
        failure_aware_baseline += float(np.mean(b_fa / penalty))
        denominator = np.maximum(np.abs(b_fa), 1e-9)
        improvement = (b_fa - p_fa) / denominator
        boot = np.empty(resamples)
        for index in range(resamples):
            sample = rng.integers(0, len(improvement), size=len(improvement))
            boot[index] = float(np.mean(improvement[sample]))
        rows.append({
            "metric": metric,
            "paired_scenarios": len(improvement),
            "proposed_failure_aware_mean": float(np.mean(p_fa)),
            "baseline_failure_aware_mean": float(np.mean(b_fa)),
            "mean_relative_improvement": float(np.mean(improvement)),
            "cluster_bootstrap_ci_lower": float(np.quantile(boot, 0.025)),
            "cluster_bootstrap_ci_upper": float(np.quantile(boot, 0.975)),
            "improves_at_least_8_percent": bool(np.mean(improvement) >= 0.08),
            "positive_ci_lower": bool(np.quantile(boot, 0.025) > 0.0),
        })
    statistics = pd.DataFrame(rows)
    summary = {
        "paired_scenarios": int(len(common)),
        "proposed_success_rate": float(proposed_success.mean()),
        "baseline_success_rate": float(baseline_success.mean()),
        "success_rate_difference": success_difference,
        "success_drop_at_most_2pp": bool(success_difference >= -0.02),
        "proposed_failure_aware_score": failure_aware_proposed / len(CORE_METRICS),
        "baseline_failure_aware_score": failure_aware_baseline / len(CORE_METRICS),
        "failure_aware_not_worse": bool(failure_aware_proposed <= failure_aware_baseline + 1e-12),
        "core_metrics_passing": int((statistics.improves_at_least_8_percent & statistics.positive_ci_lower).sum()),
    }
    return statistics, summary
