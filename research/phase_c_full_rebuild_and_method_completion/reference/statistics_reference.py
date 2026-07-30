"""Reference paired statistics that avoid mean-of-episode-ratio distortion."""
from __future__ import annotations
import numpy as np


def paired_summary(method: np.ndarray, reference: np.ndarray) -> dict[str, float]:
    method = np.asarray(method, dtype=float)
    reference = np.asarray(reference, dtype=float)
    if method.shape != reference.shape:
        raise ValueError("paired arrays must have identical shapes")
    mask = np.isfinite(method) & np.isfinite(reference)
    m, r = method[mask], reference[mask]
    if len(m) == 0:
        raise ValueError("no finite pairs")
    diff = m - r
    ratio_of_means = float(np.mean(m) / np.mean(r)) if np.mean(r) != 0 else np.nan
    return {
        "n": int(len(m)),
        "mean_method": float(np.mean(m)),
        "mean_reference": float(np.mean(r)),
        "mean_paired_difference": float(np.mean(diff)),
        "median_paired_difference": float(np.median(diff)),
        "ratio_of_aggregate_means": ratio_of_means,
    }


def paired_bootstrap_difference(
    method: np.ndarray,
    reference: np.ndarray,
    *,
    n_boot: int = 5000,
    seed: int = 0,
) -> tuple[float, float, float]:
    m = np.asarray(method, dtype=float)
    r = np.asarray(reference, dtype=float)
    mask = np.isfinite(m) & np.isfinite(r)
    d = m[mask] - r[mask]
    if len(d) == 0:
        raise ValueError("no finite pairs")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(n_boot, len(d)))
    means = d[idx].mean(axis=1)
    return float(d.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))
