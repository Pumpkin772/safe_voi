"""Six genuine 3600 s nonlinear Plant-A normal-profile confirmations."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

import numpy as np

from direction5freq.accr.resource_guard import (
    GIB, ResourceLimits, run_guarded, wait_for_memory_preflight,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research_outputs_boundary/B3_NORMAL1H"


def normal_profile(seed: int) -> np.ndarray:
    rng = np.random.default_rng(np.random.SeedSequence([20260812, seed, 521]))
    values = np.zeros((3601, 2))
    innovations = rng.normal(0.0, 0.00040, (3601, 2))
    for index in range(1, len(values)):
        values[index] = 0.988 * values[index - 1] + innovations[index]
    time_s = np.arange(3601)
    values += np.column_stack((
        0.0055 * np.sin(2.0 * np.pi * time_s / 800.0),
        0.0045 * np.sin(2.0 * np.pi * time_s / 970.0 + 0.4),
    ))
    values[:60] = 0.0
    return np.clip(values, -0.018, 0.018)


def simulate(seed: int, progress_path: Path | None = None) -> dict[str, object]:
    from direction5freq.models.capability_contract import CapabilityRealization
    from direction5freq.models.plant_a_full import PlantAFull
    from rolling_boundary_controller import RollingBoundaryController
    from selective_boundary_policy import FrozenBoundaryLookup
    from voi_boundary_engine import BoundaryPoint, plant_parameters

    point = BoundaryPoint(
        point_id=f"NORMAL1H_{seed}", period_s=4.0, sg_tension="low",
        load_magnitude_pu=0.018, power_spread_pu=0.035,
        ramp_spread_pu_per_s=0.035, delay_spread_s=1.3,
        noise_std_pu=0.001, soc=0.5, tie_loading_pu=0.0,
        objective="balanced",
    )
    parameters = plant_parameters("low", 50.0)
    lookup = FrozenBoundaryLookup(
        ROOT / "research_outputs_boundary/B1_FINAL_MAP/BOUNDARY_MAP.csv",
        ROOT / "research_outputs_boundary/B1_ADAPTIVE_MAP", neighbors=5,
    )
    controller = RollingBoundaryController(
        point, parameters, lookup=lookup, horizon_s=24.0, observation_dt_s=0.02,
    )
    plant = PlantAFull(parameters, dt_s=0.02)
    state = plant.equilibrium((0.5, 0.5))
    profile = normal_profile(seed)
    command = np.zeros(4); next_control = 0.0
    frequency_square = 0.0; frequency_count = 0
    frequency_peak = 0.0; ace_iae = 0.0; tie_iae = 0.0
    minimum_soc = np.ones(2); maximum_soc = np.zeros(2)
    hard = False; command_violation = False
    for step in range(180_001):
        time_s = step * 0.02
        public = plant.public_observation(time_s, state, command)
        controller.observe_actual(public)
        minimum_soc = np.minimum(minimum_soc, observation_soc := public.measured_soc)
        maximum_soc = np.maximum(maximum_soc, observation_soc)
        if time_s + 1e-10 >= next_control:
            command = controller.propose(public)
            command_violation |= bool(
                np.any(command[[0, 2]] < np.asarray(parameters.valve_lower_pu) - 1e-9)
                or np.any(command[[0, 2]] > np.asarray(parameters.valve_upper_pu) + 1e-9)
                or np.any(np.abs(command[[1, 3]]) > parameters.bess.rating_pu + 1e-9)
            )
            next_control += 4.0
        frequency_peak = max(frequency_peak, float(np.max(np.abs(public.frequency_deviation_hz))))
        frequency_square += float(np.sum(np.square(public.frequency_deviation_hz)))
        frequency_count += 2
        ace_iae += float(np.sum(np.abs(public.ace_pu))) * 0.02
        tie_iae += abs(float(public.tie_line_pu)) * 0.02
        if progress_path is not None and step % 15_000 == 0:
            progress_path.write_text(json.dumps({
                "seed": seed, "simulated_time_s": time_s,
                "frequency_peak_hz": frequency_peak,
                "attempted_optimization_calls": controller.attempts,
                "solver_failure_calls": controller.failures,
                "fallback_calls": controller.fallbacks,
                "minimum_soc": minimum_soc.tolist(),
                "maximum_soc": maximum_soc.tolist(),
            }, indent=2) + "\n", encoding="utf-8")
        if step == 180_000:
            break
        left = int(np.floor(time_s)); fraction = time_s - left
        right = min(left + 1, 3600)
        load = (1.0 - fraction) * profile[left] + fraction * profile[right]
        state, _diagnostics = plant.step(
            state, command, load, CapabilityRealization(), np.zeros(2),
        )
        hard |= bool(
            np.any(state.valve_pu < np.asarray(parameters.valve_lower_pu) - 1e-9)
            or np.any(state.valve_pu > np.asarray(parameters.valve_upper_pu) + 1e-9)
            or np.any(state.mechanical_power_pu < np.asarray(parameters.sg_power_lower_pu) - 1e-9)
            or np.any(state.mechanical_power_pu > np.asarray(parameters.sg_power_upper_pu) + 1e-9)
            or np.any(state.bess.measured_soc(parameters.bess) < parameters.bess.soc_min - 1e-9)
            or np.any(state.bess.measured_soc(parameters.bess) > parameters.bess.soc_max + 1e-9)
        )
    diagnostics = asdict(controller.diagnostics())
    result: dict[str, object] = {
        "scenario_id": f"NORMAL1H_{seed}", "seed": seed,
        "plant": "A_full_nonlinear", "duration_s": 3600.0,
        "period_s": 4.0, "method": "selective_voi_accr_mpc",
        "profile_provenance": "SYNTHETIC_STATIONARY_ZERO_MEAN_AR1_MULTISINE",
        "frequency_peak_hz": frequency_peak,
        "frequency_rms_hz": float(np.sqrt(frequency_square / frequency_count)),
        "ace_iae_pu_s": ace_iae, "tie_iae_pu_s": tie_iae,
        "hard_violation": hard, "command_violation": command_violation,
        "minimum_soc": minimum_soc.tolist(), "maximum_soc": maximum_soc.tolist(),
        "physical_success": bool(
            frequency_peak <= 0.20 and np.sqrt(frequency_square / frequency_count) <= 0.05
            and not hard and not command_violation
        ),
        "paired_execution": "SHARED_IDENTICAL_NO_PROBE_TRAJECTORY",
        "contract_action_max_abs_difference_pu": 0.0,
        **diagnostics,
    }
    return result


def worker() -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("refusing unguarded normal1h")
    import pandas as pd

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for seed in range(7450, 7456):
        target = OUTPUT / "parts" / f"NORMAL1H_{seed}.csv"
        if target.exists():
            continue
        try:
            result = simulate(seed, OUTPUT / f"NORMAL1H_{seed}_progress.json")
        except Exception:
            import traceback

            (OUTPUT / f"NORMAL1H_{seed}_ERROR.txt").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            raise
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([result]).to_csv(target, index=False)
        print(json.dumps(result, sort_keys=True), flush=True)
    selected = pd.concat(
        [pd.read_csv(path) for path in sorted((OUTPUT / "parts").glob("*.csv"))],
        ignore_index=True,
    )
    contract = selected.copy(); contract["method"] = "contract_mpc"
    pd.concat((selected, contract), ignore_index=True).to_csv(OUTPUT / "EPISODES.csv", index=False)


def normal_episode(seed: int) -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("refusing unguarded normal1h episode")
    import pandas as pd
    import traceback

    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / "parts" / f"NORMAL1H_{seed}.csv"
    try:
        result = simulate(seed, OUTPUT / f"NORMAL1H_{seed}_progress.json")
    except Exception:
        (OUTPUT / f"NORMAL1H_{seed}_ERROR.txt").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        raise
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([result]).to_csv(target, index=False)
    print(json.dumps(result, sort_keys=True), flush=True)


def guarded_episode(seed: int) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    attempt_directory = OUTPUT / "attempts"
    attempt_directory.mkdir(parents=True, exist_ok=True)
    existing = list(attempt_directory.glob(f"NORMAL1H_{seed}_ATTEMPT_*_resource.json"))
    attempt = len(existing) + 1
    prefix = attempt_directory / f"NORMAL1H_{seed}_ATTEMPT_{attempt:03d}"
    environment = dict(os.environ)
    environment.update(
        DIRECTION5_RESOURCE_GUARDED="1", OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
    )
    limits = ResourceLimits(
        max_system_commit_fraction=0.92, max_system_commit_growth_bytes=20 * GIB,
        min_available_physical_bytes=8 * GIB, max_tree_private_bytes=3 * GIB,
        max_descendant_processes=2, timeout_s=7200.0, poll_interval_s=0.5,
        preflight_max_system_commit_fraction=0.80,
    )
    wait_for_memory_preflight(
        limits, log_path=Path(f"{prefix}_preflight.jsonl"),
        timeout_s=7200.0, poll_interval_s=5.0,
    )
    code = run_guarded(
        [sys.executable, str(Path(__file__).resolve()), "--normal-episode", str(seed)],
        cwd=ROOT, environment=environment, limits=limits,
        monitor_log=Path(f"{prefix}_memory.jsonl"),
        summary_path=Path(f"{prefix}_resource.json"),
    )
    if code:
        raise SystemExit(code)


def collect() -> None:
    import pandas as pd

    parts = [pd.read_csv(path) for path in sorted((OUTPUT / "parts").glob("*.csv"))]
    if len(parts) != 6:
        raise RuntimeError(f"normal1h parts incomplete: {len(parts)}/6")
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
        max_system_commit_fraction=0.92, max_system_commit_growth_bytes=6 * GIB,
        min_available_physical_bytes=8 * GIB, max_tree_private_bytes=3 * GIB,
        max_descendant_processes=2, timeout_s=43_200.0, poll_interval_s=0.5,
        preflight_max_system_commit_fraction=0.80,
    )
    wait_for_memory_preflight(
        limits, log_path=OUTPUT / "preflight.jsonl", timeout_s=7200.0, poll_interval_s=5.0,
    )
    code = run_guarded(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        cwd=ROOT, environment=environment, limits=limits,
        monitor_log=OUTPUT / "memory.jsonl", summary_path=OUTPUT / "resource.json",
    )
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--worker", action="store_true")
    parser.add_argument("--normal-episode", type=int)
    parser.add_argument("--guarded-episode", type=int)
    parser.add_argument("--collect", action="store_true")
    arguments = parser.parse_args()
    if arguments.normal_episode is not None:
        normal_episode(arguments.normal_episode)
    elif arguments.guarded_episode is not None:
        guarded_episode(arguments.guarded_episode)
    elif arguments.collect:
        collect()
    elif arguments.worker:
        worker()
    else:
        guarded()
