"""Post-M2 independent development search; never reads M2 episode outcomes."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.validation import capability_for, simulate_plant_a_episode


SEARCH_PATH = REPO / "configs/direction5_voi_accr/m1_r1_development_search.yaml"
BASE_LOCK_PATH = REPO / "configs/direction5_voi_accr/m2_validation_lock.yaml"
OUTPUT = REPO / "research_outputs_working/M1_R1_POST_M2"
PROGRESS = REPO / "progress_direction5_voi_accr/M1_R1.json"
BASE = "contract_only_recourse_mpc"
VOI = "voi_accr_mpc"
ORACLE = "perfect_capability_recourse_oracle"


def development_manifest(search: dict[str, Any]) -> pd.DataFrame:
    rows = []
    index = 0
    for mechanism in search["mechanisms"]:
        for tension in search["sg_tensions"]:
            for period_s in search["periods_s"]:
                for value_region in search["value_regions"]:
                    seed = int(search["development_seed_range"][0]) + index
                    rng = np.random.default_rng(np.random.SeedSequence([20260811, seed, 311]))
                    capability_time = float(rng.uniform(102.0, 126.0))
                    relation = ("before", "simultaneous", "after")[(index // 2) % 3]
                    offset = -14.0 if relation == "before" else 14.0 if relation == "after" else 0.0
                    high = 0.0744 if tension == "low" else 0.0558
                    rows.append({
                        "scenario_id": f"D5-M1R1-{index:03d}",
                        "split": "development_r1",
                        "seed": seed,
                        "design_cell": f"A_full_nonlinear|{mechanism}|{tension}|{float(period_s):g}",
                        "plant": "A_full_nonlinear",
                        "mechanism": mechanism,
                        "capability_mechanism": mechanism,
                        "sg_tension": tension,
                        "period_s": float(period_s),
                        "control_period_s": float(period_s),
                        "condition": (
                            "known"
                            if ((mechanism == "ramp_drop") + (tension == "high")) % 2 == 0
                            else "OOD"
                        ),
                        "known_ood": (
                            "known"
                            if ((mechanism == "ramp_drop") + (tension == "high")) % 2 == 0
                            else "OOD"
                        ),
                        "duration_s": float(search["duration_s"]),
                        "capability_change_time_s": capability_time,
                        "load_event_time_s": capability_time + offset,
                        "load_area": ("area0", "area1", "both")[index % 3],
                        "load_sign": 1,
                        "load_magnitude_pu": high if value_region == "HIGH_VALUE_CANDIDATE" else 0.020,
                        "timing_relation": relation,
                        "initial_soc": (0.45, 0.55)[index % 2],
                        "initial_soc_area1": (0.45, 0.55)[index % 2],
                        "initial_soc_area2": (0.45, 0.55)[index % 2],
                        "value_region": value_region,
                        "contract_violation": False,
                        "contract_status": "WITHIN_CONTRACT",
                        "factor_assignment": "M1_R1_NEW_DEVELOPMENT_FULL_FACTORIAL",
                    })
                    index += 1
    return pd.DataFrame(rows)


def candidate_lock(
    base: dict[str, Any], search: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    lock = deepcopy(base)
    fixed = search["fixed_repairs"]
    selected = search["locked_m1_parameters"]
    lock["horizon_steps"] = int(selected["horizon_steps"])
    lock["voi_controller"].update({
        "horizon_steps": int(selected["horizon_steps"]),
        "delivered_branch_weight": float(selected["delivered_branch_weight"]),
        "ace_weight": float(selected["ace_weight"]),
        "tie_weight": float(selected["tie_weight"]),
        "frequency_weight": float(selected["frequency_weight"]),
        "bess_effort_weight": float(selected["bess_effort_weight"]),
        "sg_effort_weight": float(selected["sg_effort_weight"]),
        "action_relevance_norm": float(selected["action_relevance_norm"]),
        "minimum_oracle_gap": float(selected["minimum_oracle_gap"]),
        "minimum_ace_for_probe": float(selected["minimum_ace_for_probe"]),
        "voi_margin": float(candidate["voi_margin"]),
    })
    lock["voi_probe"].update({
        "id": str(selected["probe_id"]),
        "amplitude_pu": float(selected["probe_amplitude_pu"]),
        "normalized_sequence": list(selected["probe_sequence"]),
        "certificate_validity_s": float(candidate["certificate_validity_s"]),
        "certificate_confirmation_s": fixed["certificate_confirmation_s"],
        "cooldown_s": float(selected["cooldown_s"]),
        "trigger_time_s": float(selected["trigger_time_s"]),
        "passive_renewal": bool(selected["passive_renewal"]),
        "latch_abstention": bool(selected["latch_abstention"]),
        "require_detected_change_for_probe": bool(
            fixed["require_detected_change_for_probe"]
        ),
        "minimum_partition_reduction": float(
            fixed["minimum_partition_reduction"]
        ),
        "certificate_power_guard_pu": float(fixed["certificate_power_guard_pu"]),
        "certificate_ramp_guard_pu_per_s": float(
            fixed["certificate_ramp_guard_pu_per_s"]
        ),
        "certificate_delay_guard_s": float(fixed["certificate_delay_guard_s"]),
        "probe_prediction_dt_s": float(fixed["probe_prediction_dt_s"]),
    })
    lock["voi_estimator"].update({
        "window_s": float(selected["estimator_window_s"]),
        "active_residual_bound_pu": float(selected["active_residual_bound_pu"]),
    })
    return lock


def save_progress(candidate: str, completed: int, total: int, latest: str) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps({
        "project": "DIRECTION5", "method": "VOI-ACCR-MPC",
        "milestone": "M1_R1_POST_M2_DEVELOPMENT", "candidate": candidate,
        "completed": completed, "total": total, "latest": latest,
    }, indent=2), encoding="utf-8")


def run_common(
    manifest: pd.DataFrame, lock: dict[str, Any], weight: float
) -> pd.DataFrame:
    part_root = OUTPUT / "common_parts"
    rows = []
    total = len(manifest) * 2
    for _, scenario in manifest.iterrows():
        for method in (BASE, ORACLE):
            target = part_root / f"{scenario.scenario_id}__{method}.csv"
            if not target.exists():
                result = simulate_plant_a_episode(
                    scenario.to_dict(), method, lock, weight,
                    cycle_output_path=(
                        OUTPUT / "common_cycles" / f"{scenario.scenario_id}__{method}.parquet"
                    ),
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                pd.DataFrame([result]).to_csv(target, index=False)
            rows.append(pd.read_csv(target))
            save_progress("COMMON", len(rows), total, target.name)
    return pd.concat(rows, ignore_index=True)


def run_candidate(
    manifest: pd.DataFrame,
    common: pd.DataFrame,
    lock: dict[str, Any],
    candidate: dict[str, Any],
    search: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    candidate_id = str(candidate["id"])
    root = OUTPUT / "candidates" / candidate_id
    rows = []
    for _, scenario in manifest.iterrows():
        target = root / "episode_parts" / f"{scenario.scenario_id}__{VOI}.csv"
        if not target.exists():
            result = simulate_plant_a_episode(
                scenario.to_dict(), VOI, lock,
                float(lock["voi_controller"]["delivered_branch_weight"]),
                cycle_output_path=root / "cycle_parts" / f"{scenario.scenario_id}__{VOI}.parquet",
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame([result]).to_csv(target, index=False)
        rows.append(pd.read_csv(target))
        save_progress(candidate_id, len(rows), len(manifest), target.name)
    voi_rows = pd.concat(rows, ignore_index=True)
    episodes = pd.concat((common, voi_rows), ignore_index=True)
    episodes.to_csv(root / "EPISODES.csv", index=False)
    pivot = episodes.pivot(index="scenario_id", columns="method")
    paired = manifest[[
        "scenario_id", "mechanism", "sg_tension", "period_s", "condition",
        "timing_relation", "value_region",
    ]].copy()
    for metric in (
        "frequency_peak_hz", "ace_iae_pu_s", "tie_iae_pu_s",
        "sg_mechanical_mileage_pu",
    ):
        paired[f"base_{metric}"] = paired.scenario_id.map(pivot[metric][BASE])
        paired[f"voi_{metric}"] = paired.scenario_id.map(pivot[metric][VOI])
        paired[f"oracle_{metric}"] = paired.scenario_id.map(pivot[metric][ORACLE])
    voi_index = voi_rows.set_index("scenario_id")
    for column in (
        "voi_probe_triggers", "probe_command_l1_pu_s", "hard_violation",
        "fallback_calls", "candidate_diameter_reduction_max",
        "maximum_unmetered_responsibility_jump_pu",
    ):
        paired[column] = paired.scenario_id.map(voi_index[column])
    paired["actually_probed"] = paired.voi_probe_triggers > 0
    paired.to_csv(root / "PAIRED.csv", index=False)

    certificate_rows = []
    for _, scenario in manifest.iterrows():
        path = root / "cycle_parts" / f"{scenario.scenario_id}__{VOI}.parquet"
        cycles = pd.read_parquet(path).sort_values("time_s")
        previous = 0
        for _, cycle in cycles.iterrows():
            current = int(cycle.certificate_issues_to_date)
            if current <= previous:
                continue
            truth = capability_for(scenario, float(cycle.time_s))
            false = bool(
                cycle.certificate_power0_pu > truth.upper_power_pu[0] + 1e-9
                or cycle.certificate_ramp0_pu_per_s > truth.ramp_up_pu_per_s[0] + 1e-9
                or cycle.certificate_delay0_s < truth.delay_s[0] - 1e-9
            )
            certificate_rows.append({
                "scenario_id": scenario.scenario_id, "time_s": cycle.time_s,
                "certificate_issue": current, "false_optimism": false,
            })
            previous = current
    certificate = pd.DataFrame(certificate_rows)
    certificate.to_csv(root / "CERTIFICATE_AUDIT.csv", index=False)

    high = paired[paired.value_region.eq("HIGH_VALUE_CANDIDATE")]
    worthwhile = high[high.actually_probed]
    low = paired[paired.value_region.eq("LOW_VALUE_CONTROL")]
    def aggregate_improvement(frame: pd.DataFrame, metric: str) -> float:
        denominator = float(frame[f"base_{metric}"].sum())
        return float(
            (frame[f"base_{metric}"].sum() - frame[f"voi_{metric}"].sum())
            / denominator
        ) if denominator > 1e-12 else np.nan
    low_changes = []
    for metric in ("frequency_peak_hz", "ace_iae_pu_s", "tie_iae_pu_s", "sg_mechanical_mileage_pu"):
        low_changes.extend((
            np.abs(low[f"base_{metric}"] - low[f"voi_{metric}"])
            / np.maximum(np.abs(low[f"base_{metric}"]), 1e-9)
        ).tolist())
    false_rate = float(certificate.false_optimism.mean()) if len(certificate) else 0.0
    gate = search["gates"]
    best_improvement = max(
        aggregate_improvement(worthwhile, "ace_iae_pu_s"),
        aggregate_improvement(worthwhile, "tie_iae_pu_s"),
    ) if len(worthwhile) else np.nan
    summary = {
        "candidate_id": candidate_id,
        "certificate_validity_s": float(candidate["certificate_validity_s"]),
        "voi_margin": float(candidate["voi_margin"]),
        "scenario_count": int(len(paired)),
        "worthwhile_scenarios": int(len(worthwhile)),
        "best_aggregate_improvement": best_improvement,
        "ace_aggregate_improvement": aggregate_improvement(worthwhile, "ace_iae_pu_s") if len(worthwhile) else np.nan,
        "tie_aggregate_improvement": aggregate_improvement(worthwhile, "tie_iae_pu_s") if len(worthwhile) else np.nan,
        "candidate_reduction_mean": float(worthwhile.candidate_diameter_reduction_max.mean()) if len(worthwhile) else 0.0,
        "false_optimism_rate": false_rate,
        "low_probe_rate": float((low.voi_probe_triggers > 0).mean()),
        "low_max_relative_metric_change": float(max(low_changes, default=0.0)),
        "frequency_delta_max_hz": float((paired.voi_frequency_peak_hz - paired.base_frequency_peak_hz).max()),
        "hard_violations": int(voi_rows.hard_violation.sum()),
        "fallback_calls": int(voi_rows.fallback_calls.sum()),
        "probe_command_l1_pu_s": float(voi_rows.probe_command_l1_pu_s.sum()),
    }
    summary["m1_pass"] = bool(
        summary["hard_violations"] <= int(gate["hard_violations_max"])
        and summary["frequency_delta_max_hz"] <= float(gate["frequency_peak_delta_hz_max"])
        and summary["worthwhile_scenarios"] >= int(gate["worthwhile_scenarios_min"])
        and summary["best_aggregate_improvement"] >= float(gate["worthwhile_ace_or_tie_improvement_min"])
        and summary["candidate_reduction_mean"] >= float(gate["candidate_diameter_reduction_min"])
        and summary["false_optimism_rate"] <= float(gate["false_optimism_max"])
        and summary["low_probe_rate"] <= float(gate["not_worthwhile_probe_rate_max"])
        and summary["low_max_relative_metric_change"] <= float(gate["not_worthwhile_metric_change_max"])
    )
    (root / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return episodes, summary


def main() -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("Refusing unguarded M1 R1 development")
    search = yaml.safe_load(SEARCH_PATH.read_text("utf-8"))
    base_lock = yaml.safe_load(BASE_LOCK_PATH.read_text("utf-8"))
    manifest = development_manifest(search)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(OUTPUT / "MANIFEST.csv", index=False)
    reference_lock = candidate_lock(
        base_lock, search, search["search_candidates"][0]
    )
    common = run_common(
        manifest, reference_lock,
        float(reference_lock["voi_controller"]["delivered_branch_weight"]),
    )
    summaries = []
    selected = None
    for candidate in search["search_candidates"]:
        lock = candidate_lock(base_lock, search, candidate)
        _, summary = run_candidate(manifest, common, lock, candidate, search)
        summaries.append(summary)
        pd.DataFrame(summaries).to_csv(OUTPUT / "SEARCH_SUMMARY.csv", index=False)
        if summary["m1_pass"]:
            selected = {"candidate": candidate, "summary": summary, "lock": lock}
            break
    decision = {
        "project": "DIRECTION5", "method": "VOI-ACCR-MPC",
        "milestone": "M1_R1_POST_M2_DEVELOPMENT",
        "status": "PASS" if selected else "FAIL",
        "m1_r1_pass": bool(selected),
        "selected_candidate": selected["candidate"] if selected else None,
        "selected_summary": selected["summary"] if selected else None,
        "candidates_completed": len(summaries),
        "m2_validation_outcomes_not_used_for_parameter_selection": True,
    }
    (OUTPUT / "DECISION.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(decision, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
