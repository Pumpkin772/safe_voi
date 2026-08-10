"""Fail-closed process and memory guarded launcher for Direction5 M2."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import argparse

import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.resource_guard import (
    GIB,
    ResourceLimits,
    run_guarded,
    wait_for_memory_preflight,
)


def main(
    *, fairness_smoke: bool = False,
    development_r1: bool = False,
    development_r2: bool = False,
    oracle_horizon_screen: bool = False,
) -> None:
    lock = yaml.safe_load(
        (REPO / "configs/direction5_voi_accr/m2_validation_lock.yaml").read_text("utf-8")
    )
    values = lock["resource_guard"]
    limits = ResourceLimits(
        float(values["max_system_commit_fraction"]),
        int(float(values["max_system_commit_growth_gib"]) * GIB),
        int(float(values["min_available_physical_gib"]) * GIB),
        int(float(values["max_process_tree_private_gib"]) * GIB),
        int(values["max_descendant_processes"]),
        float(values["poll_interval_s"]),
        float(values["timeout_s"]),
        preflight_max_system_commit_fraction=float(
            values["preflight_max_system_commit_fraction"]
        ),
    )
    environment = os.environ.copy()
    environment.update({
        "DIRECTION5_RESOURCE_GUARDED": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "DIRECTION5_ANDES_AUTOGEN": "FORBIDDEN",
    })
    log_root = REPO / "logs_direction5_voi_accr/M2"
    wait_for_memory_preflight(
        limits,
        log_path=log_root / "PRELAUNCH_MEMORY_WAIT.jsonl",
    )
    if fairness_smoke:
        target = REPO / "scripts/direction5_voi_accr/run_m2_fairness_smoke.py"
        label = "M2_FAIRNESS_SMOKE"
    elif development_r1:
        target = REPO / "scripts/direction5_voi_accr/run_m1_r1_development.py"
        label = "M1_R1_DEVELOPMENT"
    elif development_r2:
        target = REPO / "scripts/direction5_voi_accr/run_m1_r2_development.py"
        label = "M1_R2_DEVELOPMENT"
    elif oracle_horizon_screen:
        target = REPO / "scripts/direction5_voi_accr/run_oracle_horizon_screen.py"
        label = "ORACLE_HORIZON_SCREEN"
    else:
        target = REPO / "scripts/direction5_voi_accr/run_m2_validation.py"
        label = "M2"
    code = run_guarded(
        [sys.executable, str(target)],
        cwd=REPO,
        environment=environment,
        limits=limits,
        monitor_log=log_root / f"{label}_MEMORY_MONITOR.jsonl",
        summary_path=log_root / f"{label}_MEMORY_MONITOR_SUMMARY.json",
    )
    raise SystemExit(code)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fairness-smoke", action="store_true")
    parser.add_argument("--development-r1", action="store_true")
    parser.add_argument("--development-r2", action="store_true")
    parser.add_argument("--oracle-horizon-screen", action="store_true")
    arguments = parser.parse_args()
    main(
        fairness_smoke=arguments.fairness_smoke,
        development_r1=arguments.development_r1,
        development_r2=arguments.development_r2,
        oracle_horizon_screen=arguments.oracle_horizon_screen,
    )
