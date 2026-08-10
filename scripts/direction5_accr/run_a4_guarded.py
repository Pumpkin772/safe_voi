"""Memory-guarded launcher for the A4 focused method run."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
from direction5freq.accr.resource_guard import GIB, ResourceLimits, run_guarded


def main() -> None:
    values = yaml.safe_load((REPO / "configs/direction5_accr/a4_method_lock.yaml").read_text("utf-8"))["resource_guard"]
    limits = ResourceLimits(
        float(values["max_system_commit_fraction"]), int(float(values["max_system_commit_growth_gib"]) * GIB),
        int(float(values["min_available_physical_gib"]) * GIB), int(float(values["max_process_tree_private_gib"]) * GIB),
        int(values["max_descendant_processes"]), float(values["poll_interval_s"]), float(values["timeout_s"]),
    )
    environment = os.environ.copy()
    environment.update({"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    code = run_guarded(
        [sys.executable, str(REPO / "scripts/direction5_accr/run_a4_method.py")],
        cwd=REPO, environment=environment, limits=limits,
        monitor_log=REPO / "logs_accr/A4/MEMORY_MONITOR.jsonl",
        summary_path=REPO / "logs_accr/A4/MEMORY_MONITOR_SUMMARY.json",
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
