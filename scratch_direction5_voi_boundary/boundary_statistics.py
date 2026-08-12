"""Registered paired, scenario-balanced statistics for boundary validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


CORE_METRICS = (
    "frequency_peak_hz", "ace_iae_pu_s", "tie_iae_pu_s",
    "sg_mechanical_mileage_pu", "bess_energy_throughput_pu_s",
)


@dataclass(frozen=True, slots=True)
class Interval:
    estimate: float
    lower: float
    upper: float


def paired_absolute_differences(
    episodes: pd.DataFrame,
    *,
    tested_method: str = "selective_voi_accr_mpc",
    baseline_method: str = "contract_mpc",
) -> pd.DataFrame:
    keys = ["scenario_id", "design_cell", "plant", "period_s", "known_ood", "seed"]
    selected = episodes.loc[episodes.method.isin((tested_method, baseline_method))]
    if selected.duplicated(keys + ["method"]).any():
        raise ValueError("method/scenario rows must be unique")
    wide = selected.pivot(index=keys, columns="method", values=list(CORE_METRICS)).reset_index()
    rows = []
    for _, source in wide.iterrows():
        row = {name: source[(name, "")] for name in keys}
        for metric in CORE_METRICS:
            # Positive means that the selective method is better (lower cost).
            row[f"improvement__{metric}"] = float(
                source[(metric, baseline_method)] - source[(metric, tested_method)]
            )
        rows.append(row)
    return pd.DataFrame(rows)


def scenario_balanced_mean(values: pd.DataFrame, column: str) -> float:
    return float(values.groupby("design_cell", sort=False)[column].mean().mean())


def hierarchical_bootstrap(
    values: pd.DataFrame,
    column: str,
    *,
    seed: int,
    resamples: int = 10_000,
    family_size: int = 1,
) -> Interval:
    """Resample design cells, then independent seeds within selected cells."""

    cells = tuple(values.design_cell.unique())
    if not cells:
        return Interval(float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    samples = np.empty(resamples)
    for index in range(resamples):
        selected_cells = rng.choice(cells, size=len(cells), replace=True)
        cell_means = []
        for cell in selected_cells:
            rows = values.loc[values.design_cell.eq(cell)]
            seeds = tuple(rows.seed.unique())
            chosen = rng.choice(seeds, size=len(seeds), replace=True)
            seed_means = [float(rows.loc[rows.seed.eq(item), column].mean()) for item in chosen]
            cell_means.append(float(np.mean(seed_means)))
        samples[index] = float(np.mean(cell_means))
    tail = 0.05 / (2.0 * family_size)
    lower, upper = np.quantile(samples, (tail, 1.0 - tail))
    return Interval(scenario_balanced_mean(values, column), float(lower), float(upper))


def value_recovery(
    paired: pd.DataFrame,
    oracle_paired: pd.DataFrame,
    metric: str,
) -> float:
    numerator = scenario_balanced_mean(paired, f"improvement__{metric}")
    denominator = scenario_balanced_mean(oracle_paired, f"improvement__{metric}")
    return float(numerator / denominator) if denominator > 0.0 else float("nan")


def wilson_upper(false_count: int, total: int, z: float = 1.959963984540054) -> float:
    if total <= 0:
        return float("nan")
    proportion = false_count / total
    denominator = 1.0 + z * z / total
    center = proportion + z * z / (2.0 * total)
    radius = z * np.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total))
    return float((center + radius) / denominator)


__all__ = [
    "CORE_METRICS", "Interval", "hierarchical_bootstrap",
    "paired_absolute_differences", "scenario_balanced_mean", "value_recovery",
    "wilson_upper",
]

