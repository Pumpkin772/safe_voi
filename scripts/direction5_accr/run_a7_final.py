"""Run the one-shot A7 final confirmation only after a passing locked A6."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.validation import simulate_plant_a_episode
from scripts.direction5_accr.run_a6_validation import (
    gate_decision,
    normal_profile,
    simulate_native,
)


LOCK_PATH = REPO / "configs/direction5_accr/a6_validation_lock.yaml"
SELECTION_PATH = REPO / "results_accr/A6/development/A6_FROZEN_SELECTION.json"
A6_SUMMARY = REPO / "results_accr/A6/validation/A6_SUMMARY.json"
RESULTS = REPO / "results_accr/A7"
CYCLE_PARTS = RESULTS / "cycle_parts"
NATIVE_PARTS = RESULTS / "native_parts"
EXECUTION_LOCK = RESULTS / "A7_EXECUTION_LOCK.json"
FINAL_MANIFEST = RESULTS / "A7_FINAL_MANIFEST.csv"
PROGRESS = REPO / "progress_accr/A7.json"
PRIMARY_METHODS = (
    "contract_only_recourse_mpc", "accr_mpc",
    "perfect_capability_recourse_oracle",
)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _common_row(
    *, seed: int, scenario_id: str, plant: str, mechanism: str,
    tension: str, period_s: float, condition: str, rng: np.random.Generator,
) -> dict[str, Any]:
    capability_time = float(rng.uniform(82.0, 112.0))
    relation = str(rng.choice(("before", "simultaneous", "after")))
    offset = -12.0 if relation == "before" else 12.0 if relation == "after" else 0.0
    area = str(rng.choice(("area0", "area1", "both")))
    sign = int(rng.choice((-1, 1)))
    magnitude_range = (0.035, 0.045) if plant == "B_native_ANDES_Kundur" else (0.052, 0.064)
    magnitude = float(rng.uniform(*magnitude_range))
    soc = float(rng.choice((0.40, 0.50, 0.60)))
    return {
        "scenario_id": scenario_id, "split": "final", "seed": seed,
        "design_cell": f"{plant}|{mechanism}|{tension}|{period_s:g}",
        "plant": plant, "mechanism": mechanism,
        "capability_mechanism": mechanism, "sg_tension": tension,
        "period_s": period_s, "control_period_s": period_s,
        "condition": condition, "known_ood": condition,
        "duration_s": 300.0, "capability_change_time_s": capability_time,
        "load_event_time_s": capability_time + offset,
        "load_area": area, "load_sign": sign, "load_magnitude_pu": magnitude,
        "timing_relation": relation, "initial_soc": soc,
        "initial_soc_area1": soc, "initial_soc_area2": soc,
        "frequency_noise_std_hz": 0.0, "noise_std_hz": 0.0,
        "control_jitter_s": 0.0, "jitter_s": 0.0,
        "dropout_probability": 0.0, "probe_eligible": True,
        "contract_violation": False, "contract_status": "WITHIN_CONTRACT",
        "materiality_positive": mechanism == "power_drop",
        "factor_assignment": "EXPLICIT_FINAL_DESIGN_PLUS_INDEPENDENT_SEEDED_DRAWS",
    }


def plant_a_manifest() -> pd.DataFrame:
    rows = []
    seed = 400
    index = 0
    for mechanism in ("power_drop", "ramp_drop"):
        for tension in ("low", "high"):
            for period_s in (2.0, 4.0):
                for condition in ("known", "OOD"):
                    for _replicate in range(3):
                        rng = np.random.default_rng(np.random.SeedSequence([20260810, seed, 401]))
                        rows.append(_common_row(
                            seed=seed, scenario_id=f"A7-F-A-{index:03d}",
                            plant="A_full_nonlinear", mechanism=mechanism,
                            tension=tension, period_s=period_s, condition=condition, rng=rng,
                        ))
                        seed += 1
                        index += 1
    return pd.DataFrame(rows)


def plant_b_manifest() -> pd.DataFrame:
    rows = []
    index = 0
    for mechanism in ("power_drop", "ramp_drop"):
        for period_s in (2.0, 4.0):
            for condition in ("known", "OOD"):
                seed = 448 + index
                rng = np.random.default_rng(np.random.SeedSequence([20260810, seed, 419]))
                rows.append(_common_row(
                    seed=seed, scenario_id=f"A7-F-B-{index:03d}",
                    plant="B_native_ANDES_Kundur", mechanism=mechanism,
                    tension="low", period_s=period_s, condition=condition, rng=rng,
                ))
                index += 1
    return pd.DataFrame(rows)


def normal_manifest() -> pd.DataFrame:
    return pd.DataFrame([{
        "scenario_id": "A7-F-N-456", "split": "final", "seed": 456,
        "design_cell": "A_full_nonlinear|normal1h|low|4",
        "plant": "A_full_nonlinear", "mechanism": "power_drop",
        "capability_mechanism": "none", "sg_tension": "low",
        "period_s": 4.0, "control_period_s": 4.0,
        "condition": "known", "known_ood": "known", "duration_s": 3600.0,
        "capability_change_time_s": 5000.0, "load_event_time_s": 0.0,
        "load_area": "both", "load_sign": 0, "load_magnitude_pu": np.nan,
        "timing_relation": "normal_profile", "initial_soc": 0.50,
        "initial_soc_area1": 0.50, "initial_soc_area2": 0.50,
        "frequency_noise_std_hz": 0.0, "noise_std_hz": 0.0,
        "control_jitter_s": 0.0, "jitter_s": 0.0,
        "dropout_probability": 0.0, "probe_eligible": True,
        "contract_violation": False, "contract_status": "WITHIN_CONTRACT",
        "materiality_positive": False,
        "factor_assignment": "INDEPENDENT_REAL_3600S_FINAL_PROFILE",
    }])


def contract_violation_manifest() -> pd.DataFrame:
    rows = []
    for index, seed in enumerate((457, 458, 459)):
        rng = np.random.default_rng(np.random.SeedSequence([20260810, seed, 433]))
        row = _common_row(
            seed=seed, scenario_id=f"A7-F-CV-{index:02d}",
            plant="A_full_nonlinear", mechanism="power_drop", tension="low",
            period_s=2.0 if index != 1 else 4.0,
            condition="OOD", rng=rng,
        )
        row.update({
            "contract_violation": True,
            "contract_status": "BELOW_GUARANTEED_FLOOR",
            "true_power_override_pu": 0.020,
            "true_ramp_override_pu_per_s": 0.010,
            "true_delay_override_s": 2.0,
            "materiality_positive": False,
        })
        rows.append(row)
    return pd.DataFrame(rows)


def _manifest_bytes() -> tuple[pd.DataFrame, bytes]:
    manifest = pd.concat(
        (plant_a_manifest(), plant_b_manifest(), normal_manifest(), contract_violation_manifest()),
        ignore_index=True, sort=False,
    )
    return manifest, manifest.to_csv(index=False).encode("utf-8")


def establish_execution_lock(selection: dict, a6: dict) -> None:
    manifest, payload = _manifest_bytes()
    expected = digest_bytes(payload)
    RESULTS.mkdir(parents=True, exist_ok=True)
    if EXECUTION_LOCK.is_file():
        frozen = json.loads(EXECUTION_LOCK.read_text("utf-8"))
        if frozen["final_manifest_sha256"] != expected:
            raise RuntimeError("A7 final manifest changed after the one-shot lock")
        if digest_bytes(FINAL_MANIFEST.read_bytes()) != expected:
            raise RuntimeError("stored A7 final manifest no longer matches its pre-execution hash")
        return
    FINAL_MANIFEST.write_bytes(payload)
    config_sha = digest_bytes(LOCK_PATH.read_bytes())
    selection_sha = digest_bytes(SELECTION_PATH.read_bytes())
    execution = {
        "project": "DIRECTION5", "stage": "A7", "one_shot": True,
        "algorithm_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "a6_status": a6["status"],
        "selected_probe_policy": selection["selected_probe_policy"],
        "selected_delivered_branch_weight": selection["selected_delivered_branch_weight"],
        "final_seed_range": [400, 459],
        "final_manifest_sha256": expected,
        "config_sha256": config_sha, "selection_sha256": selection_sha,
        "post_result_tuning_allowed": False,
        "execution_state": "STARTED_RESUMABLE_SAME_LOCK",
    }
    EXECUTION_LOCK.write_text(json.dumps(execution, indent=2) + "\n", encoding="utf-8")


def _native_part(scenario_id: str, method: str) -> Path:
    return NATIVE_PARTS / f"{scenario_id}__{method}.csv"


def native_worker(index: int, method: str) -> None:
    lock = yaml.safe_load(LOCK_PATH.read_text("utf-8"))
    selection = json.loads(SELECTION_PATH.read_text("utf-8"))
    scenario = plant_b_manifest().iloc[int(index)]
    result = simulate_native(
        scenario.to_dict(), method, lock,
        float(selection["selected_delivered_branch_weight"]),
        cycle_parts=CYCLE_PARTS,
    )
    NATIVE_PARTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([result]).to_csv(_native_part(str(scenario.scenario_id), method), index=False)


def _run_native_isolated(index: int, method: str) -> None:
    environment = os.environ.copy()
    environment.update({"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--native-worker", str(index), method],
        cwd=REPO, env=environment, check=True,
    )


def _run_plant_a_group(
    manifest: pd.DataFrame,
    methods: tuple[str, ...],
    lock: dict,
    weight: float,
    checkpoint_path: Path,
) -> pd.DataFrame:
    rows = pd.read_csv(checkpoint_path).to_dict("records") if checkpoint_path.is_file() else []
    index_by_key = {(str(row["scenario_id"]), str(row["method"])): i for i, row in enumerate(rows)}
    for _, scenario in manifest.iterrows():
        for method in methods:
            key = (str(scenario.scenario_id), method)
            cycle = CYCLE_PARTS / f"{scenario.scenario_id}__{method}.parquet"
            if key in index_by_key and cycle.is_file():
                continue
            result = simulate_plant_a_episode(
                scenario.to_dict(), method, lock, weight, cycle_output_path=cycle,
            )
            if key in index_by_key:
                rows[index_by_key[key]] = result
            else:
                index_by_key[key] = len(rows)
                rows.append(result)
            pd.DataFrame(rows).to_csv(checkpoint_path, index=False)
    return pd.DataFrame(rows)


def main() -> None:
    a6 = json.loads(A6_SUMMARY.read_text("utf-8"))
    if a6["status"] != "PASS":
        raise RuntimeError("A7 is forbidden because locked A6 did not pass")
    if (RESULTS / "A7_SUMMARY.json").is_file():
        print((RESULTS / "A7_SUMMARY.json").read_text("utf-8"))
        return
    lock = yaml.safe_load(LOCK_PATH.read_text("utf-8"))
    selection = json.loads(SELECTION_PATH.read_text("utf-8"))
    establish_execution_lock(selection, a6)
    weight = float(selection["selected_delivered_branch_weight"])

    plant_a = plant_a_manifest()
    plant_b = plant_b_manifest()
    normal = normal_manifest()
    violation = contract_violation_manifest()
    plant_a.to_csv(RESULTS / "A7_PLANT_A_MANIFEST.csv", index=False)
    plant_b.to_csv(RESULTS / "A7_PLANT_B_MANIFEST.csv", index=False)
    normal.to_csv(RESULTS / "A7_NORMAL1H_MANIFEST.csv", index=False)
    violation.to_csv(RESULTS / "A7_CONTRACT_VIOLATION_MANIFEST.csv", index=False)

    core = _run_plant_a_group(
        plant_a, PRIMARY_METHODS, lock, weight,
        RESULTS / "A7_CORE_EPISODES_CHECKPOINT.csv",
    )
    core_rows = core.to_dict("records")
    core_index = {
        (str(row["scenario_id"]), str(row["method"])): index
        for index, row in enumerate(core_rows)
    }
    for native_index, scenario in plant_b.iterrows():
        for method in PRIMARY_METHODS:
            key = (str(scenario.scenario_id), method)
            cycle = CYCLE_PARTS / f"{scenario.scenario_id}__{method}.parquet"
            if key in core_index and cycle.is_file():
                continue
            part = _native_part(str(scenario.scenario_id), method)
            if not part.is_file() or not cycle.is_file():
                _run_native_isolated(int(native_index), method)
            result = pd.read_csv(part).iloc[0].to_dict()
            if key in core_index:
                core_rows[core_index[key]] = result
            else:
                core_index[key] = len(core_rows)
                core_rows.append(result)
            pd.DataFrame(core_rows).to_csv(RESULTS / "A7_CORE_EPISODES_CHECKPOINT.csv", index=False)
    core = pd.DataFrame(core_rows)
    core.to_csv(RESULTS / "A7_ALL_CORE_EPISODES.csv", index=False)

    violation_episodes = _run_plant_a_group(
        violation, ("contract_only_recourse_mpc", "accr_mpc"), lock, weight,
        RESULTS / "A7_CONTRACT_VIOLATION_EPISODES_CHECKPOINT.csv",
    )
    violation_episodes["counted_in_guarantee_gate"] = False
    violation_episodes["classification"] = "PHYSICAL_CAPABILITY_BELOW_CONTRACT_OUTSIDE_GUARANTEE_DOMAIN"
    violation_episodes.to_csv(RESULTS / "A7_CONTRACT_VIOLATION_EPISODES.csv", index=False)

    normal_checkpoint = RESULTS / "A7_NORMAL1H_EPISODES_CHECKPOINT.csv"
    normal_rows = pd.read_csv(normal_checkpoint).to_dict("records") if normal_checkpoint.is_file() else []
    normal_index = {str(row["method"]): i for i, row in enumerate(normal_rows)}
    profile = normal_profile(456)
    scenario = normal.iloc[0]
    for method in ("contract_only_recourse_mpc", "accr_mpc"):
        cycle = CYCLE_PARTS / f"{scenario.scenario_id}__{method}.parquet"
        if method in normal_index and cycle.is_file():
            continue
        result = simulate_plant_a_episode(
            scenario.to_dict(), method, lock, weight,
            normal_profile=profile, cycle_output_path=cycle,
        )
        if method in normal_index:
            normal_rows[normal_index[method]] = result
        else:
            normal_index[method] = len(normal_rows)
            normal_rows.append(result)
        pd.DataFrame(normal_rows).to_csv(normal_checkpoint, index=False)
    normal_episodes = pd.DataFrame(normal_rows)
    normal_episodes.to_csv(RESULTS / "A7_NORMAL1H_EPISODES.csv", index=False)

    gates, summary = gate_decision(
        core, normal_episodes, lock, output_dir=RESULTS, artifact_prefix="A7",
    )
    summary.update({
        "stage": "A7", "one_shot_final": True,
        "final_seeds_consumed": True,
        "final_manifest_sha256": json.loads(EXECUTION_LOCK.read_text("utf-8"))["final_manifest_sha256"],
        "contract_violation_scenarios": int(violation.scenario_id.nunique()),
        "contract_violation_counted_in_primary_gate": False,
        "next_stage": "A8",
    })
    gates.to_csv(RESULTS / "A7_ALL_GATES.csv", index=False)
    (RESULTS / "A7_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    failures = gates[gates.status.eq("FAIL")].copy()
    failures["deleted"] = False
    failures["standard_changed"] = False
    failures.to_csv(RESULTS / "A7_FAILURE_LEDGER.csv", index=False)
    execution = json.loads(EXECUTION_LOCK.read_text("utf-8"))
    execution["execution_state"] = "COMPLETED_NO_RETUNING"
    execution["final_status"] = summary["status"]
    EXECUTION_LOCK.write_text(json.dumps(execution, indent=2) + "\n", encoding="utf-8")
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps({
        "stage": "A7", "status": summary["status"],
        "one_shot_final": True, "next_stage": "A8",
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-worker", nargs=2, metavar=("INDEX", "METHOD"))
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.native_worker:
        native_worker(int(arguments.native_worker[0]), arguments.native_worker[1])
    else:
        main()
