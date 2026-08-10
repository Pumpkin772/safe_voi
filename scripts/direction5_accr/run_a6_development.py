"""A6 development-only probe rescreen and registered weight selection."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.probing import ProbeCandidate, candidate_models, safety_result
from direction5freq.accr.validation import plant_parameters, simulate_plant_a_episode


LOCK_PATH = REPO / "configs/direction5_accr/a6_validation_lock.yaml"
A3_LOCK_PATH = REPO / "configs/direction5_accr/a3_probe_lock.yaml"
RESULTS = REPO / "results_accr/A6/development"
PROGRESS = REPO / "progress_accr/A6_DEVELOPMENT.json"
CYCLE_PARTS = RESULTS / "cycle_parts"


def development_manifest(lock: dict) -> pd.DataFrame:
    rows = []
    designs = (
        (240, "low", 2.0, "area0", "before"),
        (241, "low", 4.0, "both", "after"),
        (242, "high", 2.0, "area1", "simultaneous"),
        (243, "high", 4.0, "both", "before"),
    )
    for index, (seed, tension, period, area, relation) in enumerate(designs):
        capability_time = 80.0 + 3.0 * index
        load_time = capability_time + (-10.0 if relation == "before" else 10.0 if relation == "after" else 0.0)
        load_magnitude = 0.62 * min(
            plant_parameters(tension).sg_power_upper_pu
        )
        rows.append({
            "scenario_id": f"A6-D-{index:02d}", "split": "development", "seed": seed,
            "design_cell": f"A_full_nonlinear|power_drop|{tension}|{period:g}",
            "plant": "A_full_nonlinear", "mechanism": "power_drop",
            "capability_mechanism": "power_drop",
            "sg_tension": tension, "period_s": period,
            "control_period_s": period,
            "condition": "known", "duration_s": float(lock["development_duration_s"]),
            "capability_change_time_s": capability_time, "load_event_time_s": load_time,
            "load_area": area, "load_sign": 1, "load_magnitude_pu": load_magnitude,
            "timing_relation": relation, "initial_soc": 0.50,
            "initial_soc_area1": 0.50, "initial_soc_area2": 0.50,
            "noise_std_hz": 0.0, "jitter_s": 0.0, "dropout_probability": 0.0,
            "probe_eligible": True, "known_ood": "known",
            "contract_status": "WITHIN_CONTRACT", "materiality_positive": True,
            "factor_assignment": "explicit_crossed_development_design",
        })
    return pd.DataFrame(rows)


def rescreen_boundary_probe(lock: dict, a3_lock: dict) -> pd.DataFrame:
    probe_lock = dict(a3_lock)
    probe_lock["base_action_pu"] = [0.030, float(lock["probe"]["base_bess_pu"]), 0.020, 0.000]
    probe = ProbeCandidate(
        lock["probe"]["probe_id"], float(lock["probe"]["amplitude_pu"]),
        np.asarray(lock["probe"]["normalized_sequence"], dtype=float),
    )
    rows = []
    for model in candidate_models(a3_lock):
        result = safety_result(probe, model, probe_lock)
        rows.append({
            "power_pu": model.power_pu, "ramp_pu_per_s": model.ramp_pu_per_s,
            "delay_s": model.delay_s, **result,
            "safe": bool(
                not result["hard_violation"]
                and result["incremental_frequency_peak_hz"] <= float(a3_lock["gates"]["incremental_frequency_hz_max"])
                and result["incremental_ace_fraction"] <= float(a3_lock["gates"]["incremental_ace_fraction_max"])
                and result["incremental_tie_fraction"] <= float(a3_lock["gates"]["incremental_tie_fraction_max"])
            ),
        })
    return pd.DataFrame(rows)


def summarize_weights(episodes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for weight, group in episodes.groupby("delivered_branch_weight"):
        wide = group.pivot(index="scenario_id", columns="method", values="ace_iae_pu_s")
        absolute = wide.contract_only_recourse_mpc - wide.accr_mpc
        denominator = wide.contract_only_recourse_mpc - wide.perfect_capability_recourse_oracle
        valid = denominator > 1e-9
        recovery = (absolute[valid] / denominator[valid]).replace([np.inf, -np.inf], np.nan).dropna()
        method = group[group.method.eq("accr_mpc")]
        rows.append({
            "delivered_branch_weight": float(weight),
            "scenario_count": int(len(wide)),
            "mean_ace_relative_improvement": float(np.mean(absolute / np.maximum(wide.contract_only_recourse_mpc, 1e-9))),
            "mean_value_recovery": float(recovery.mean()) if len(recovery) else np.nan,
            "valid_value_recovery_scenarios": int(len(recovery)),
            "hard_violations": int(method.hard_violation.sum() + method.command_violation.sum()),
            "fallback_calls": int(method.fallback_calls.sum()),
            "certificate_issues": int(method.certificate_issues.sum()),
            "nonzero_certified_surplus_episodes": int((method.certified_surplus_l1_pu_s > 1e-9).sum()),
            "p99_solve_time_s": float(method.p99_solve_time_s.max()),
        })
    return pd.DataFrame(rows).sort_values("delivered_branch_weight")


def main() -> None:
    lock = yaml.safe_load(LOCK_PATH.read_text("utf-8"))
    a3_lock = yaml.safe_load(A3_LOCK_PATH.read_text("utf-8"))
    if lock["final_seeds_consumed"]:
        raise RuntimeError("A6 development may not consume final seeds")
    RESULTS.mkdir(parents=True, exist_ok=True)
    safety = rescreen_boundary_probe(lock, a3_lock)
    safety.to_csv(RESULTS / "A6_BOUNDARY_PROBE_SAFETY.csv", index=False)
    manifest = development_manifest(lock)
    manifest.to_csv(RESULTS / "A6_DEVELOPMENT_MANIFEST.csv", index=False)
    checkpoint = RESULTS / "A6_DEVELOPMENT_EPISODES_CHECKPOINT.csv"
    rows = pd.read_csv(checkpoint).to_dict("records") if checkpoint.is_file() else []
    completed = {
        (str(row["scenario_id"]), str(row["method"]), float(row["delivered_branch_weight"]))
        for row in rows
    }
    row_index = {
        (str(row["scenario_id"]), str(row["method"]), float(row["delivered_branch_weight"])): index
        for index, row in enumerate(rows)
    }
    for weight in lock["development_candidates"]["delivered_branch_weights"]:
        for _, scenario in manifest.iterrows():
            for method in lock["primary_methods"]:
                key = (str(scenario.scenario_id), str(method), float(weight))
                cycle_path = CYCLE_PARTS / f"{scenario.scenario_id}__{method}__w{float(weight):g}.parquet"
                checkpoint_has_current_manifest = bool(
                    key in row_index and rows[row_index[key]].get("design_cell")
                )
                if key in completed and cycle_path.is_file() and checkpoint_has_current_manifest:
                    continue
                result = simulate_plant_a_episode(
                    scenario.to_dict(), method, lock, float(weight),
                    cycle_output_path=cycle_path,
                )
                result["delivered_branch_weight"] = float(weight)
                if key in row_index:
                    rows[row_index[key]] = result
                else:
                    row_index[key] = len(rows)
                    rows.append(result)
                completed.add(key)
                pd.DataFrame(rows).to_csv(checkpoint, index=False)
    episodes = pd.DataFrame(rows)
    episodes.to_csv(RESULTS / "A6_DEVELOPMENT_EPISODES.csv", index=False)
    weights = summarize_weights(episodes)
    weights.to_csv(RESULTS / "A6_WEIGHT_SCREEN.csv", index=False)
    eligible = weights[(weights.hard_violations == 0) & (weights.fallback_calls == 0)]
    if len(eligible):
        ranked = eligible.assign(
            rank_value=eligible.mean_value_recovery.fillna(-np.inf)
        ).sort_values(["rank_value", "delivered_branch_weight"], ascending=[False, True])
        selected_weight = float(ranked.iloc[0].delivered_branch_weight)
    else:
        selected_weight = float(lock["development_candidates"]["delivered_branch_weights"][0])
    selection = {
        "project": "DIRECTION5", "stage": "A6_DEVELOPMENT",
        "status": "PASS" if bool(safety.safe.all()) and len(eligible) else "FAIL",
        "selected_delivered_branch_weight": selected_weight,
        "selection_rule": "maximum development mean ACE value recovery among zero-hard-violation zero-fallback candidates; ties choose lower weight",
        "selected_probe_policy": lock["probe"],
        "boundary_probe_candidates_safe": int(safety.safe.sum()),
        "boundary_probe_candidates_total": int(len(safety)),
        "validation_or_final_read": False,
        "final_seeds_consumed": False,
        "repair_rounds_used": 1,
        "repair_classification": "PROBE_TRIGGER_BOUNDARY_PRELOAD",
    }
    RESULTS.joinpath("A6_FROZEN_SELECTION.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps({
        "stage": "A6_DEVELOPMENT", "status": selection["status"],
        "selection": "results_accr/A6/development/A6_FROZEN_SELECTION.json",
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(selection, indent=2))
    print(weights.to_string(index=False))
    if selection["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
