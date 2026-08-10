"""Only supported launcher for the Direction5 ACCR A0 workload."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.resource_guard import GIB, ResourceLimits, run_guarded


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--resume-after-plant-a", action="store_true")
    mode.add_argument("--prepare-andes", action="store_true")
    args = parser.parse_args()
    lock = yaml.safe_load(
        (REPO / "configs/direction5_accr/a0_platform_lock.yaml").read_text("utf-8")
    )
    values = lock["resource_guard"]
    limits = ResourceLimits(
        max_system_commit_fraction=float(values["max_system_commit_fraction"]),
        max_system_commit_growth_bytes=int(float(values["max_system_commit_growth_gib"]) * GIB),
        min_available_physical_bytes=int(float(values["min_available_physical_gib"]) * GIB),
        max_tree_private_bytes=int(float(values["max_process_tree_private_gib"]) * GIB),
        max_descendant_processes=int(values["max_descendant_processes"]),
        poll_interval_s=float(values["poll_interval_s"]),
        timeout_s=float(values["timeout_s"]),
    )
    environment = os.environ.copy()
    environment.update({
        "DIRECTION5_RESOURCE_GUARDED": "1",
        "DIRECTION5_ANDES_AUTOGEN": "FORBIDDEN",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
    })
    log_directory = REPO / "logs_accr/A0"
    if args.prepare_andes:
        command = [
            sys.executable,
            str(REPO / "scripts/direction5_accr/prepare_andes_codegen.py"),
        ]
        # Only the worker and its automatic Windows conhost are allowed.
        limits = replace(limits, max_descendant_processes=1)
        monitor_name = "ANDES_PREP_MEMORY_MONITOR"
    else:
        command = [
            sys.executable,
            str(REPO / "scripts/direction5_accr/run_a0_platform.py"),
            "--workers", "1",
        ]
        if args.resume_after_plant_a:
            command.append("--resume-after-plant-a")
        monitor_name = "MEMORY_MONITOR"
    returncode = run_guarded(
        command,
        cwd=REPO,
        environment=environment,
        limits=limits,
        monitor_log=log_directory / f"{monitor_name}.jsonl",
        summary_path=log_directory / f"{monitor_name}_SUMMARY.json",
    )
    print(json.dumps({"guarded_returncode": returncode}, indent=2))
    raise SystemExit(returncode)


if __name__ == "__main__":
    main()
