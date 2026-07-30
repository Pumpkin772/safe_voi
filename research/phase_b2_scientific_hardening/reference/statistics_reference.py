"""Reference-only Phase B2 statistics helpers.

Codex may adapt this file, but production code must add validation, tests, and
project schemas. The key rule is: do not average per-episode ratios and do not
force a bottleneck when no preregistered trigger is active.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Effect:
    absolute: float
    relative: float
    method_mean: float
    reference_mean: float
    scenario_count: int


def scenario_balanced_effect(
    paired: pd.DataFrame,
    *,
    method_col: str,
    reference_col: str,
    scenario_col: str = "scenario_id",
    epsilon: float = 1e-8,
) -> Effect:
    """Ratio of scenario-balanced means, never mean of episode-wise ratios."""
    required = {method_col, reference_col, scenario_col}
    missing = required - set(paired.columns)
    if missing:
        raise KeyError(f"missing columns: {sorted(missing)}")
    clean = paired[[scenario_col, method_col, reference_col]].copy()
    clean[method_col] = pd.to_numeric(clean[method_col], errors="coerce")
    clean[reference_col] = pd.to_numeric(clean[reference_col], errors="coerce")
    clean = clean.replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        raise ValueError("no finite paired observations")
    by_scenario = clean.groupby(scenario_col, sort=True)[[method_col, reference_col]].mean()
    method_mean = float(by_scenario[method_col].mean())
    reference_mean = float(by_scenario[reference_col].mean())
    absolute = method_mean - reference_mean
    relative = absolute / max(abs(reference_mean), epsilon)
    return Effect(
        absolute=absolute,
        relative=relative,
        method_mean=method_mean,
        reference_mean=reference_mean,
        scenario_count=int(len(by_scenario)),
    )


def paired_failure_table(
    frame: pd.DataFrame,
    *,
    method: str,
    reference: str,
    keys: Iterable[str] = ("scenario_id", "seed", "sg_level"),
) -> pd.DataFrame:
    keys = tuple(keys)
    cols = [*keys, "method", "scientific_success"]
    subset = frame.loc[frame["method"].isin([method, reference]), cols]
    left = subset.loc[subset["method"] == method].drop(columns="method")
    right = subset.loc[subset["method"] == reference].drop(columns="method")
    paired = left.merge(right, on=list(keys), how="outer", suffixes=("_method", "_reference"))
    m = paired["scientific_success_method"].fillna(False).astype(bool)
    r = paired["scientific_success_reference"].fillna(False).astype(bool)
    paired["both_success"] = m & r
    paired["method_only_failure"] = (~m) & r
    paired["reference_only_failure"] = m & (~r)
    paired["both_failure"] = (~m) & (~r)
    return paired


def strict_bottleneck_decision(
    *,
    problem_material: bool,
    triggers: dict[str, bool],
    normalized_scores: dict[str, float],
) -> str:
    if not problem_material:
        return "PROBLEM_NOT_MATERIAL"
    active = [name for name, value in triggers.items() if bool(value)]
    if not active:
        return "INCONCLUSIVE_REQUIRES_MORE_EVIDENCE"
    active.sort(key=lambda name: (-float(normalized_scores[name]), name))
    if len(active) == 1:
        return active[0]
    return f"COMBINED:{active[0]}+{active[1]}"
