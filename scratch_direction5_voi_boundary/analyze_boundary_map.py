"""Summarize the physical Direction5 value map without altering classifications."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research_outputs_boundary" / "B1_MAP" / "BOUNDARY_MAP.csv"
OUTPUT = ROOT / "research_outputs_boundary" / "B1_ANALYSIS"


def main() -> None:
    frame = pd.read_csv(SOURCE)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    finite = frame.replace((np.inf, -np.inf), np.nan)
    grouped = (
        finite.groupby(["period_s", "sg_tension", "objective", "region"], dropna=False)
        .agg(
            points=("point_id", "size"),
            mean_perfect_information_value=("perfect_information_value", "mean"),
            maximum_exact_probe_value=("maximum_exact_probe_value", "max"),
            maximum_upper_value=("maximum_safe_probe_upper_value", "max"),
            mean_solver_failures=("solver_failures", "mean"),
        )
        .reset_index()
    )
    grouped.to_csv(OUTPUT / "BOUNDARY_GROUPS.csv", index=False)
    exact = finite.maximum_exact_probe_value
    heuristic = finite.heuristic_value
    jointly = exact.notna() & heuristic.notna()
    sign_agreement = float(
        np.mean((exact[jointly] > 0.0) == (heuristic[jointly] > 0.0))
    ) if jointly.any() else np.nan
    rank_correlation = float(
        exact[jointly].corr(heuristic[jointly], method="spearman")
    ) if jointly.sum() >= 3 else np.nan
    summary = {
        "points": int(len(frame)),
        "positive_perfect_information_points": int(
            finite.perfect_information_value.gt(1e-8).sum()
        ),
        "positive_points": int(frame.region.eq("POSITIVE_VALUE").sum()),
        "proved_zero_points": int(frame.region.eq("ZERO_VALUE_PROVED").sum()),
        "unproved_zero_points": int(frame.region.eq("ZERO_VALUE_OBSERVED_NOT_PROVED").sum()),
        "solver_unclassified_points": int(frame.region.eq("UNCLASSIFIED_SOLVER").sum()),
        "maximum_perfect_information_value": float(finite.perfect_information_value.max()),
        "maximum_exact_probe_value": float(finite.maximum_exact_probe_value.max()),
        "maximum_safe_probe_upper_value": float(finite.maximum_safe_probe_upper_value.max()),
        "heuristic_exact_sign_agreement": sign_agreement,
        "heuristic_exact_spearman": rank_correlation,
    }
    (OUTPUT / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    colors = {
        "POSITIVE_VALUE": "#ca0020",
        "ZERO_VALUE_PROVED": "#0571b0",
        "ZERO_VALUE_OBSERVED_NOT_PROVED": "#92c5de",
        "UNCLASSIFIED_SOLVER": "#666666",
    }
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2), constrained_layout=True)
    for region, subset in finite.groupby("region"):
        axes[0].scatter(
            subset.perfect_information_value,
            subset.maximum_exact_probe_value,
            s=20, alpha=0.75, label=region, color=colors.get(region, "black"),
        )
        axes[1].scatter(
            subset.heuristic_value,
            subset.maximum_exact_probe_value,
            s=20, alpha=0.75, label=region, color=colors.get(region, "black"),
        )
    for axis in axes:
        axis.axhline(0.0, color="black", linewidth=0.8)
        axis.grid(alpha=0.20)
        axis.set_ylabel("exact net probe value")
    axes[0].set_xlabel("registered perfect-information value")
    axes[1].set_xlabel("predecessor heuristic proxy")
    axes[0].legend(fontsize=7)
    fig.savefig(OUTPUT / "EXACT_VALUE_BOUNDARY.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2), constrained_layout=True)
    scatter = axes[0].scatter(
        finite.load_magnitude_pu, finite.perfect_information_value,
        c=finite.tie_loading_pu, cmap="viridis", s=22, alpha=0.8,
    )
    axes[0].axhline(0.0, color="black", linewidth=0.8)
    axes[0].set_xlabel("persistent load estimate (pu)")
    axes[0].set_ylabel("registered perfect-information value")
    fig.colorbar(scatter, ax=axes[0], label="tie loading (pu)")
    for period, subset in finite.groupby("period_s"):
        axes[1].scatter(
            subset.heuristic_value, subset.perfect_information_value,
            s=22, alpha=0.75, label=f"{period:g} s",
        )
    axes[1].axhline(0.0, color="black", linewidth=0.8)
    axes[1].set_xlabel("predecessor heuristic proxy")
    axes[1].set_ylabel("registered perfect-information value")
    axes[1].legend()
    for axis in axes:
        axis.grid(alpha=0.20)
    fig.savefig(OUTPUT / "PERFECT_INFORMATION_SCREEN.png", dpi=180)
    plt.close(fig)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
