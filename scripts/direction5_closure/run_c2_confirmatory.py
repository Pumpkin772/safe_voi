"""Lock and execute the one-time untouched-seed Direction5 confirmation."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.evaluation.corrected_statistics import (
    corrected_metric_summary,
    paired_failure_rows,
    paired_failure_table,
)
from direction5freq.evaluation.final_protocol import MECHANISMS
from scripts.direction5_final.run_r5_validation import (
    ALL_METHODS,
    PRIMARY_METHODS,
    simulate_plant_a,
    simulate_plant_b,
)


CONFIG = REPO / "configs/direction5_closure/confirmatory_protocol.yaml"
R5_LOCK = REPO / "configs/direction5_final/r5_validation_lock.yaml"
LOCK = REPO / "research_outputs_closure/02_CONFIRMATORY/FINAL_LOCK.json"
MANIFEST_DIR = REPO / "research_outputs_closure/02_CONFIRMATORY"
RESULTS = REPO / "results_closure/C2"
PARTS = RESULTS / "parts"
LOGS = REPO / "logs_closure/C2"
PROGRESS = REPO / "progress_closure"
MARKER = RESULTS / "FINAL_SEEDS_CONSUMED.json"
P_METHOD = "dcsv_cr_mpc"
B_METHOD = "contract_only_rolling_mpc"
SUPPLEMENTAL_METHODS = tuple(method for method in ALL_METHODS if method not in PRIMARY_METHODS)
KINDS = ("plant_a_primary", "plant_a_supplemental", "plant_b", "normal", "contract_violation")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def tree_sha(paths: list[Path]) -> str:
    hasher = hashlib.sha256()
    files = []
    for root in paths:
        if root.is_file():
            files.append(root)
        else:
            files.extend(path for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    for path in sorted(files, key=lambda value: value.relative_to(REPO).as_posix()):
        relative = path.relative_to(REPO).as_posix()
        hasher.update(relative.encode("utf-8"))
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True, encoding="utf-8").strip()


def load_config() -> dict[str, Any]:
    config = yaml.safe_load(CONFIG.read_text("utf-8"))
    if config["method"] != P_METHOD or config["primary_methods"] != list(PRIMARY_METHODS):
        raise RuntimeError("confirmatory protocol changes the frozen primary methods")
    r5 = yaml.safe_load(R5_LOCK.read_text("utf-8"))
    if config["gates"] != r5["gates"]:
        raise RuntimeError("confirmatory Gate differs from frozen validation Gate")
    if config["final_seeds"] != r5["final_seeds"]:
        raise RuntimeError("confirmatory final seeds differ from the frozen firewall")
    return config


def permute(values: list, cell: int, factor: int) -> np.ndarray:
    rng = np.random.default_rng(np.random.SeedSequence([20260805, 901, cell, factor]))
    return np.asarray(values, dtype=object)[rng.permutation(len(values))]


def plant_a_manifest() -> pd.DataFrame:
    config = load_config()
    seeds = list(map(int, config["final_seeds"]))
    cells = [(m, t, p) for m in MECHANISMS for t in ("low", "high") for p in (2.0, 4.0)]
    assignments: dict[int, list[int]] = {index: [] for index in range(len(cells))}
    for seed_index, seed in enumerate(seeds):
        assignments[seed_index % 12].append(seed)
        assignments[(seed_index + 6) % 12].append(seed)
    rows, scenario_index = [], 0
    for cell_index, (mechanism, tension, period_s) in enumerate(cells):
        cell_seeds = sorted(assignments[cell_index])
        if len(cell_seeds) != 10:
            raise RuntimeError("Plant-A final seed assignment is not balanced")
        magnitude = permute(["sustainable"] * 5 + ["bridge"] * 3 + ["infeasible"] * 2, cell_index, 1)
        timing = permute(["before"] * 4 + ["after"] * 3 + ["simultaneous"] * 3, cell_index, 2)
        area = permute(["area0"] * 4 + ["area1"] * 3 + ["both"] * 3, cell_index, 3)
        sign = permute([1] * 7 + [-1] * 3, cell_index, 4)
        condition = permute(["known"] * 5 + ["OOD"] * 5, cell_index, 5)
        soc = permute([0.35, 0.50, 0.65, 0.35, 0.50, 0.65, 0.35, 0.50, 0.65, 0.50], cell_index, 6)
        noise = permute([0.0, 0.0, 0.0001, 0.0001, 0.0002, 0.0002, 0.0, 0.0001, 0.0002, 0.0], cell_index, 7)
        jitter = permute([0.0, 0.0, 0.01, 0.01, 0.02, 0.02, 0.0, 0.01, 0.02, 0.0], cell_index, 8)
        dropout = permute([0.0, 0.0, 0.0, 0.001, 0.001, 0.002, 0.0, 0.001, 0.002, 0.0], cell_index, 9)
        repeated = permute([True, True] + [False] * 8, cell_index, 10)
        for local_index, seed in enumerate(cell_seeds):
            rng = np.random.default_rng(np.random.SeedSequence([20260805, 907, cell_index, seed]))
            capability_time = float(rng.uniform(100.0, 135.0))
            relation = str(timing[local_index])
            offset = float(rng.uniform(10.0, 22.0))
            load_time = capability_time - offset if relation == "before" else capability_time + offset if relation == "after" else capability_time
            rows.append({
                "scenario_id": f"C2-F-A-{scenario_index:03d}", "split": "confirmatory_final",
                "seed": seed, "plant": "A_full_nonlinear", "mechanism": mechanism,
                "sg_tension": tension, "period_s": period_s, "duration_s": 300.0,
                "magnitude_class": str(magnitude[local_index]), "timing_relation": relation,
                "load_area": str(area[local_index]), "load_sign": int(sign[local_index]),
                "condition": str(condition[local_index]), "capability_change_time_s": capability_time,
                "load_event_time_s": load_time,
                "second_capability_change_time_s": capability_time + 82.0 if bool(repeated[local_index]) else np.nan,
                "initial_soc": float(soc[local_index]), "frequency_noise_std_hz": float(noise[local_index]),
                "control_jitter_s": float(jitter[local_index]), "dropout_probability": float(dropout[local_index]),
                "nominal_warmup_s": 60.0,
                "factor_assignment": "LOCKED_CONFIRMATORY_INDEPENDENT_PER_FACTOR_PERMUTATIONS",
                "contract_violation": False,
            })
            scenario_index += 1
    frame = pd.DataFrame(rows)
    if len(frame) != 120 or frame.groupby(["mechanism", "sg_tension", "period_s"]).size().min() != 10:
        raise RuntimeError("Plant-A confirmatory matrix size mismatch")
    counts = frame.seed.value_counts()
    if set(counts.index) != set(seeds) or not counts.eq(2).all():
        raise RuntimeError("not every final seed is assigned exactly twice in Plant A")
    return frame


def plant_b_manifest() -> pd.DataFrame:
    seeds = list(map(int, load_config()["final_seeds"][:24]))
    rows, scenario_index = [], 0
    for mechanism_index, mechanism in enumerate(MECHANISMS):
        local_seeds = seeds[8 * mechanism_index:8 * (mechanism_index + 1)]
        periods = permute([2.0] * 4 + [4.0] * 4, 20 + mechanism_index, 1)
        signs = permute([1] * 5 + [-1] * 3, 20 + mechanism_index, 2)
        areas = permute(["area0"] * 3 + ["area1"] * 3 + ["both"] * 2, 20 + mechanism_index, 3)
        conditions = permute(["known"] * 4 + ["OOD"] * 4, 20 + mechanism_index, 4)
        operating = permute(["base"] * 4 + ["stressed"] * 4, 20 + mechanism_index, 5)
        noise = permute([0.0] * 4 + [0.00015] * 4, 20 + mechanism_index, 6)
        jitter = permute([0.0] * 4 + [0.01] * 4, 20 + mechanism_index, 7)
        for local_index, seed in enumerate(local_seeds):
            rng = np.random.default_rng(np.random.SeedSequence([20260805, 919, mechanism_index, seed]))
            capability_time = float(rng.uniform(100.0, 130.0))
            relation = ("before", "after", "simultaneous")[local_index % 3]
            load_time = capability_time + (-14.0 if relation == "before" else 14.0 if relation == "after" else 0.0)
            rows.append({
                "scenario_id": f"C2-F-B-{scenario_index:03d}", "split": "confirmatory_final",
                "seed": seed, "plant": "B_native_ANDES_Kundur", "mechanism": mechanism,
                "sg_tension": str(operating[local_index]), "operating_point": str(operating[local_index]),
                "period_s": float(periods[local_index]), "duration_s": 300.0,
                "magnitude_class": "sustainable", "timing_relation": relation,
                "load_area": str(areas[local_index]), "load_sign": int(signs[local_index]),
                "condition": str(conditions[local_index]), "capability_change_time_s": capability_time,
                "load_event_time_s": load_time, "second_capability_change_time_s": np.nan,
                "initial_soc": float(rng.choice([0.40, 0.50, 0.60])),
                "frequency_noise_std_hz": float(noise[local_index]),
                "control_jitter_s": float(jitter[local_index]),
                "dropout_probability": 0.001 if local_index in (2, 6) else 0.0,
                "nominal_warmup_s": 60.0,
                "factor_assignment": "LOCKED_CONFIRMATORY_INDEPENDENT_PER_FACTOR_PERMUTATIONS",
                "contract_violation": False,
            })
            scenario_index += 1
    return pd.DataFrame(rows)


def normal_manifest() -> pd.DataFrame:
    rows = []
    for index, seed in enumerate(load_config()["normal_profile_seeds"]):
        rows.append({
            "scenario_id": f"C2-N-{index:02d}", "split": "confirmatory_registered_normal_profile",
            "seed": int(seed), "plant": "A_full_nonlinear", "mechanism": MECHANISMS[index % 3],
            "sg_tension": "low", "period_s": 4.0, "duration_s": 3600.0,
            "magnitude_class": "normal_profile", "timing_relation": "independent_profile",
            "load_area": "both", "load_sign": 1, "condition": "known" if index < 3 else "OOD",
            "capability_change_time_s": 1100.0 + 100.0 * index, "load_event_time_s": 0.0,
            "second_capability_change_time_s": 2400.0 + 40.0 * index,
            "initial_soc": 0.50, "frequency_noise_std_hz": 0.0001,
            "control_jitter_s": 0.01, "dropout_probability": 0.001,
            "nominal_warmup_s": 60.0, "factor_assignment": "REGISTERED_SYNTHETIC_PROFILE_FACTORS",
            "profile_provenance": "SYNTHETIC_AR2_MULTI_SINE_REGISTERED_NOT_PUBLIC_MEASURED",
            "contract_violation": False,
        })
    return pd.DataFrame(rows)


def contract_violation_manifest() -> pd.DataFrame:
    base = plant_a_manifest().groupby(
        ["mechanism", "sg_tension", "period_s"], group_keys=False
    ).head(1).iloc[:6].copy()
    base["scenario_id"] = [f"C2-CV-{index:02d}" for index in range(6)]
    base["split"] = "confirmatory_contract_violation_separate"
    base["seed"] = np.arange(154, 160)
    base["contract_violation"] = True
    base["magnitude_class"] = "bridge"
    base["load_sign"] = 1
    base["condition"] = "contract_violation"
    return base


def manifest(kind: str) -> pd.DataFrame:
    if kind in {"plant_a_primary", "plant_a_supplemental"}:
        frame = plant_a_manifest()
        return frame if kind == "plant_a_primary" else frame.groupby(["mechanism", "sg_tension", "period_s"], group_keys=False).head(2).reset_index(drop=True)
    if kind == "plant_b":
        return plant_b_manifest()
    if kind == "normal":
        return normal_manifest()
    if kind == "contract_violation":
        return contract_violation_manifest()
    raise ValueError(kind)


def methods_for(kind: str) -> tuple[str, ...]:
    if kind in {"plant_a_primary", "plant_b"}:
        return PRIMARY_METHODS
    if kind == "plant_a_supplemental":
        return SUPPLEMENTAL_METHODS
    if kind == "normal":
        return ALL_METHODS
    if kind == "contract_violation":
        return (P_METHOD,)
    raise ValueError(kind)


def combined_manifest() -> pd.DataFrame:
    frames = []
    for kind in KINDS:
        frame = manifest(kind).copy()
        frame.insert(0, "dataset_kind", kind)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False)


def part_paths(kind: str, scenario_id: str, method: str) -> tuple[Path, Path]:
    stem = f"{scenario_id}__{method}"
    return PARTS / kind / f"{stem}__summary.parquet", PARTS / kind / f"{stem}__cycles.parquet"


def prepare_lock() -> None:
    parts_exist = PARTS.exists() and any(PARTS.rglob("*.parquet"))
    if LOCK.exists() or MARKER.exists() or parts_exist:
        raise RuntimeError("confirmatory evidence already exists; refusing to relock")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    PROGRESS.mkdir(parents=True, exist_ok=True)
    for kind in KINDS:
        manifest(kind).to_csv(MANIFEST_DIR / f"{kind.upper()}_MANIFEST.csv", index=False)
    all_manifest = combined_manifest()
    all_manifest.to_csv(MANIFEST_DIR / "FINAL_MANIFEST.csv", index=False)
    method_hash = tree_sha([
        REPO / "src/direction5freq",
        REPO / "scripts/direction5_final/run_r5_validation.py",
        R5_LOCK,
    ])
    lock = {
        "schema": "direction5.closure.final_lock.v1", "project": "DIRECTION5",
        "method": "DCSV-CR-MPC_FROZEN", "source_commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"), "created_utc": utc_now(),
        "method_source_sha256": method_hash,
        "execution_source_sha256": file_sha(Path(__file__).resolve()),
        "statistics_source_sha256": file_sha(REPO / "src/direction5freq/evaluation/corrected_statistics.py"),
        "protocol_sha256": file_sha(CONFIG), "r5_lock_sha256": file_sha(R5_LOCK),
        "manifest_sha256": file_sha(MANIFEST_DIR / "FINAL_MANIFEST.csv"),
        "goal_sha256": file_sha(REPO / "research/direction5_closure_confirmation_and_manuscript/CODEX_GOAL.md"),
        "final_seeds": load_config()["final_seeds"], "final_seeds_consumed": False,
        "method_weights_thresholds_scenarios_changed": False,
        "validation_bug_found": False, "execution_permitted_once": True,
        "post_result_tuning_forbidden": True,
    }
    LOCK.write_text(json.dumps(lock, indent=2) + "\n", "utf-8")
    (PROGRESS / "C2_LOCK.json").write_text(json.dumps({
        "schema": "direction5.closure.progress.v1", "stage": "C2_LOCK",
        "status": "PASS", "gate": "A2_CONFIRMATORY_HASH_LOCK",
        "final_seeds_consumed": False, "lock_sha256": file_sha(LOCK),
        "manifest_rows": len(all_manifest), "next_stage": "C2_EXECUTE_ONCE",
    }, indent=2) + "\n", "utf-8")
    print(json.dumps(lock, indent=2))


def verify_lock() -> dict:
    if not LOCK.is_file():
        raise RuntimeError("FINAL_LOCK.json is missing")
    lock = json.loads(LOCK.read_text("utf-8"))
    checks = {
        "method_source_sha256": tree_sha([
            REPO / "src/direction5freq", REPO / "scripts/direction5_final/run_r5_validation.py", R5_LOCK,
        ]),
        "execution_source_sha256": file_sha(Path(__file__).resolve()),
        "statistics_source_sha256": file_sha(REPO / "src/direction5freq/evaluation/corrected_statistics.py"),
        "protocol_sha256": file_sha(CONFIG), "r5_lock_sha256": file_sha(R5_LOCK),
        "manifest_sha256": file_sha(MANIFEST_DIR / "FINAL_MANIFEST.csv"),
        "goal_sha256": file_sha(REPO / "research/direction5_closure_confirmation_and_manuscript/CODEX_GOAL.md"),
    }
    mismatches = {name: {"locked": lock[name], "actual": value} for name, value in checks.items() if lock[name] != value}
    if mismatches:
        raise RuntimeError(f"confirmatory lock mismatch: {mismatches}")
    return lock


def run_worker(kind: str, index: int, method: str) -> None:
    row = manifest(kind).iloc[int(index)]
    if kind == "plant_b":
        summary, cycles = simulate_plant_b(row.to_dict(), method)
    else:
        summary, cycles = simulate_plant_a(row.to_dict(), method, normal=kind == "normal")
    summary["dataset_kind"] = kind
    cycles["dataset_kind"] = kind
    summary_path, cycles_path = part_paths(kind, str(row.scenario_id), method)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([summary]).to_parquet(summary_path, index=False, compression="zstd")
    cycles.to_parquet(cycles_path, index=False, compression="zstd")


def tasks(kind: str) -> list[tuple[str, int, str]]:
    return [(kind, index, method) for index in range(len(manifest(kind))) for method in methods_for(kind)]


def subprocess_task(task: tuple[str, int, str]) -> tuple[tuple[str, int, str], int, str]:
    kind, index, method = task
    row = manifest(kind).iloc[index]
    summary_path, cycles_path = part_paths(kind, str(row.scenario_id), method)
    if summary_path.is_file() and cycles_path.is_file():
        return task, 0, "RESUME_SAME_LOCK_EXISTING_PART"
    environment = os.environ.copy()
    environment.update({
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
    })
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker", kind, str(index), method],
        cwd=REPO, env=environment, capture_output=True, text=True,
    )
    log = LOGS / kind / f"{row.scenario_id}__{method}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(completed.stdout + ("\nSTDERR\n" + completed.stderr if completed.stderr else ""), "utf-8")
    return task, completed.returncode, str(log)


def execute_kind(kind: str, workers: int) -> None:
    task_list = tasks(kind)
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(subprocess_task, task) for task in task_list]
        for count, future in enumerate(as_completed(futures), start=1):
            task, code, detail = future.result()
            if code:
                failures.append((task, detail))
            if count % 10 == 0 or count == len(task_list):
                print(f"C2 {kind}: {count}/{len(task_list)} complete; failures={len(failures)}", flush=True)
    if failures:
        raise RuntimeError(f"C2 worker failures: {failures[:5]}")


def load_parts(kind: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    summaries, cycles = [], []
    for index, row in manifest(kind).iterrows():
        for method in methods_for(kind):
            summary_path, cycles_path = part_paths(kind, str(row.scenario_id), method)
            summaries.append(pd.read_parquet(summary_path).iloc[0].to_dict())
            cycles.append(pd.read_parquet(cycles_path))
    return pd.DataFrame(summaries), pd.concat(cycles, ignore_index=True, sort=False)


def summarize(
    plant_a: pd.DataFrame, supplemental: pd.DataFrame, plant_b: pd.DataFrame,
    normal: pd.DataFrame, contract: pd.DataFrame, cycles: pd.DataFrame,
) -> dict:
    config = load_config()
    core = pd.concat((plant_a, plant_b), ignore_index=True, sort=False)
    rows = paired_failure_rows(core, P_METHOD, B_METHOD)
    failure_table = paired_failure_table(rows)
    summary, bootstrap, pairs = corrected_metric_summary(
        rows, P_METHOD, B_METHOD, resamples=int(config["bootstrap_resamples"]),
        bootstrap_seed=int(config["bootstrap_seed"]),
    )
    failure_table.to_csv(MANIFEST_DIR / "FINAL_PAIRED_FAILURES.csv", index=False)
    summary.to_csv(MANIFEST_DIR / "FINAL_STATISTICS.csv", index=False)
    bootstrap.to_csv(MANIFEST_DIR / "FINAL_BOOTSTRAP.csv", index=False)
    pairs.to_parquet(RESULTS / "FINAL_PAIRED_ROWS.parquet", index=False, compression="zstd")

    p_eval = core[(core.method.eq(P_METHOD)) & core.evaluation_status.eq("EVALUATED")]
    b_eval = core[(core.method.eq(B_METHOD)) & core.evaluation_status.eq("EVALUATED")]
    success_drop = float(b_eval.physical_success.mean() - p_eval.physical_success.mean())
    terminal_drop = float(b_eval.terminal_recovery.mean() - p_eval.terminal_recovery.mean())
    primary = summary[summary.analysis.eq("both_success")]
    primary_boot = bootstrap[bootstrap.analysis.eq("both_success")]
    metric_gate = primary.merge(primary_boot[["metric", "relative_improvement_lower"]], on="metric")
    metric_gate["passes"] = (
        metric_gate.aggregate_mean_relative_improvement.ge(config["gates"]["relative_improvement_min"])
        & metric_gate.relative_improvement_lower.gt(config["gates"]["bootstrap_relative_lower_min"])
    )
    metric_gate.to_csv(MANIFEST_DIR / "FINAL_CORE_METRIC_GATES.csv", index=False)
    failure_aware = summary[summary.analysis.eq("failure_aware") & summary.penalty_multiplier.eq(2.0)]

    dcsv = cycles[(cycles.method.eq(P_METHOD)) & cycles.attempted_solver_calls.fillna(0).gt(0)].copy()
    decisions = len(dcsv)
    raw_calls = int(dcsv.attempted_solver_calls.sum())
    restorations = int(dcsv.restoration_used.sum())
    fallbacks = int(dcsv.fallback_used.sum())
    primary_actions = decisions - restorations - fallbacks
    denominator = pd.DataFrame([
        ("primary_accepted_actions", primary_actions, True),
        ("restoration_accepted_actions", restorations, True),
        ("backup_actions", fallbacks, True), ("unhandled_actions", 0, True),
        ("attempted_optimization_decisions", decisions, True),
        ("raw_solver_invocations", raw_calls, False),
        ("physical_infeasibility_preclassifications", int((cycles.method.eq(P_METHOD) & cycles.attempted_solver_calls.fillna(0).eq(0)).sum()), False),
    ], columns=("quantity", "count", "in_attempted_decision_denominator"))
    denominator["decision_identity_holds"] = primary_actions + restorations + fallbacks == decisions
    denominator["raw_invocation_identity_holds"] = primary_actions + 2 * restorations + 2 * fallbacks == raw_calls
    denominator.to_csv(MANIFEST_DIR / "FINAL_SOLVER_DENOMINATOR.csv", index=False)

    known = core[(core.method.eq(P_METHOD)) & core.condition.eq("known") & core.evaluation_status.eq("EVALUATED")]
    known_backup = float(known.fallback_calls.sum() / max(known.controller_calls.sum(), 1))
    numerical_fraction = float(dcsv.numerical_failure.sum() / max(raw_calls, 1))
    p99_ratio = float(np.quantile(dcsv.solve_time_s / dcsv.period_s, 0.99))
    direction_rows = []
    for plant, block in core[core.evaluation_status.eq("EVALUATED")].groupby("plant"):
        wide = block.pivot(index="scenario_id", columns="method", values="frequency_peak_hz")
        difference = float((wide[B_METHOD] - wide[P_METHOD]).mean())
        direction_rows.append({"plant": plant, "paired_frequency_absolute_difference_hz": difference, "positive_direction": difference > 0.0})
    directions = pd.DataFrame(direction_rows)
    directions.to_csv(MANIFEST_DIR / "FINAL_PLANT_DIRECTION.csv", index=False)
    known_ood = core[core.evaluation_status.eq("EVALUATED")].groupby(
        ["plant", "condition", "method"], as_index=False
    ).agg(
        episodes=("scenario_id", "size"), success_rate=("physical_success", "mean"),
        frequency_peak_hz=("frequency_peak_hz", "mean"), ace_iae_pu_s=("ace_iae_pu_s", "mean"),
        tie_rms_pu=("tie_rms_pu", "mean"), restoration_calls=("restoration_calls", "sum"),
        fallback_calls=("fallback_calls", "sum"), numerical_failure_calls=("numerical_failure_calls", "sum"),
    )
    known_ood.to_csv(MANIFEST_DIR / "FINAL_KNOWN_OOD.csv", index=False)
    domain = core.groupby(["registered_domain", "evaluation_status", "method"], as_index=False).agg(
        episodes=("scenario_id", "size"), successes=("physical_success", "sum"), hard_violations=("hard_violation", "sum"),
    )
    domain.to_csv(MANIFEST_DIR / "FINAL_DOMAIN_STATISTICS.csv", index=False)
    normal_quality = normal.groupby("method", as_index=False).agg(
        episodes=("scenario_id", "size"), frequency_peak_hz=("frequency_peak_hz", "max"),
        frequency_rms_hz=("frequency_rms_hz", "max"), ace_iae_pu_s=("ace_iae_pu_s", "mean"),
        tie_rms_pu=("tie_rms_pu", "mean"), terminal_recovery_rate=("terminal_recovery", "mean"),
        fallback_calls=("fallback_calls", "sum"), hard_violations=("hard_violation", "sum"),
    )
    normal_quality["quality_gate"] = (
        normal_quality.frequency_peak_hz.le(config["gates"]["normal_frequency_peak_hz_max"])
        & normal_quality.frequency_rms_hz.le(config["gates"]["normal_frequency_rms_hz_max"])
        & normal_quality.terminal_recovery_rate.eq(1.0) & normal_quality.hard_violations.eq(0)
    )
    normal_quality.to_csv(MANIFEST_DIR / "FINAL_NORMAL1H.csv", index=False)
    contract[[
        "scenario_id", "contract_violation_detection_calls", "frequency_peak_hz",
        "frequency_rms_hz", "terminal_recovery", "fallback_calls", "hard_violation",
    ]].to_csv(MANIFEST_DIR / "FINAL_CONTRACT_VIOLATION.csv", index=False)

    confirm_gates = {
        "success_drop_at_most_2pp": success_drop <= config["gates"]["success_drop_max_pp"] / 100.0,
        "failure_aware_not_worse": bool(failure_aware.aggregate_mean_relative_improvement.ge(0.0).all()),
        "two_of_three_metrics_improve_8pct_positive_ci": int(metric_gate.passes.sum()) >= config["gates"]["core_metrics_required"],
        "terminal_recovery_not_worse": terminal_drop <= config["gates"]["terminal_recovery_drop_max_pp"] / 100.0,
        "hard_violations_zero": bool(not core.hard_violation.any() and not supplemental.hard_violation.any() and not normal.hard_violation.any()),
        "known_contract_backup_at_most_1pct": known_backup <= config["gates"]["known_contract_backup_fraction_max"],
        "numerical_failure_at_most_0p1pct": numerical_fraction <= config["gates"]["numerical_failure_fraction_max"],
        "p99_below_half_period": p99_ratio < config["gates"]["p99_solve_fraction_of_period_max"],
        "plant_a_b_direction_consistent_positive": bool(len(directions) == 2 and directions.positive_direction.all()),
        "normal1h_frequency_quality": bool(normal_quality.quality_gate.all()),
        "contract_violation_separate_and_detected": bool(contract.evaluation_status.eq("CONTRACT_VIOLATION_OUTSIDE_GUARANTEE_DOMAIN").all() and contract.contract_violation_detection_calls.gt(0).all()),
        "solver_denominator_identities_hold": bool(denominator.decision_identity_holds.all() and denominator.raw_invocation_identity_holds.all()),
    }
    validation = json.loads((REPO / "progress_final/R5.json").read_text("utf-8"))
    confirm_positive = bool(
        confirm_gates["success_drop_at_most_2pp"]
        and confirm_gates["two_of_three_metrics_improve_8pct_positive_ci"]
        and confirm_gates["plant_a_b_direction_consistent_positive"]
        and confirm_gates["hard_violations_zero"]
    )
    joint_positive = validation["status"] == "PASS" and confirm_positive
    result = {
        "schema": "direction5.closure.confirmatory_summary.v1", "stage": "C2",
        "execution_complete": True, "lock_sha256": file_sha(LOCK),
        "plant_a_scenarios": len(plant_a_manifest()), "plant_b_scenarios": len(plant_b_manifest()),
        "core_method_rows": len(core), "supplemental_rows": len(supplemental),
        "normal1h_rows": len(normal), "contract_violation_rows": len(contract),
        "success_drop_pp": 100.0 * success_drop, "terminal_recovery_drop_pp": 100.0 * terminal_drop,
        "core_metrics_passing": int(metric_gate.passes.sum()), "known_backup_fraction": known_backup,
        "optimization_decisions": decisions, "raw_solver_invocations": raw_calls,
        "restoration_calls": restorations, "fallback_calls": fallbacks,
        "numerical_failures": int(dcsv.numerical_failure.sum()), "accuracy_warnings": int(dcsv.accuracy_warning.sum()),
        "p99_solve_fraction_of_period": p99_ratio, "confirmatory_gates": confirm_gates,
        "confirmatory_positive_gate": confirm_positive,
        "validation_positive_gate": validation["status"] == "PASS",
        "joint_validation_confirmatory_positive": joint_positive,
        "final_seeds_consumed": True, "post_result_tuning_permitted": False,
        "next_stage": "C3_NEGATIVE_MANUSCRIPT" if not joint_positive else "C3_BOUNDED_POSITIVE_MANUSCRIPT",
    }
    (RESULTS / "C2_SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    (MANIFEST_DIR / "FINAL_GATE_DECISION.csv").write_text(
        pd.DataFrame([{"gate": name, "passed": passed} for name, passed in confirm_gates.items()]).to_csv(index=False), "utf-8"
    )
    return result


def execute_once(resume: bool) -> None:
    lock = verify_lock()
    if MARKER.exists():
        marker = json.loads(MARKER.read_text("utf-8"))
        if marker["status"] == "COMPLETE":
            raise RuntimeError("final seeds were already consumed and completed; rerun forbidden")
        if not resume or marker.get("lock_sha256") != file_sha(LOCK):
            raise RuntimeError("an interrupted final run may only resume under the identical lock")
    else:
        if resume:
            raise RuntimeError("--resume requested but no interrupted marker exists")
        parts_exist = PARTS.exists() and any(PARTS.rglob("*.parquet"))
        if parts_exist:
            raise RuntimeError("unregistered confirmatory parts exist before seed consumption")
        RESULTS.mkdir(parents=True, exist_ok=True)
        marker = {
            "schema": "direction5.closure.final_seed_consumption.v1", "status": "RUNNING",
            "started_utc": utc_now(), "lock_sha256": file_sha(LOCK),
            "final_seeds": lock["final_seeds"], "final_seeds_consumed": True,
            "single_execution": True, "post_result_tuning_forbidden": True,
        }
        MARKER.write_text(json.dumps(marker, indent=2) + "\n", "utf-8")
    started = time.perf_counter()
    workers = int(load_config()["workers"])
    for kind in KINDS:
        execute_kind(kind, workers)
    plant_a, plant_a_cycles = load_parts("plant_a_primary")
    supplemental, supplemental_cycles = load_parts("plant_a_supplemental")
    plant_b, plant_b_cycles = load_parts("plant_b")
    normal, normal_cycles = load_parts("normal")
    contract, contract_cycles = load_parts("contract_violation")
    all_episodes = pd.concat((plant_a, plant_b, supplemental, normal, contract), ignore_index=True, sort=False)
    all_cycles = pd.concat((plant_a_cycles, plant_b_cycles, supplemental_cycles, normal_cycles, contract_cycles), ignore_index=True, sort=False)
    all_cycles["optimization_attempted"] = all_cycles.attempted_solver_calls.fillna(0).gt(0)
    all_episodes.to_parquet(MANIFEST_DIR / "FINAL_EPISODES.parquet", index=False, compression="zstd")
    all_cycles.to_parquet(MANIFEST_DIR / "FINAL_CYCLES.parquet", index=False, compression="zstd")
    result = summarize(plant_a, supplemental, plant_b, normal, contract, all_cycles)
    result["elapsed_s"] = time.perf_counter() - started
    (RESULTS / "C2_SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    marker.update({"status": "COMPLETE", "completed_utc": utc_now(), "summary_sha256": file_sha(RESULTS / "C2_SUMMARY.json")})
    MARKER.write_text(json.dumps(marker, indent=2) + "\n", "utf-8")
    progress = {
        "schema": "direction5.closure.progress.v1", "stage": "C2", "status": "PASS",
        "gate": "A2_ONE_TIME_CONFIRMATORY_EXECUTION_COMPLETE",
        "confirmatory_positive_gate": result["confirmatory_positive_gate"],
        "joint_validation_confirmatory_positive": result["joint_validation_confirmatory_positive"],
        "final_seeds_consumed": True, "post_result_tuning_permitted": False,
        "lock_sha256": file_sha(LOCK), "next_stage": result["next_stage"],
    }
    (PROGRESS / "C2.json").write_text(json.dumps(progress, indent=2) + "\n", "utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-lock", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--worker", nargs=3, metavar=("KIND", "INDEX", "METHOD"))
    args = parser.parse_args()
    selected = sum((args.prepare_lock, args.execute, args.worker is not None))
    if selected != 1:
        parser.error("choose exactly one of --prepare-lock, --execute or --worker")
    if args.prepare_lock:
        prepare_lock()
    elif args.execute:
        execute_once(args.resume)
    else:
        run_worker(args.worker[0], int(args.worker[1]), args.worker[2])
