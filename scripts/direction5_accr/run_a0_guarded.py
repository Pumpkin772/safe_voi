"""Only supported launcher for the Direction5 ACCR A0 workload."""

from __future__ import annotations

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
    returncode = run_guarded(
        [
            sys.executable,
            str(REPO / "scripts/direction5_accr/run_a0_platform.py"),
            "--workers", "1",
        ],
        cwd=REPO,
        environment=environment,
        limits=limits,
        monitor_log=log_directory / "MEMORY_MONITOR.jsonl",
        summary_path=log_directory / "MEMORY_MONITOR_SUMMARY.json",
    )
    print(json.dumps({"guarded_returncode": returncode}, indent=2))
    raise SystemExit(returncode)


if __name__ == "__main__":
    main()
