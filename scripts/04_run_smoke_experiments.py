"""Run the Phase-6 smoke matrix or the frozen validation-only tuning matrix."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path

from d5freq.evaluation.phase6_experiments import (
    Phase6Paths,
    resolve_repo_or_cwd_path,
    run_phase6_stage,
    utc_timestamp,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run resumable Phase-6 smoke/debug episodes, or the complete "
            "21-scenario x 10-seed tuning qualification for the one frozen P candidate."
        )
    )
    parser.add_argument("--stage", choices=("smoke", "tuning"), default="smoke")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiments.yaml"),
        help="experiments YAML, resolved relative to repo root then current directory",
    )
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="episode processes; each final-grade solver is constrained to one thread",
    )
    parser.add_argument(
        "--solver-tier",
        choices=("DEBUG", "FINAL"),
        default=None,
        help="defaults to DEBUG for smoke and FINAL for tuning",
    )
    parser.add_argument(
        "--method",
        action="append",
        dest="methods",
        help="repeatable smoke-only method filter",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        help="repeatable smoke-only scenario filter",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=None,
        help="smoke/debug-only deterministic prefix limit",
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    paths = Phase6Paths.from_repo(
        arguments.repo_root,
        output_root=arguments.output_root,
    )
    paths = replace(
        paths,
        experiments_config=resolve_repo_or_cwd_path(
            arguments.config, paths.repo_root
        ),
    )
    result = run_phase6_stage(
        paths,
        stage=arguments.stage,
        workers=arguments.workers,
        solver_tier=arguments.solver_tier,
        method_ids=arguments.methods,
        scenario_ids=arguments.scenarios,
        max_runs=arguments.max_runs,
    )
    print(
        json.dumps(
            {
                "completed_at_utc": utc_timestamp(),
                "stage": result.stage,
                "planned_run_count": result.planned_run_count,
                "executed_or_resumed_count": result.executed_or_resumed_count,
                "per_episode_metrics": str(result.per_episode_metrics_path),
                "experiment_ledger": str(result.experiment_ledger_path),
                "protocol_snapshot": str(result.protocol_snapshot_path),
                "tuning_selection_record": (
                    None
                    if result.tuning_selection_record_path is None
                    else str(result.tuning_selection_record_path)
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
