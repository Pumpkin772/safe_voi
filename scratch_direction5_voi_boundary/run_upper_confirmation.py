"""Confirm every nonzero-VPI design point against all safe-probe upper values."""

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


def _write(rows: list[dict[str, object]], path: Path) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def worker(arguments: argparse.Namespace) -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("refusing unguarded upper confirmation")
    import pandas as pd

    from voi_boundary_engine import BoundaryPoint, evaluate_boundary_point, probe_library

    map_path = ROOT / "research_outputs_boundary" / arguments.map_subdir / "BOUNDARY_MAP.csv"
    output = ROOT / "research_outputs_boundary" / arguments.output_subdir
    output.mkdir(parents=True, exist_ok=True)
    source = pd.read_csv(map_path)
    selected = source.loc[
        source.solver_failures.eq(0)
        & source.perfect_information_value.gt(arguments.vpi_threshold)
    ].sort_values("perfect_information_value", ascending=False)
    summary_path = output / "UPPER_CONFIRMATION.csv"
    existing: dict[str, dict[str, object]] = {}
    if summary_path.exists():
        with summary_path.open("r", newline="", encoding="utf-8") as stream:
            existing = {row["point_id"]: row for row in csv.DictReader(stream)}
    for row in selected.itertuples(index=False):
        if row.point_id in existing:
            continue
        point = BoundaryPoint(
            point_id=str(row.point_id), period_s=float(row.period_s),
            sg_tension=str(row.sg_tension), load_magnitude_pu=float(row.load_magnitude_pu),
            power_spread_pu=float(row.power_spread_pu),
            ramp_spread_pu_per_s=float(row.ramp_spread_pu_per_s),
            delay_spread_s=float(row.delay_spread_s), noise_std_pu=float(row.noise_std_pu),
            soc=float(row.soc), tie_loading_pu=float(row.tie_loading_pu),
            objective=str(row.objective),
        )
        result = evaluate_boundary_point(
            point, physical_horizon_s=arguments.horizon,
            exact_probe_limit=None,
            upper_only=not bool(arguments.strong_convexity_upper_only),
            strong_convexity_upper_only=bool(arguments.strong_convexity_upper_only),
        )
        registered = {item.probe_id: item for item in probe_library(point)}
        detail = result.summary(); detail["candidate_models"] = [asdict(item) for item in result.candidate_models]
        detail["probes"] = []
        for value in result.probes:
            payload = asdict(value); definition = registered[value.probe_id]
            payload.update(
                area=definition.area, sequence_pu=list(definition.sequence_pu),
                physical_duration_s=definition.duration_s,
                amplitude_pu=definition.amplitude_pu, shape=definition.shape,
            )
            detail["probes"].append(payload)
        (output / f"{point.point_id}.json").write_text(
            json.dumps(detail, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        existing[point.point_id] = result.summary()
        ordered = [existing[key] for key in sorted(existing)]
        _write(ordered, summary_path)
        PROGRESS.write_text(json.dumps({
            "project": "DIRECTION5", "goal": "VOI_BOUNDARY_FINAL",
            "status": "B1_ALL_PROBE_UPPER_CONFIRMATION_IN_PROGRESS",
            "points_requiring_confirmation": int(len(selected)),
            "points_confirmed": len(existing),
            "proved_zero": sum(item["region"] == "ZERO_VALUE_PROVED" for item in ordered),
            "positive_upper_remaining": sum(
                float(item["maximum_safe_probe_upper_value"]) > 1e-8 for item in ordered
            ),
            "last_point": point.point_id,
        }, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result.summary(), sort_keys=True), flush=True)


def guarded(arguments: argparse.Namespace) -> None:
    output = ROOT / "research_outputs_boundary" / arguments.output_subdir
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(Path(__file__).resolve()), "--worker",
        "--horizon", str(arguments.horizon),
        "--vpi-threshold", str(arguments.vpi_threshold),
        "--map-subdir", arguments.map_subdir,
        "--output-subdir", arguments.output_subdir,
        "--strong-convexity-upper-only", str(arguments.strong_convexity_upper_only),
    ]
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
        timeout_s=43_200.0,
        poll_interval_s=0.5,
        preflight_max_system_commit_fraction=0.80,
    )
    wait_for_memory_preflight(
        limits, log_path=output / "preflight.jsonl",
        timeout_s=3600.0, poll_interval_s=5.0,
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
    result.add_argument("--horizon", type=float, default=24.0)
    result.add_argument("--vpi-threshold", type=float, default=1e-8)
    result.add_argument("--map-subdir", default="B1_TIGHT_MAP")
    result.add_argument("--output-subdir", default="B1_UPPER_CONFIRMATION")
    result.add_argument("--strong-convexity-upper-only", type=int, choices=(0, 1), default=0)
    return result


if __name__ == "__main__":
    args = parser().parse_args()
    worker(args) if args.worker else guarded(args)
