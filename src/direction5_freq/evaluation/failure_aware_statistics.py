"""Registered paired, failure-aware comparison statistics."""

from __future__ import annotations

import numpy as np


def paired_bootstrap_improvement(
    baseline: np.ndarray,
    proposed: np.ndarray,
    *,
    seed: int = 20260803,
    samples: int = 2000,
) -> tuple[float, float, float]:
    baseline_value = np.asarray(baseline, dtype=float)
    proposed_value = np.asarray(proposed, dtype=float)
    if baseline_value.shape != proposed_value.shape or baseline_value.size == 0:
        raise ValueError("paired nonempty arrays with the same shape are required")
    point = 1.0 - float(np.mean(proposed_value)) / max(
        float(np.mean(baseline_value)), 1e-12
    )
    rng = np.random.default_rng(seed)
    draws = np.empty(samples)
    for index in range(samples):
        selected = rng.integers(0, baseline_value.size, baseline_value.size)
        draws[index] = 1.0 - float(np.mean(proposed_value[selected])) / max(
            float(np.mean(baseline_value[selected])), 1e-12
        )
    return point, float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))
