"""Wait for the registered memory buffer, then launch one guarded task."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.resource_guard import (
    GIB,
    ResourceLimits,
    wait_for_memory_preflight,
)


def main() -> None:
    limits = ResourceLimits(
        max_system_commit_fraction=0.70,
        max_system_commit_growth_bytes=int(10 * GIB),
        min_available_physical_bytes=int(8 * GIB),
        max_tree_private_bytes=int(4 * GIB),
        max_descendant_processes=2,
        poll_interval_s=0.10,
        timeout_s=4 * 3600.0,
        preflight_max_system_commit_fraction=0.64,
    )
    output = REPO / "research_outputs_working/M1"
    wait_for_memory_preflight(
        limits,
        log_path=output / "M1_CAPACITY_WAIT.jsonl",
        timeout_s=4 * 3600.0,
        poll_interval_s=5.0,
    )
    command = [
        sys.executable,
        str(REPO / "scratch_direction5/run_m1_guarded.py"),
        *sys.argv[1:],
    ]
    completed = subprocess.run(
        command,
        cwd=REPO,
        env=os.environ.copy(),
        check=False,
    )
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
