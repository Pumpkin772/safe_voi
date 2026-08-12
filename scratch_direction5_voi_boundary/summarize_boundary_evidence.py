"""Combine primary, adaptive, and probe-upper evidence into the final boundary map."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research_outputs_boundary" / "B1_FINAL_MAP"


def _load_optional(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _attach_confirmation(
    source: pd.DataFrame, confirmation: pd.DataFrame, origin: str,
) -> pd.DataFrame:
    result = source.copy(); result["origin"] = origin
    if confirmation.empty:
        result["confirmed_upper_value"] = np.nan
        result["final_region"] = np.where(
            result.perfect_information_value <= 1e-8,
            "ZERO_VALUE_PROVED", "UNCLASSIFIED",
        )
        return result
    confirmed = confirmation.set_index("point_id")
    result["confirmed_upper_value"] = result.point_id.map(
        confirmed.maximum_safe_probe_upper_value
    )
    result["final_region"] = np.where(
        result.perfect_information_value <= 1e-8,
        "ZERO_VALUE_PROVED",
        np.where(
            result.confirmed_upper_value <= 1e-8,
            "ZERO_VALUE_PROVED",
            np.where(result.confirmed_upper_value > 1e-8, "UPPER_POSITIVE_NEEDS_EXACT", "UNCLASSIFIED"),
        ),
    )
    return result


def main() -> None:
    primary = pd.read_csv(ROOT / "research_outputs_boundary/B1_TIGHT_MAP/BOUNDARY_MAP.csv")
    primary_confirmation = _load_optional(
        ROOT / "research_outputs_boundary/B1_UPPER_CONFIRMATION/UPPER_CONFIRMATION.csv"
    )
    adaptive = _load_optional(
        ROOT / "research_outputs_boundary/B1_ADAPTIVE_MAP/BOUNDARY_MAP.csv"
    )
    adaptive_confirmation = _load_optional(
        ROOT / "research_outputs_boundary/B1_ADAPTIVE_QUADRATIC_CONFIRMATION/UPPER_CONFIRMATION.csv"
    )
    frames = [_attach_confirmation(primary, primary_confirmation, "initial_lhs")]
    if not adaptive.empty:
        frames.append(_attach_confirmation(adaptive, adaptive_confirmation, "adaptive_boundary"))
    combined = pd.concat(frames, ignore_index=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUTPUT / "BOUNDARY_MAP.csv", index=False)

    heuristic_positive = combined.heuristic_value.gt(0.0)
    exact_or_upper_positive = combined.final_region.isin((
        "UPPER_POSITIVE_NEEDS_EXACT", "POSITIVE_VALUE",
    ))
    summary = {
        "points": int(len(combined)),
        "initial_lhs_points": int(combined.origin.eq("initial_lhs").sum()),
        "adaptive_points": int(combined.origin.eq("adaptive_boundary").sum()),
        "proved_zero_points": int(combined.final_region.eq("ZERO_VALUE_PROVED").sum()),
        "unclassified_points": int(combined.final_region.eq("UNCLASSIFIED").sum()),
        "upper_positive_points_needing_exact": int(
            combined.final_region.eq("UPPER_POSITIVE_NEEDS_EXACT").sum()
        ),
        "unclassified_fraction": float(combined.final_region.eq("UNCLASSIFIED").mean()),
        "maximum_registered_perfect_information_value": float(
            combined.perfect_information_value.max()
        ),
        "maximum_confirmed_probe_upper_value": float(
            combined.confirmed_upper_value.max()
        ) if combined.confirmed_upper_value.notna().any() else None,
        "heuristic_positive_fraction": float(heuristic_positive.mean()),
        "heuristic_false_positive_fraction": float(
            (heuristic_positive & combined.final_region.eq("ZERO_VALUE_PROVED")).mean()
        ),
        "heuristic_exact_sign_agreement": float(
            np.mean(heuristic_positive == exact_or_upper_positive)
        ),
        "solver_failures": int(combined.solver_failures.sum()),
    }
    (OUTPUT / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    grouped = (
        combined.groupby(["origin", "objective", "period_s", "sg_tension", "final_region"])
        .agg(points=("point_id", "size"),
             max_vpi=("perfect_information_value", "max"),
             max_probe_upper=("confirmed_upper_value", "max"))
        .reset_index()
    )
    grouped.to_csv(OUTPUT / "BOUNDARY_GROUPS.csv", index=False)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), constrained_layout=True)
    palette = {"ZERO_VALUE_PROVED": "#2166ac", "UNCLASSIFIED": "#777777",
               "UPPER_POSITIVE_NEEDS_EXACT": "#b2182b", "POSITIVE_VALUE": "#d6604d"}
    for region, subset in combined.groupby("final_region"):
        axes[0].scatter(
            subset.perfect_information_value, subset.confirmed_upper_value,
            s=14, alpha=0.65, color=palette.get(region, "black"), label=region,
        )
        axes[1].scatter(
            subset.heuristic_value, subset.perfect_information_value,
            s=14, alpha=0.65, color=palette.get(region, "black"), label=region,
        )
    axes[0].axhline(0.0, color="black", linewidth=0.8)
    axes[0].set_xlabel("registered perfect-information value")
    axes[0].set_ylabel("safe-probe value upper bound")
    axes[1].axhline(0.0, color="black", linewidth=0.8)
    axes[1].set_xlabel("predecessor heuristic proxy")
    axes[1].set_ylabel("registered perfect-information value")
    for axis in axes:
        axis.grid(alpha=0.2)
    axes[0].legend(fontsize=7)
    fig.savefig(OUTPUT / "BOUNDARY_MAP.png", dpi=180)
    plt.close(fig)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

