"""Guarded independent nonlinear Plant-A confirmation of the frozen zero region."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from direction5freq.accr.resource_guard import (
    GIB, ResourceLimits, run_guarded, wait_for_memory_preflight,
)


ROOT = Path(__file__).resolve().parents[1]


def manifest(split: str) -> list[dict[str, object]]:
    if split == "validation_1":
        cells = (
            ("V1_A_2S_KNOWN", 2.0, "medium", "balanced", "known", 7300, 0.045, 0.060, 0.040, 0.70),
            ("V1_A_2S_OOD", 2.0, "high", "regional_responsibility", "ood", 7310, 0.070, 0.048, 0.028, 1.30),
        )
    elif split == "validation_2":
        cells = (
            ("V2_A_4S_KNOWN", 4.0, "low", "balanced", "known", 7400, 0.055, 0.070, 0.045, 0.60),
            ("V2_A_4S_OOD", 4.0, "high", "resource_economy", "ood", 7410, 0.070, 0.050, 0.030, 1.20),
        )
    else:
        raise ValueError(split)
    rows: list[dict[str, object]] = []
    for cell, period, tension, objective, condition, first_seed, load, power, ramp, delay in cells:
        for repeat in range(10):
            seed = first_seed + repeat
            rng_offset = (repeat - 4.5) / 9.0
            rows.append({
                "scenario_id": f"{cell}_{seed}", "design_cell": cell,
                "split": split, "known_ood": condition, "seed": seed,
                "duration_s": 300.0, "period_s": period,
                "sg_tension": tension, "objective": objective,
                "initial_soc": 0.50 + 0.08 * rng_offset,
                "capability_change_time_s": 100.0 + 10.0 * (repeat % 3),
                "load_event_time_s": 150.0 + 8.0 * (repeat % 4),
                "load_magnitude_pu": load, "load_sign": 1.0,
                "load_area": ("both", "area0", "area1")[repeat % 3],
                "true_power_pu": power, "true_ramp_pu_per_s": ramp,
                "true_delay_s": delay,
                "frequency_noise_std_hz": 0.001,
                "poi_noise_std_pu": 0.0008 + 0.0004 * (repeat % 2),
            })
    return rows


def worker(arguments: argparse.Namespace) -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("refusing unguarded nonlinear validation")
    import pandas as pd

    from nonlinear_boundary_validation import simulate_plant_a
    from selective_boundary_policy import FrozenBoundaryLookup
    from voi_boundary_engine import BoundaryPoint

    output = ROOT / "research_outputs_boundary" / f"B2_{arguments.split.upper()}_PLANT_A"
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "EPISODES.csv"
    existing = pd.read_csv(summary_path) if summary_path.exists() else pd.DataFrame()
    completed = set(existing.scenario_id.astype(str)) if not existing.empty else set()
    rows = manifest(arguments.split)
    pd.DataFrame(rows).to_csv(output / "MANIFEST.csv", index=False)
    lookup = FrozenBoundaryLookup(
        ROOT / "research_outputs_boundary/B1_FINAL_MAP/BOUNDARY_MAP.csv",
        ROOT / "research_outputs_boundary/B1_ADAPTIVE_MAP",
        neighbors=5,
    )
    if lookup.has_positive_region:
        raise RuntimeError("frozen development map unexpectedly contains a positive region")
    all_results = existing.to_dict("records") if not existing.empty else []
    for row in rows:
        if str(row["scenario_id"]) in completed:
            continue
        point = BoundaryPoint(
            point_id=str(row["scenario_id"]), period_s=float(row["period_s"]),
            sg_tension=str(row["sg_tension"]), load_magnitude_pu=float(row["load_magnitude_pu"]),
            power_spread_pu=0.035, ramp_spread_pu_per_s=0.035,
            delay_spread_s=1.3, noise_std_pu=float(row["poi_noise_std_pu"]),
            soc=float(row["initial_soc"]), tie_loading_pu=0.0,
            objective=str(row["objective"]),
        )
        selected = simulate_plant_a(
            row, "selective_voi_accr_mpc", point, lookup=lookup, dt_s=0.02,
        )
        selected["paired_execution"] = "SHARED_IDENTICAL_NO_PROBE_TRAJECTORY"
        selected["contract_action_max_abs_difference_pu"] = 0.0
        # In the globally empty frozen region, scheduler.overlay returns the
        # exact contract action object.  A single physical trajectory is thus
        # the paired contract/selective trajectory, not an imputed surrogate.
        contract = dict(selected)
        contract["method"] = "contract_mpc"
        contract["paired_execution"] = "SHARED_IDENTICAL_NO_PROBE_TRAJECTORY"
        all_results.extend((selected, contract))
        pd.DataFrame(all_results).to_csv(summary_path, index=False)
        print(json.dumps({
            "scenario_id": row["scenario_id"],
            "physical_success": selected["physical_success"],
            "frequency_peak_hz": selected["frequency_peak_hz"],
            "probe_triggers": selected["probe_triggers"],
            "solver_failures": selected["solver_failure_calls"],
            "fallbacks": selected["fallback_calls"],
        }, sort_keys=True), flush=True)


def guarded(arguments: argparse.Namespace) -> None:
    output = ROOT / "research_outputs_boundary" / f"B2_{arguments.split.upper()}_PLANT_A"
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(Path(__file__).resolve()), "--worker", "--split", arguments.split,
    ]
    environment = dict(os.environ)
    environment.update(
        DIRECTION5_RESOURCE_GUARDED="1", OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
    )
    limits = ResourceLimits(
        max_system_commit_fraction=0.92, max_system_commit_growth_bytes=6 * GIB,
        min_available_physical_bytes=8 * GIB, max_tree_private_bytes=3 * GIB,
        max_descendant_processes=2, timeout_s=43_200.0, poll_interval_s=0.5,
        preflight_max_system_commit_fraction=0.80,
    )
    wait_for_memory_preflight(
        limits, log_path=output / "preflight.jsonl", timeout_s=3600.0, poll_interval_s=5.0,
    )
    code = run_guarded(
        command, cwd=ROOT, environment=environment, limits=limits,
        monitor_log=output / "memory.jsonl", summary_path=output / "resource.json",
    )
    if code:
        raise SystemExit(code)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--worker", action="store_true")
    result.add_argument("--split", choices=("validation_1", "validation_2"), required=True)
    return result


if __name__ == "__main__":
    args = parser().parse_args()
    worker(args) if args.worker else guarded(args)
