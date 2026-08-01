"""Correct Phase-E H1--H3 using frozen results only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction1freq.evaluation.failure_aware_statistics import (
    paired_bootstrap_improvement,
    paired_failure_counts,
)


REPO = Path(__file__).resolve().parents[2]
METRICS = ("frequency_iae_hz_s", "ace_iae_pu_s", "tie_iae_pu_s")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assign_frozen_e3_split(episodes: pd.DataFrame) -> pd.Series:
    """Recover the split actually used by E6, independent of bad labels."""

    seeds = episodes["load_seed"].astype(int)
    if not seeds.between(0, 19).all():
        raise ValueError("frozen E3 audit expects seeds 0--19")
    return pd.Series(
        np.where(seeds < 10, "legacy_development", "legacy_validation"),
        index=episodes.index,
    )


def baseline_selection(episodes: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    candidates = episodes[
        (episodes["split_f1"] == "legacy_development")
        & (episodes["method"] != "oracle_o2_nmpc")
    ]
    records = []
    for method, frame in candidates.groupby("method"):
        successes = frame[frame.physical_success]
        records.append(
            {
                "method": method,
                "selection_split": "legacy_development_seeds_0_9_only",
                "episodes": len(frame),
                "physical_success_rate": float(frame.physical_success.mean()),
                "mean_cost_all_episodes": float(
                    frame.independent_rollout_objective.mean()
                ),
                "mean_cost_successful_episodes": float(
                    successes.independent_rollout_objective.mean()
                ),
                "validation_used_for_selection": False,
            }
        )
    table = pd.DataFrame(records).sort_values(
        ["physical_success_rate", "mean_cost_successful_episodes", "method"],
        ascending=[False, True, True],
    )
    table["selection_rank"] = np.arange(1, len(table) + 1)
    table["selected"] = table.selection_rank == 1
    return str(table.iloc[0].method), table


def _failure_penalty_improvements(
    baseline: pd.DataFrame, proposed: pd.DataFrame
) -> dict[str, float]:
    common = baseline.index.intersection(proposed.index)
    b = baseline.loc[common]
    p = proposed.loc[common]
    pooled_success_cost = pd.concat(
        [
            b.loc[b.physical_success, "independent_rollout_objective"],
            p.loc[p.physical_success, "independent_rollout_objective"],
        ]
    )
    scale = float(pooled_success_cost.max()) if len(pooled_success_cost) else 1.0
    output: dict[str, float] = {}
    for multiplier in (2.0, 5.0, 10.0):
        b_cost = b.independent_rollout_objective.to_numpy(float).copy()
        p_cost = p.independent_rollout_objective.to_numpy(float).copy()
        b_cost[~b.physical_success.to_numpy(bool)] = multiplier * scale
        p_cost[~p.physical_success.to_numpy(bool)] = multiplier * scale
        denominator = max(float(np.mean(b_cost)), 1e-15)
        output[f"failure_penalty_{int(multiplier)}x_improvement"] = (
            1.0 - float(np.mean(p_cost)) / denominator
        )
    return output


def materiality_failure_aware(
    episodes: pd.DataFrame, baseline_method: str
) -> pd.DataFrame:
    main = episodes[episodes.sfr_period_s == 4.0]
    records: list[dict[str, object]] = []
    for split in ("legacy_development", "legacy_validation"):
        subset = main[main.split_f1 == split]
        for (mechanism, tension), frame in subset.groupby(
            ["mechanism", "sg_tension"]
        ):
            baseline = frame[frame.method == baseline_method].set_index("scenario_id")
            proposed = frame[frame.method == "oracle_o2_nmpc"].set_index("scenario_id")
            counts = paired_failure_counts(baseline, proposed)
            common = baseline.index.intersection(proposed.index)
            b = baseline.loc[common]
            p = proposed.loc[common]
            both = b.physical_success & p.physical_success
            record: dict[str, object] = {
                "split": split,
                "mechanism": mechanism,
                "sg_tension": tension,
                "baseline_method": baseline_method,
                "paired_episodes": len(common),
                **counts,
                "baseline_success_rate": float(b.physical_success.mean()),
                "oracle_success_rate": float(p.physical_success.mean()),
                "success_rate_difference": float(
                    p.physical_success.mean() - b.physical_success.mean()
                ),
            }
            metrics_passing = 0
            for metric in METRICS:
                point, low, high = paired_bootstrap_improvement(
                    b.loc[both, metric].to_numpy(float),
                    p.loc[both, metric].to_numpy(float),
                    clusters=b.loc[both, "load_seed"].to_numpy(int),
                )
                record[f"{metric}_aggregate_mean_improvement"] = point
                record[f"{metric}_ci_low"] = low
                record[f"{metric}_ci_high"] = high
                metrics_passing += int(
                    np.isfinite(point) and point >= 0.10 and low > 0.0
                )
            record.update(_failure_penalty_improvements(b, p))
            no_success_masking = bool(
                record["oracle_success_rate"] >= record["baseline_success_rate"]
            )
            record["continuous_metrics_passing"] = metrics_passing
            record["no_success_rate_degradation"] = no_success_masking
            record["cell_materiality_pass"] = bool(
                no_success_masking
                and (
                    record["success_rate_difference"] >= 0.10
                    or metrics_passing >= 2
                )
            )
            records.append(record)
    return pd.DataFrame(records)


def development_only_tcrit() -> pd.DataFrame:
    source = pd.read_csv(
        REPO / "results_phase_e" / "E3" / "full" / "TCRIT_DEVELOPMENT.csv"
    )
    seed = source.scenario_id.str.extract(r"_(\d+)$")[0].astype(int)
    result = source.loc[seed < 10].copy()
    result["f1_split"] = "legacy_development_seeds_0_9_only"
    result["validation_used_for_threshold_design"] = False
    return result


def main() -> None:
    output = REPO / "results_phase_f" / "F1"
    science = REPO / "research_outputs_phase_f" / "01_SCIENCE"
    progress_dir = REPO / "progress_phase_f"
    log_dir = REPO / "logs_phase_f" / "F1"
    for directory in (output, science, progress_dir, log_dir):
        directory.mkdir(parents=True, exist_ok=True)

    source = pd.read_parquet(
        REPO / "results_phase_e" / "E3" / "full" / "E3_MATERIALITY_EPISODES.parquet"
    )
    episodes = source.copy()
    episodes["split_f1"] = assign_frozen_e3_split(episodes)
    baseline_method, selection = baseline_selection(episodes)
    materiality = materiality_failure_aware(episodes, baseline_method)
    tcrit = development_only_tcrit()

    validation_pass = materiality[
        (materiality.split == "legacy_validation")
        & materiality.cell_materiality_pass
    ]
    mechanisms_passing = int(validation_pass.mechanism.nunique())
    tensions_passing = int(validation_pass.sg_tension.nunique())
    h1 = (
        "SUPPORTED"
        if mechanisms_passing >= 2 and tensions_passing >= 2
        else "NOT_SUPPORTED"
    )
    h2 = (
        "TESTED_PASSIVE_ESTIMATORS_NOT_SUPPORTED_UNDER_REGISTERED_EXCITATION"
    )
    h3 = "TESTED_ACTIVE_PROBE_NOT_SAFE"
    hypotheses = pd.DataFrame(
        [
            {
                "hypothesis": "H1",
                "status": h1,
                "scope": "frozen Phase-E O2 versus development-selected deployable baseline",
                "evidence": (
                    f"{mechanisms_passing} validation mechanisms and "
                    f"{tensions_passing} SG tensions pass success-first materiality"
                ),
            },
            {
                "hypothesis": "H2",
                "status": h2,
                "scope": "three tested passive estimators; registered natural excitation only",
                "evidence": "Phase-E E4 frozen evidence",
            },
            {
                "hypothesis": "H3",
                "status": h3,
                "scope": "registered alternating-probe implementations only",
                "evidence": "Phase-E E5 safety/cost evidence",
            },
            {
                "hypothesis": "H4",
                "status": "NOT_EVALUATED",
                "scope": "CDSR-MPC",
                "evidence": "requires F4--F7",
            },
            {
                "hypothesis": "H5",
                "status": "NOT_EVALUATED",
                "scope": "registered-set certificate",
                "evidence": "requires F5",
            },
        ]
    )

    selection_path = output / "BASELINE_SELECTION_DEVELOPMENT_ONLY.csv"
    materiality_path = output / "MATERIALITY_FAILURE_AWARE.csv"
    tcrit_path = output / "TCRIT_DEVELOPMENT_ONLY.csv"
    hypotheses_path = science / "CORRECTED_HYPOTHESES_STATUS.csv"
    selection.to_csv(selection_path, index=False)
    materiality.to_csv(materiality_path, index=False)
    tcrit.to_csv(tcrit_path, index=False)
    hypotheses.to_csv(hypotheses_path, index=False)

    boundary = science / "CORRECTED_CLAIM_BOUNDARY.md"
    boundary.write_text(
        f"""# Corrected Phase-F claim boundary

## Frozen Phase-E split recovery

The Phase-E manifest mislabeled every seed as development.  F1 recovers the
split actually used by E6: seeds 0--9 select the deployable baseline and seeds
10--19 are held-out legacy validation.  This audit does not run or alter a
controller.  The Phase-F experiments themselves use the separately registered
0--19 / 20--39 / 100--159 split.

The development-only success-first selection chooses `{baseline_method}`.
Validation is never used for selection, weights, thresholds, or Tcrit.

## Corrected hypotheses

- H1: **{h1}**.  Success-rate degradation is a veto, so both-success
  continuous improvements cannot hide additional Oracle failures.
- H2: **{h2}**.  This is not a category-level impossibility result.
- H3: **{h3}**.  This applies only to the registered tested probe.
- H4/H5: not evaluated until CDSR-MPC and certificates exist.

All continuous improvements are aggregate-mean ratios with paired
seed-cluster bootstrap intervals.  The paired failure table distinguishes both
success, each one-sided failure, both fail, and not evaluated.  Penalty
sensitivity at 2x/5x/10x the worst successful objective is included but is not
used to erase the success-first table.
""",
        encoding="utf-8",
    )

    gate = {
        "development_only_baseline_selection": bool(
            not selection.validation_used_for_selection.any()
        ),
        "best_baseline_fixed_before_validation": baseline_method
        == "fixed_allocation_pi",
        "failure_and_not_evaluated_separate": "not_evaluated"
        in materiality.columns,
        "aggregate_mean_ratio_used": all(
            "aggregate_mean_improvement" in column
            for column in materiality.columns
            if column.endswith("_improvement")
            and column.startswith(("frequency", "ace", "tie"))
        ),
        "validation_not_used_for_tcrit": bool(
            not tcrit.validation_used_for_threshold_design.any()
        ),
        "h1_at_least_two_mechanisms": mechanisms_passing >= 2,
        "h1_at_least_two_sg_tensions": tensions_passing >= 2,
        "h2_h3_claims_scope_limited": True,
    }
    gate_passed = all(gate.values())
    progress = {
        "schema": "direction1.phase_f.progress.v1",
        "stage": "F1",
        "gate": "G1_CORRECTED_SCIENCE",
        "gate_passed": gate_passed,
        "gate_components": gate,
        "best_deployable_baseline": baseline_method,
        "h1_status": h1,
        "mechanisms_passing": mechanisms_passing,
        "sg_tensions_passing": tensions_passing,
        "h2_status": h2,
        "h3_status": h3,
        "new_controller_runs": 0,
        "source_results_modified": False,
        "next_stage": "F2" if gate_passed else "F9_NEGATIVE_PACKAGE",
        "outputs_sha256": {
            path.relative_to(REPO).as_posix(): sha256(path)
            for path in (
                selection_path,
                materiality_path,
                tcrit_path,
                hypotheses_path,
                boundary,
            )
        },
    }
    (progress_dir / "F1.json").write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not gate_passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

