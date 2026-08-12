"""Sequential, resumable and memory-guarded B1 boundary map calculation."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from direction5freq.accr.resource_guard import (
    GIB, ResourceLimits, run_guarded, wait_for_memory_preflight,
)


ROOT = Path(__file__).resolve().parents[1]
PROGRESS = ROOT / "progress_boundary.json"


def _manifest(count: int, seed: int, prefix: str):
    import numpy as np
    from scipy.stats import qmc

    from voi_boundary_engine import BoundaryPoint

    sample = qmc.LatinHypercube(d=9, seed=seed).random(n=count)
    periods = (2.0, 4.0)
    tensions = ("low", "medium", "high")
    objectives = ("balanced", "regional_responsibility", "resource_economy")
    points = []
    for index, row in enumerate(sample):
        points.append(BoundaryPoint(
            point_id=f"{prefix}{index:04d}",
            period_s=periods[min(int(row[0] * len(periods)), len(periods) - 1)],
            sg_tension=tensions[min(int(row[1] * len(tensions)), len(tensions) - 1)],
            load_magnitude_pu=float(0.015 + 0.060 * row[2]),
            power_spread_pu=float(0.035 * row[3]),
            ramp_spread_pu_per_s=float(0.035 * row[4]),
            delay_spread_s=float(1.3 * row[5]),
            noise_std_pu=float(0.0005 + 0.0015 * row[6]),
            soc=float(0.30 + 0.40 * row[7]),
            tie_loading_pu=float(0.04 * row[8]),
            objective=objectives[index % len(objectives)],
        ))
    return points


def _write_csv(rows: list[dict[str, object]], path: Path) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def worker(arguments: argparse.Namespace) -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("refusing unguarded boundary map")
    from voi_boundary_engine import evaluate_boundary_point, probe_library

    output = ROOT / "research_outputs_boundary" / arguments.output_subdir
    output.mkdir(parents=True, exist_ok=True)
    if arguments.manifest_path:
        import pandas as pd
        from voi_boundary_engine import BoundaryPoint

        source = pd.read_csv(ROOT / arguments.manifest_path)
        points = [BoundaryPoint(**row) for row in source.to_dict(orient="records")]
    else:
        points = _manifest(arguments.count, arguments.seed, arguments.prefix)
    _write_csv([asdict(point) for point in points], output / "MANIFEST.csv")
    summary_path = output / "BOUNDARY_MAP.csv"
    existing: dict[str, dict[str, object]] = {}
    if summary_path.exists():
        with summary_path.open("r", newline="", encoding="utf-8") as stream:
            existing = {row["point_id"]: row for row in csv.DictReader(stream)}
    for point in points:
        if point.point_id in existing:
            continue
        result = evaluate_boundary_point(
            point,
            physical_horizon_s=arguments.horizon,
            exact_probe_limit=arguments.probe_limit,
            upper_only=bool(arguments.upper_only),
            strong_convexity_upper_only=bool(arguments.strong_convexity_upper_only),
        )
        detail = result.summary()
        detail["candidate_models"] = [asdict(item) for item in result.candidate_models]
        registered = {item.probe_id: item for item in probe_library(point)}
        detail["probes"] = []
        for value in result.probes:
            payload = asdict(value)
            definition = registered[value.probe_id]
            payload.update(
                area=definition.area,
                sequence_pu=list(definition.sequence_pu),
                physical_duration_s=definition.duration_s,
                amplitude_pu=definition.amplitude_pu,
                shape=definition.shape,
            )
            detail["probes"].append(payload)
        (output / f"{point.point_id}.json").write_text(
            json.dumps(detail, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        existing[point.point_id] = result.summary()
        ordered = [existing[key] for key in sorted(existing)]
        _write_csv(ordered, summary_path)
        progress = {
            "project": "DIRECTION5", "goal": "VOI_BOUNDARY_FINAL",
            "status": "B1_MAP_IN_PROGRESS",
            "points_completed": len(existing), "points_registered": len(points),
            "positive_points": sum(row["region"] == "POSITIVE_VALUE" for row in ordered),
            "proved_zero_points": sum(row["region"] == "ZERO_VALUE_PROVED" for row in ordered),
            "solver_failures": sum(int(row["solver_failures"]) for row in ordered),
            "last_point": point.point_id,
        }
        PROGRESS.write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result.summary(), sort_keys=True), flush=True)
    ordered = [existing[key] for key in sorted(existing)]
    PROGRESS.write_text(json.dumps({
        "project": "DIRECTION5", "goal": "VOI_BOUNDARY_FINAL",
        "status": "B1_MAP_COMPLETED",
        "points_completed": len(existing), "points_registered": len(points),
        "positive_points": sum(row["region"] == "POSITIVE_VALUE" for row in ordered),
        "proved_zero_points": sum(row["region"] == "ZERO_VALUE_PROVED" for row in ordered),
        "solver_failures": sum(int(row["solver_failures"]) for row in ordered),
    }, indent=2) + "\n", encoding="utf-8")


def guarded(arguments: argparse.Namespace) -> None:
    output = ROOT / "research_outputs_boundary" / arguments.output_subdir
    output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker"]
    for option, value in (
        ("--count", arguments.count), ("--seed", arguments.seed),
        ("--horizon", arguments.horizon), ("--probe-limit", arguments.probe_limit),
        ("--upper-only", int(arguments.upper_only)),
        ("--strong-convexity-upper-only", int(arguments.strong_convexity_upper_only)),
        ("--output-subdir", arguments.output_subdir), ("--prefix", arguments.prefix),
        ("--manifest-path", arguments.manifest_path),
    ):
        command.extend((option, str(value)))
    environment = dict(os.environ)
    environment.update(
        DIRECTION5_RESOURCE_GUARDED="1", OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
        VECLIB_MAXIMUM_THREADS="1",
    )
    limits = ResourceLimits(
        max_system_commit_fraction=0.92,
        max_system_commit_growth_bytes=6 * GIB,
        min_available_physical_bytes=8 * GIB,
        max_tree_private_bytes=3 * GIB,
        max_descendant_processes=2,
        timeout_s=arguments.timeout,
        poll_interval_s=0.5,
        preflight_max_system_commit_fraction=0.80,
    )
    wait_for_memory_preflight(
        limits,
        log_path=output / "preflight.jsonl",
        timeout_s=min(arguments.timeout, 3600.0),
        poll_interval_s=5.0,
    )
    code = run_guarded(
        command, cwd=ROOT, environment=environment,
        limits=limits,
        monitor_log=output / "memory.jsonl",
        summary_path=output / "resource.json",
    )
    if code:
        raise SystemExit(code)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--worker", action="store_true")
    result.add_argument("--count", type=int, default=512)
    result.add_argument("--seed", type=int, default=7000)
    result.add_argument("--horizon", type=float, default=24.0)
    result.add_argument("--probe-limit", type=int, default=8)
    result.add_argument("--upper-only", type=int, choices=(0, 1), default=0)
    result.add_argument("--strong-convexity-upper-only", type=int, choices=(0, 1), default=0)
    result.add_argument("--output-subdir", default="B1_MAP")
    result.add_argument("--prefix", default="B1_LHS_")
    result.add_argument("--manifest-path", default="")
    result.add_argument("--timeout", type=float, default=43_200.0)
    return result


if __name__ == "__main__":
    args = parser().parse_args()
    worker(args) if args.worker else guarded(args)
