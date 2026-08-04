"""Reference statistics for paired, scenario-balanced evaluation.

Do not use mean episode-wise relative ratios as a primary metric.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def aggregate_mean_improvement(df: pd.DataFrame, metric: str, proposed: str, baseline: str) -> float:
    wide = df.pivot(index="scenario_id", columns="method", values=metric).dropna()
    p = float(wide[proposed].mean())
    b = float(wide[baseline].mean())
    return (b - p) / max(abs(b), 1e-12)


def paired_absolute_differences(df: pd.DataFrame, metric: str, proposed: str, baseline: str) -> pd.Series:
    wide = df.pivot(index="scenario_id", columns="method", values=metric).dropna()
    return wide[baseline] - wide[proposed]


def hierarchical_seed_bootstrap(
    paired: pd.DataFrame,
    value_col: str,
    cell_col: str,
    seed_col: str,
    resamples: int = 5000,
    random_seed: int = 20260804,
) -> np.ndarray:
    """Resample design cells, then seed clusters inside each sampled cell."""
    rng = np.random.default_rng(random_seed)
    cells = np.asarray(sorted(paired[cell_col].unique()))
    out = np.empty(resamples)
    for r in range(resamples):
        sampled_cells = rng.choice(cells, size=len(cells), replace=True)
        cell_means = []
        for cell in sampled_cells:
            block = paired[paired[cell_col] == cell]
            seeds = np.asarray(sorted(block[seed_col].unique()))
            sampled_seeds = rng.choice(seeds, size=len(seeds), replace=True)
            vals = []
            for seed in sampled_seeds:
                vals.extend(block.loc[block[seed_col] == seed, value_col].tolist())
            cell_means.append(float(np.mean(vals)))
        out[r] = float(np.mean(cell_means))
    return out
