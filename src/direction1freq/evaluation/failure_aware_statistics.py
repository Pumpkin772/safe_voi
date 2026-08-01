"""Success-first paired statistics with explicit missing-evaluation handling."""

from __future__ import annotations

import numpy as np
import pandas as pd


def paired_failure_counts(
    baseline: pd.DataFrame,
    proposed: pd.DataFrame,
    *,
    success_column: str = "physical_success",
) -> dict[str, int]:
    """Count mutually exclusive paired outcomes without coercing missing rows."""

    common = baseline.index.intersection(proposed.index)
    b = baseline.loc[common, success_column].astype(bool)
    p = proposed.loc[common, success_column].astype(bool)
    return {
        "both_success": int((b & p).sum()),
        "only_proposed_fails": int((b & ~p).sum()),
        "only_baseline_fails": int((~b & p).sum()),
        "both_fail": int((~b & ~p).sum()),
        "not_evaluated": int(len(baseline.index.union(proposed.index)) - len(common)),
    }


def aggregate_mean_improvement(baseline: np.ndarray, proposed: np.ndarray) -> float:
    """Return 1-mean(proposed)/mean(baseline), never mean episode ratios."""

    baseline_array = np.asarray(baseline, dtype=float)
    proposed_array = np.asarray(proposed, dtype=float)
    if baseline_array.shape != proposed_array.shape:
        raise ValueError("paired arrays must have the same shape")
    if not len(baseline_array):
        return float("nan")
    denominator = float(np.mean(baseline_array))
    if abs(denominator) <= 1e-15:
        return float("nan")
    return 1.0 - float(np.mean(proposed_array)) / denominator


def paired_bootstrap_improvement(
    baseline: np.ndarray,
    proposed: np.ndarray,
    *,
    clusters: np.ndarray | None = None,
    samples: int = 2000,
    seed: int = 20260801,
) -> tuple[float, float, float]:
    """Cluster bootstrap of the aggregate-mean improvement."""

    b = np.asarray(baseline, dtype=float)
    p = np.asarray(proposed, dtype=float)
    if b.shape != p.shape:
        raise ValueError("paired arrays must have the same shape")
    if len(b) < 2:
        return float("nan"), float("nan"), float("nan")
    labels = np.arange(len(b)) if clusters is None else np.asarray(clusters)
    if labels.shape != b.shape:
        raise ValueError("clusters must match paired arrays")
    unique = np.unique(labels)
    rng = np.random.default_rng(seed)
    values = np.empty(samples)
    for draw in range(samples):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        indices = np.concatenate([np.flatnonzero(labels == item) for item in sampled])
        values[draw] = aggregate_mean_improvement(b[indices], p[indices])
    point = aggregate_mean_improvement(b, p)
    return point, float(np.nanquantile(values, 0.025)), float(
        np.nanquantile(values, 0.975)
    )

