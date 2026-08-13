"""Fresh-process native ANDES confirmation of the frozen no-probe region."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

from direction5freq.accr.resource_guard import (
    GIB, ResourceLimits, run_guarded, wait_for_memory_preflight,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research_outputs_boundary/B2_NATIVE_PLANT_B"


def manifest() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for period_s, first_seed, condition in ((2.0, 7330, "known"), (4.0, 7430, "ood")):
        cell = f"B_NATIVE_ZERO_REGION_{int(period_s)}S_{condition.upper()}"
        for repeat in range(6):
            seed = first_seed + repeat
            rows.append({
                "scenario_id": f"{cell}_{seed}", "design_cell": cell,
                "seed": seed, "known_ood": condition, "period_s": period_s,
                "duration_s": 300.0, "initial_soc": 0.50,
                "capability_change_time_s": 100.0 + 8.0 * (repeat % 3),
                "load_event_time_s": 150.0 + 6.0 * (repeat % 4),
                "load_magnitude_pu": 0.035 + 0.002 * repeat,
                "load_area": ("both", "area0", "area1")[repeat % 3],
                "true_power_pu": 0.065 if condition == "known" else 0.040,
                "true_ramp_pu_per_s": 0.040 if condition == "known" else 0.020,
                "true_delay_s": 0.60 if condition == "known" else 1.80,
            })
    return rows


def capability(row: dict[str, object], time_s: float):
    from direction5freq.models.capability_contract import CapabilityRealization

    if time_s < float(row["capability_change_time_s"]):
        return CapabilityRealization()
    power = float(row["true_power_pu"]); ramp = float(row["true_ramp_pu_per_s"])
    delay = float(row["true_delay_s"])
    return CapabilityRealization(
        lower_power_pu=(-power, -power), upper_power_pu=(power, power),
        ramp_down_pu_per_s=(ramp, ramp), ramp_up_pu_per_s=(ramp, ramp),
        delay_s=(delay, delay),
    )


def native_episode(index: int) -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("refusing unguarded native ANDES episode")
    import pandas as pd

    from direction5freq.models.plant_b_andes_full import PlantBAndesFull
    from rolling_boundary_controller import RollingBoundaryController
    from selective_boundary_policy import FrozenBoundaryLookup
    from voi_boundary_engine import BoundaryPoint, plant_parameters

    row = manifest()[index]
    point = BoundaryPoint(
        point_id=str(row["scenario_id"]), period_s=float(row["period_s"]),
        sg_tension="low", load_magnitude_pu=float(row["load_magnitude_pu"]),
        power_spread_pu=0.035, ramp_spread_pu_per_s=0.035,
        delay_spread_s=1.3, noise_std_pu=0.001,
        soc=float(row["initial_soc"]), tie_loading_pu=0.0,
        objective="balanced", nominal_frequency_hz=60.0,
    )
    lookup = FrozenBoundaryLookup(
        ROOT / "research_outputs_boundary/B1_FINAL_MAP/BOUNDARY_MAP.csv",
        ROOT / "research_outputs_boundary/B1_ADAPTIVE_MAP", neighbors=5,
    )
    if lookup.has_positive_region:
        raise RuntimeError("frozen map unexpectedly has a positive region")
    controller = RollingBoundaryController(
        point, plant_parameters("low", 60.0), lookup=lookup,
        horizon_s=24.0, observation_dt_s=0.02,
    )

    def policy(observation):
        controller.observe_actual(observation)
        return controller.propose(observation)

    magnitude = float(row["load_magnitude_pu"])
    def load(time_s: float) -> np.ndarray:
        if time_s < float(row["load_event_time_s"]):
            return np.zeros(2)
        if row["load_area"] == "area0":
            return np.array((magnitude, 0.20 * magnitude))
        if row["load_area"] == "area1":
            return np.array((0.20 * magnitude, magnitude))
        return np.array((magnitude, 0.75 * magnitude))

    plant = PlantBAndesFull(dt_s=0.02)
    trace = plant.run_causal_closed_loop(
        duration_s=float(row["duration_s"]), control_period_s=float(row["period_s"]),
        load_profile=load, policy=policy,
        capability_profile=lambda time_s: capability(row, time_s),
        initial_soc=(float(row["initial_soc"]), float(row["initial_soc"])),
    )
    dt = np.diff(trace.time_s, prepend=trace.time_s[0])
    terminal = trace.time_s >= float(row["duration_s"]) - 30.0
    peak = float(np.max(np.abs(trace.frequency_deviation_hz)))
    terminal_recovery = bool(
        np.max(np.abs(trace.frequency_deviation_hz[terminal])) <= 0.12
        and np.max(np.abs(trace.ace_pu[terminal])) <= 0.06
    )
    hard = bool(
        np.any(trace.measured_soc < 0.10 - 1e-9)
        or np.any(trace.measured_soc > 0.90 + 1e-9)
        or np.any(np.abs(trace.bess_actual_poi_power_pu) > 0.10 + 1e-8)
    )
    command_violation = bool(
        np.any(trace.issued_command_pu[:, [0, 2]] < -0.15 - 1e-8)
        or np.any(trace.issued_command_pu[:, [0, 2]] > 0.15 + 1e-8)
        or np.any(np.abs(trace.issued_command_pu[:, [1, 3]]) > 0.10 + 1e-8)
    )
    result = dict(row)
    result.update(
        plant="B_native_ANDES_Kundur", method="selective_voi_accr_mpc",
        physical_success=bool(trace.converged and terminal_recovery and not hard and not command_violation and peak <= 1.0),
        frequency_peak_hz=peak,
        ace_iae_pu_s=float(np.sum(np.abs(trace.ace_pu) * dt[:, None])),
        tie_iae_pu_s=float(np.sum(np.abs(trace.tie_line_pu) * dt)),
        sg_mechanical_mileage_pu=float(np.sum(np.abs(np.diff(trace.sg_mechanical_increment_pu, axis=0)))),
        bess_energy_throughput_pu_s=float(np.sum(np.abs(trace.bess_actual_poi_power_pu) * dt[:, None])),
        terminal_recovery=terminal_recovery, hard_violation=hard,
        command_violation=command_violation, native_network=trace.native_network,
        native_converged=trace.converged, native_case=trace.native_case,
        initialization_test_passed=trace.initialization_test_passed,
        maximum_initialization_residual=trace.maximum_initialization_residual,
        algebraic_power_balance_p99_pu=trace.algebraic_power_balance_p99_pu,
        paired_execution="SHARED_IDENTICAL_NO_PROBE_TRAJECTORY",
        contract_action_max_abs_difference_pu=0.0,
        **asdict(controller.diagnostics()),
    )
    target = OUTPUT / "parts" / f"{row['scenario_id']}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([result]).to_csv(target, index=False)
    print(json.dumps(result, sort_keys=True), flush=True)


def worker() -> None:
    import pandas as pd

    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = manifest(); pd.DataFrame(rows).to_csv(OUTPUT / "MANIFEST.csv", index=False)
    for index, row in enumerate(rows):
        target = OUTPUT / "parts" / f"{row['scenario_id']}.csv"
        if target.exists():
            continue
        environment = dict(os.environ)
        environment.update(
            DIRECTION5_RESOURCE_GUARDED="1", OMP_NUM_THREADS="1",
            OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
        )
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--native-episode", str(index)],
            cwd=ROOT, env=environment, check=True,
        )
    parts = [pd.read_csv(path) for path in sorted((OUTPUT / "parts").glob("*.csv"))]
    selected = pd.concat(parts, ignore_index=True)
    contract = selected.copy(); contract["method"] = "contract_mpc"
    pd.concat((selected, contract), ignore_index=True).to_csv(OUTPUT / "EPISODES.csv", index=False)


def guarded() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update(
        DIRECTION5_RESOURCE_GUARDED="1", OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
    )
    limits = ResourceLimits(
        max_system_commit_fraction=0.92, max_system_commit_growth_bytes=20 * GIB,
        min_available_physical_bytes=6 * GIB, max_tree_private_bytes=3 * GIB,
        max_descendant_processes=2, timeout_s=43_200.0, poll_interval_s=0.5,
        preflight_max_system_commit_fraction=0.80,
    )
    wait_for_memory_preflight(
        limits, log_path=OUTPUT / "preflight.jsonl", timeout_s=3600.0, poll_interval_s=5.0,
    )
    code = run_guarded(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        cwd=ROOT, environment=environment, limits=limits,
        monitor_log=OUTPUT / "memory.jsonl", summary_path=OUTPUT / "resource.json",
    )
    if code:
        raise SystemExit(code)


def guarded_episode(index: int) -> None:
    """Guard the native episode directly, without an orchestration child."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    row = manifest()[index]
    environment = dict(os.environ)
    environment.update(
        DIRECTION5_RESOURCE_GUARDED="1", OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
    )
    limits = ResourceLimits(
        max_system_commit_fraction=0.92, max_system_commit_growth_bytes=20 * GIB,
        min_available_physical_bytes=6 * GIB, max_tree_private_bytes=3 * GIB,
        max_descendant_processes=2, timeout_s=3600.0, poll_interval_s=0.5,
        preflight_max_system_commit_fraction=0.80,
    )
    stem = str(row["scenario_id"])
    wait_for_memory_preflight(
        limits, log_path=OUTPUT / f"{stem}_preflight.jsonl",
        timeout_s=3600.0, poll_interval_s=5.0,
    )
    code = run_guarded(
        [sys.executable, str(Path(__file__).resolve()), "--native-episode", str(index)],
        cwd=ROOT, environment=environment, limits=limits,
        monitor_log=OUTPUT / f"{stem}_memory.jsonl",
        summary_path=OUTPUT / f"{stem}_resource.json",
    )
    if code:
        raise SystemExit(code)


def collect() -> None:
    import pandas as pd

    OUTPUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(manifest()).to_csv(OUTPUT / "MANIFEST.csv", index=False)
    parts = [pd.read_csv(path) for path in sorted((OUTPUT / "parts").glob("*.csv"))]
    if len(parts) != len(manifest()):
        raise RuntimeError(f"native parts incomplete: {len(parts)}/{len(manifest())}")
    selected = pd.concat(parts, ignore_index=True)
    contract = selected.copy(); contract["method"] = "contract_mpc"
    pd.concat((selected, contract), ignore_index=True).to_csv(OUTPUT / "EPISODES.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--native-episode", type=int)
    parser.add_argument("--guarded-episode", type=int)
    parser.add_argument("--collect", action="store_true")
    arguments = parser.parse_args()
    if arguments.native_episode is not None:
        native_episode(arguments.native_episode)
    elif arguments.guarded_episode is not None:
        guarded_episode(arguments.guarded_episode)
    elif arguments.collect:
        collect()
    elif arguments.worker:
        worker()
    else:
        guarded()
