"""Guarded one-process runner for Direction5 B1 boundary calculations."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from direction5freq.accr.resource_guard import (
    GIB, ResourceLimits, run_guarded, wait_for_memory_preflight,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research_outputs_boundary" / "B1_DEVELOPMENT"


def worker(arguments: argparse.Namespace) -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("refusing unguarded boundary calculation")
    # Keep scientific libraries out of the lightweight parent guard process.
    # Importing CVXPY/SciPy in both parent and worker materially increases Windows
    # committed memory even though only the worker performs a calculation.
    from voi_boundary_engine import BoundaryPoint, evaluate_boundary_point, probe_library

    point = BoundaryPoint(
        point_id=arguments.point_id,
        period_s=arguments.period,
        sg_tension=arguments.sg_tension,
        load_magnitude_pu=arguments.load,
        power_spread_pu=arguments.power_spread,
        ramp_spread_pu_per_s=arguments.ramp_spread,
        delay_spread_s=arguments.delay_spread,
        noise_std_pu=arguments.noise,
        soc=arguments.soc,
        tie_loading_pu=arguments.tie,
        objective=arguments.objective,
    )
    result = evaluate_boundary_point(
        point,
        physical_horizon_s=arguments.horizon,
        exact_probe_limit=arguments.probe_limit,
        upper_only=arguments.upper_only,
        strong_convexity_upper_only=arguments.strong_convexity_upper_only,
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    payload = result.summary()
    payload["candidate_models"] = [asdict(item) for item in result.candidate_models]
    registered = {item.probe_id: item for item in probe_library(point)}
    payload["probes"] = []
    for value in result.probes:
        probe_payload = asdict(value)
        definition = registered[value.probe_id]
        probe_payload.update(
            area=definition.area,
            sequence_pu=list(definition.sequence_pu),
            physical_duration_s=definition.duration_s,
            amplitude_pu=definition.amplitude_pu,
            shape=definition.shape,
        )
        payload["probes"].append(probe_payload)
    destination = OUTPUT / f"{arguments.point_id}.json"
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result.summary(), indent=2, sort_keys=True))


def guarded(arguments: argparse.Namespace) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker"]
    for option, value in (
        ("--point-id", arguments.point_id), ("--period", arguments.period),
        ("--sg-tension", arguments.sg_tension), ("--load", arguments.load),
        ("--power-spread", arguments.power_spread), ("--ramp-spread", arguments.ramp_spread),
        ("--delay-spread", arguments.delay_spread), ("--noise", arguments.noise),
        ("--soc", arguments.soc), ("--tie", arguments.tie),
        ("--objective", arguments.objective),
        ("--horizon", arguments.horizon), ("--probe-limit", arguments.probe_limit),
        ("--upper-only", int(arguments.upper_only)),
        ("--strong-convexity-upper-only", int(arguments.strong_convexity_upper_only)),
    ):
        command.extend((option, str(value)))
    environment = dict(os.environ)
    environment.update(
        DIRECTION5_RESOURCE_GUARDED="1",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
        VECLIB_MAXIMUM_THREADS="1",
    )
    limits = ResourceLimits(
        max_system_commit_fraction=0.92,
        max_system_commit_growth_bytes=6 * GIB,
        min_available_physical_bytes=8 * GIB,
        max_tree_private_bytes=3 * GIB,
        # The Conda interpreter creates one short-lived launcher child on
        # this Windows installation.  The registered ceiling of two still
        # prevents the earlier multiprocessing fan-out (18 children).
        max_descendant_processes=2,
        timeout_s=1800.0,
        poll_interval_s=0.5,
        preflight_max_system_commit_fraction=0.80,
    )
    wait_for_memory_preflight(
        limits,
        log_path=OUTPUT / f"{arguments.point_id}_preflight.jsonl",
        timeout_s=1800.0,
        poll_interval_s=5.0,
    )
    code = run_guarded(
        command,
        cwd=ROOT,
        environment=environment,
        limits=limits,
        monitor_log=OUTPUT / f"{arguments.point_id}_memory.jsonl",
        summary_path=OUTPUT / f"{arguments.point_id}_resource.json",
    )
    if code:
        raise SystemExit(code)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--worker", action="store_true")
    result.add_argument("--point-id", default="B1_PILOT_001")
    result.add_argument("--period", type=float, default=2.0)
    result.add_argument("--sg-tension", choices=("low", "medium", "high"), default="high")
    result.add_argument("--load", type=float, default=0.060)
    result.add_argument("--power-spread", type=float, default=0.035)
    result.add_argument("--ramp-spread", type=float, default=0.035)
    result.add_argument("--delay-spread", type=float, default=1.3)
    result.add_argument("--noise", type=float, default=0.0005)
    result.add_argument("--soc", type=float, default=0.5)
    result.add_argument("--tie", type=float, default=0.02)
    result.add_argument(
        "--objective",
        choices=("balanced", "regional_responsibility", "resource_economy"),
        default="balanced",
    )
    result.add_argument("--horizon", type=float, default=24.0)
    result.add_argument("--probe-limit", type=int, default=2)
    result.add_argument("--upper-only", type=int, choices=(0, 1), default=0)
    result.add_argument("--strong-convexity-upper-only", type=int, choices=(0, 1), default=0)
    return result


if __name__ == "__main__":
    args = parser().parse_args()
    worker(args) if args.worker else guarded(args)
