"""Guarded single Plant-A episode for timing and physical pilot checks."""

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
OUTPUT = ROOT / "research_outputs_boundary" / "B2_NONLINEAR_PILOT"


def worker(arguments: argparse.Namespace) -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("refusing unguarded nonlinear pilot")
    from nonlinear_boundary_validation import simulate_plant_a
    from voi_boundary_engine import BoundaryPoint

    point = BoundaryPoint(
        point_id="B2_PILOT_POINT", period_s=arguments.period,
        sg_tension=arguments.sg_tension, load_magnitude_pu=arguments.load,
        power_spread_pu=arguments.power_spread,
        ramp_spread_pu_per_s=arguments.ramp_spread,
        delay_spread_s=arguments.delay_spread,
        noise_std_pu=arguments.poi_noise,
        soc=arguments.soc, tie_loading_pu=arguments.tie,
        objective=arguments.objective,
    )
    row = {
        "scenario_id": arguments.scenario_id,
        "design_cell": f"A|{arguments.period:g}|{arguments.sg_tension}|{arguments.objective}",
        "known_ood": arguments.condition,
        "seed": arguments.seed,
        "duration_s": arguments.duration,
        "initial_soc": arguments.soc,
        "capability_change_time_s": 60.0,
        "load_event_time_s": 80.0,
        "load_magnitude_pu": arguments.load,
        "load_sign": 1.0,
        "load_area": "both",
        "true_power_pu": min(0.080, 0.045 + arguments.power_spread),
        "true_ramp_pu_per_s": min(0.060, 0.025 + arguments.ramp_spread),
        "true_delay_s": max(0.20, 1.50 - arguments.delay_spread),
        "frequency_noise_std_hz": arguments.frequency_noise,
        "poi_noise_std_pu": arguments.poi_noise,
    }
    result = simulate_plant_a(row, arguments.method, point, dt_s=arguments.dt)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / f"{arguments.scenario_id}__{arguments.method}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def guarded(arguments: argparse.Namespace) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker"]
    for option in (
        "scenario_id", "method", "seed", "duration", "dt", "period", "sg_tension",
        "load", "power_spread", "ramp_spread", "delay_spread", "frequency_noise",
        "poi_noise", "soc", "tie", "objective", "condition",
    ):
        command.extend(("--" + option.replace("_", "-"), str(getattr(arguments, option))))
    environment = dict(os.environ)
    environment.update(
        DIRECTION5_RESOURCE_GUARDED="1", OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
    )
    limits = ResourceLimits(
        max_system_commit_fraction=0.92, max_system_commit_growth_bytes=6 * GIB,
        min_available_physical_bytes=8 * GIB, max_tree_private_bytes=3 * GIB,
        max_descendant_processes=2, timeout_s=7200.0, poll_interval_s=0.5,
        preflight_max_system_commit_fraction=0.80,
    )
    wait_for_memory_preflight(
        limits, log_path=OUTPUT / f"{arguments.scenario_id}_preflight.jsonl",
        timeout_s=3600.0, poll_interval_s=5.0,
    )
    code = run_guarded(
        command, cwd=ROOT, environment=environment, limits=limits,
        monitor_log=OUTPUT / f"{arguments.scenario_id}_memory.jsonl",
        summary_path=OUTPUT / f"{arguments.scenario_id}_resource.json",
    )
    if code:
        raise SystemExit(code)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--worker", action="store_true")
    result.add_argument("--scenario-id", default="B2_PILOT_001")
    result.add_argument("--method", choices=("contract_mpc", "perfect_capability_oracle"), default="contract_mpc")
    result.add_argument("--seed", type=int, default=7100)
    result.add_argument("--duration", type=float, default=120.0)
    result.add_argument("--dt", type=float, default=0.02)
    result.add_argument("--period", type=float, default=4.0)
    result.add_argument("--sg-tension", choices=("low", "medium", "high"), default="medium")
    result.add_argument("--load", type=float, default=0.070)
    result.add_argument("--power-spread", type=float, default=0.030)
    result.add_argument("--ramp-spread", type=float, default=0.020)
    result.add_argument("--delay-spread", type=float, default=0.8)
    result.add_argument("--frequency-noise", type=float, default=0.001)
    result.add_argument("--poi-noise", type=float, default=0.001)
    result.add_argument("--soc", type=float, default=0.5)
    result.add_argument("--tie", type=float, default=0.02)
    result.add_argument("--objective", default="resource_economy")
    result.add_argument("--condition", choices=("known", "ood"), default="known")
    return result


if __name__ == "__main__":
    args = parser().parse_args()
    worker(args) if args.worker else guarded(args)
