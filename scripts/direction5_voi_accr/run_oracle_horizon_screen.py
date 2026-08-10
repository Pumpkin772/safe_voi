"""Screen whether longer MPC horizons create enough perfect-information value."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from direction5freq.accr.validation import simulate_plant_a_episode
from run_m1_r1_development import development_manifest


SCREEN_PATH = REPO / "configs/direction5_voi_accr/oracle_horizon_materiality_screen.yaml"
BASE_LOCK_PATH = REPO / "configs/direction5_voi_accr/m2_validation_lock.yaml"
OUTPUT = REPO / "research_outputs_working/ORACLE_HORIZON_SCREEN"
PROGRESS = REPO / "progress_direction5_voi_accr/ORACLE_HORIZON_SCREEN.json"
BASE = "contract_only_recourse_mpc"
ORACLE = "perfect_capability_recourse_oracle"


def manifest_for(screen: dict) -> pd.DataFrame:
    values = {
        "mechanisms": screen["mechanisms"],
        "sg_tensions": screen["sg_tensions"],
        "periods_s": screen["periods_s"],
        "value_regions": screen["value_regions"],
        "development_seed_range": screen["development_seed_range"],
        "duration_s": screen["duration_s"],
    }
    result = development_manifest(values)
    result["scenario_id"] = [f"D5-OHS-{index:03d}" for index in range(len(result))]
    result["split"] = "development_oracle_horizon_screen"
    result["factor_assignment"] = "NEW_DEVELOPMENT_ORACLE_HORIZON_SCREEN"
    return result


def save_progress(horizon: int, completed: int, total: int, latest: str) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps({
        "project": "DIRECTION5", "method": "VOI-ACCR-MPC",
        "screen": "ORACLE_HORIZON_MATERIALITY", "horizon_steps": horizon,
        "completed": completed, "total": total, "latest": latest,
    }, indent=2), encoding="utf-8")


def lock_for(base: dict, screen: dict, horizon: int) -> dict:
    lock = deepcopy(base)
    lock["horizon_steps"] = int(horizon)
    lock["voi_controller"]["horizon_steps"] = int(horizon)
    lock["voi_controller"].update(screen["weights"])
    return lock


def main() -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("Refusing unguarded Oracle horizon screen")
    screen = yaml.safe_load(SCREEN_PATH.read_text("utf-8"))
    base_lock = yaml.safe_load(BASE_LOCK_PATH.read_text("utf-8"))
    manifest = manifest_for(screen)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(OUTPUT / "MANIFEST.csv", index=False)
    summaries = []
    for horizon in screen["horizon_steps"]:
        lock = lock_for(base_lock, screen, int(horizon))
        root = OUTPUT / f"H{int(horizon):02d}"
        rows = []
        total = len(manifest) * 2
        for _, scenario in manifest.iterrows():
            for method in (BASE, ORACLE):
                target = root / "episode_parts" / f"{scenario.scenario_id}__{method}.csv"
                if not target.exists():
                    result = simulate_plant_a_episode(
                        scenario.to_dict(), method, lock,
                        float(lock["voi_controller"]["delivered_branch_weight"]),
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    pd.DataFrame([result]).to_csv(target, index=False)
                rows.append(pd.read_csv(target))
                save_progress(int(horizon), len(rows), total, target.name)
        episodes = pd.concat(rows, ignore_index=True)
        episodes.to_csv(root / "EPISODES.csv", index=False)
        pivot = episodes.pivot(index="scenario_id", columns="method")
        high = manifest.loc[
            manifest.value_region.eq("HIGH_VALUE_CANDIDATE"), "scenario_id"
        ]
        record = {
            "horizon_steps": int(horizon),
            "scenario_count": int(len(manifest)),
            "high_scenario_count": int(len(high)),
            "hard_violations": int(episodes.hard_violation.sum()),
            "fallback_calls": int(episodes.fallback_calls.sum()),
            "p99_solve_fraction_max": float(
                (episodes.p99_solve_time_s / episodes.period_s).max()
            ),
        }
        for metric in ("ace_iae_pu_s", "tie_iae_pu_s"):
            baseline = float(pivot[metric].loc[high, BASE].sum())
            oracle = float(pivot[metric].loc[high, ORACLE].sum())
            record[f"oracle_{metric}_aggregate_improvement"] = (
                (baseline - oracle) / baseline
            )
            for period in screen["periods_s"]:
                ids = manifest.loc[
                    manifest.value_region.eq("HIGH_VALUE_CANDIDATE")
                    & manifest.period_s.eq(float(period)), "scenario_id"
                ]
                base_period = float(pivot[metric].loc[ids, BASE].sum())
                oracle_period = float(pivot[metric].loc[ids, ORACLE].sum())
                record[f"oracle_{metric}_improvement_period_{float(period):g}s"] = (
                    (base_period - oracle_period) / base_period
                )
        record["oracle_materiality_pass"] = bool(
            max(
                record["oracle_ace_iae_pu_s_aggregate_improvement"],
                record["oracle_tie_iae_pu_s_aggregate_improvement"],
            ) >= float(screen["oracle_materiality_gate"])
        )
        summaries.append(record)
        pd.DataFrame(summaries).to_csv(OUTPUT / "SUMMARY.csv", index=False)
    decision = {
        "project": "DIRECTION5", "method": "VOI-ACCR-MPC",
        "screen": "ORACLE_HORIZON_MATERIALITY",
        "status": (
            "MATERIALITY_CEILING_FOUND"
            if any(row["oracle_materiality_pass"] for row in summaries)
            else "NO_AGGREGATE_ORACLE_CEILING_AT_REGISTERED_GATE"
        ),
        "oracle_materiality_gate": float(screen["oracle_materiality_gate"]),
        "horizons_screened": list(screen["horizon_steps"]),
        "any_horizon_pass": bool(
            any(row["oracle_materiality_pass"] for row in summaries)
        ),
        "validation_or_final_seeds_used": False,
    }
    (OUTPUT / "DECISION.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(decision, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
