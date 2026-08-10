"""Memory-guarded single-process launcher for A1."""

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
    lock = yaml.safe_load((REPO / "configs/direction5_accr/a1_materiality_lock.yaml").read_text("utf-8"))
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
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    })
    log_directory = REPO / "logs_accr/A1"
    log_directory.mkdir(parents=True, exist_ok=True)
    existing = list(log_directory.glob("MEMORY_MONITOR*.jsonl"))
    attempt = len(existing) + 1
    monitor_name = f"MEMORY_MONITOR_ATTEMPT_{attempt:02d}"
    returncode = run_guarded(
        [sys.executable, str(REPO / "scripts/direction5_accr/run_a1_materiality.py")],
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
