"""Run the locked A1 perfect-capability materiality experiment."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.materiality import METHODS, build_manifest, paired_analysis, simulate_episode


def main() -> None:
    lock = yaml.safe_load((REPO / "configs/direction5_accr/a1_materiality_lock.yaml").read_text("utf-8"))
    if not lock["registered_before_execution"] or lock["final_seeds_consumed"]:
        raise RuntimeError("A1 lock or seed firewall is invalid")
    output = REPO / "results_accr/A1"
    output.mkdir(parents=True, exist_ok=True)
    parts = output / "episode_parts"
    parts.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(lock)
    manifest.to_csv(output / "A1_MATERIALITY_MANIFEST.csv", index=False)
    rows = []
    for row in manifest.to_dict("records"):
        for method in METHODS:
            part = parts / f"{row['scenario_id']}__{method}.csv"
            if part.exists():
                saved = pd.read_csv(part)
                if len(saved) != 1:
                    raise RuntimeError(f"invalid saved episode part: {part}")
                rows.append(saved.iloc[0].to_dict())
                print(f"RESUME {row['scenario_id']} {method}", flush=True)
                continue
            print(f"{row['scenario_id']} {method}", flush=True)
            result = simulate_episode(row, method, lock)
            temporary = part.with_suffix(".tmp")
            pd.DataFrame([result]).to_csv(temporary, index=False)
            os.replace(temporary, part)
            rows.append(result)
    episodes = pd.DataFrame(rows)
    episodes.to_csv(output / "A1_MATERIALITY_EPISODES.csv", index=False)
    paired, cells = paired_analysis(episodes, int(lock["statistics"]["bootstrap_resamples"]))
    paired.to_csv(output / "A1_MATERIALITY_PAIRED.csv", index=False)
    cells.to_csv(output / "A1_MATERIALITY_CELLS.csv", index=False)

    positive = cells[cells.materiality_positive]
    mechanism_gate = any(
        set(positive.loc[positive.mechanism == mechanism, "sg_tension"]) == set(lock["sg_tensions"])
        for mechanism in lock["mechanisms"]
    )
    execution_gates = {
        "all_scenarios_paired": bool(len(episodes) == 2 * len(manifest)),
        "full_rolling_mpc": bool(episodes.full_rolling.all()),
        "ordinary_controller_truth_leakage_zero": bool(
            not episodes.loc[episodes.method == "contract_only_rolling_mpc", "true_capability_read_by_ordinary_controller"].any()
        ),
        "hard_violations_zero": bool(int(episodes.hard_violation.sum()) == 0),
        "at_least_two_materiality_positive_cells": bool(
            int(cells.materiality_positive.sum()) >= int(lock["gate"]["minimum_positive_cells"])
        ),
        "same_power_or_ramp_mechanism_positive_at_both_tensions": bool(mechanism_gate),
    }
    summary = {
        "schema": "direction5.accr.a1.materiality.v1",
        "stage": "A1_MATERIALITY",
        "status": "PASS" if all(execution_gates.values()) else "FAIL",
        "episode_count": len(episodes),
        "scenario_count": len(manifest),
        "attempted_optimization_calls": int(episodes.attempted_optimization_calls.sum()),
        "fallback_calls": int(episodes.fallback_calls.sum()),
        "restoration_calls": int(episodes.restoration_calls.sum()),
        "materiality_positive_cells": positive[["mechanism", "sg_tension", "positive_metrics"]].to_dict("records"),
        "gates": execution_gates,
        "final_seeds_consumed": False,
        "next_stage_if_literature_gate_passes": "A2",
    }
    (output / "A1_MATERIALITY_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    raise SystemExit(0 if summary["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
