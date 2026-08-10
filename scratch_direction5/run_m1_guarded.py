"""Fail-closed memory/process guard for the M1 development search."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.resource_guard import GIB, ResourceLimits, run_guarded


def main() -> None:
    output = REPO / "research_outputs_working/M1"
    output.mkdir(parents=True, exist_ok=True)
    limits = ResourceLimits(
        max_system_commit_fraction=0.70,
        max_system_commit_growth_bytes=int(10 * GIB),
        min_available_physical_bytes=int(8 * GIB),
        max_tree_private_bytes=int(4 * GIB),
        # Registered A3 Windows allowance: conhost plus at most one short-lived
        # numerical-runtime helper. This remains far below the historical 18.
        max_descendant_processes=2,
        poll_interval_s=0.10,
        timeout_s=4 * 3600.0,
        preflight_max_system_commit_fraction=0.64,
    )
    environment = os.environ.copy()
    environment.update({
        "DIRECTION5_RESOURCE_GUARDED": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    })
    arguments = list(sys.argv[1:])
    target = REPO / "scratch_direction5/run_m1_search.py"
    if arguments[:2] == ["--target", "weight-screen"]:
        target = REPO / "scratch_direction5/run_weight_screen.py"
        arguments = arguments[2:]
    returncode = run_guarded(
        [
            sys.executable,
            str(target),
            *arguments,
        ],
        cwd=REPO,
        environment=environment,
        limits=limits,
        monitor_log=output / "M1_MEMORY_MONITOR.jsonl",
        summary_path=output / "M1_MEMORY_MONITOR_SUMMARY.json",
    )
    print(json.dumps({"guarded_returncode": returncode}, indent=2), flush=True)
    raise SystemExit(returncode)


if __name__ == "__main__":
    main()
