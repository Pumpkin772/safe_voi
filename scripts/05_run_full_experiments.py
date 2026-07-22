"""Run or resume the complete locked 8,280-episode Phase-6 final matrix."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path

from d5freq.evaluation.phase6_analysis import (
    DEFAULT_ANALYSIS_SEED,
    DEFAULT_BOOTSTRAP_RESAMPLES,
    write_phase6_analysis,
)
from d5freq.evaluation.phase6_experiments import (
    Phase6Paths,
    resolve_repo_or_cwd_path,
    run_phase6_stage,
    utc_timestamp,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run/resume the complete frozen Phase-6 final test. Subsetting is "
            "intentionally unavailable; the tuning selection and protocol lock "
            "must exist before the first episode."
        )
    )
    parser.add_argument("--stage", choices=("final",), default="final")
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
        "--analysis-output",
        type=Path,
        default=None,
        help="review CSV directory; defaults to <repo>/results/final",
    )
    parser.add_argument(
        "--analysis-seed",
        type=int,
        default=DEFAULT_ANALYSIS_SEED,
    )
    parser.add_argument(
        "--bootstrap-resamples",
        type=int,
        default=DEFAULT_BOOTSTRAP_RESAMPLES,
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="episode processes; MOSEK/Gurobi are constrained to one thread per episode",
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
        stage="final",
        workers=arguments.workers,
        solver_tier="FINAL",
    )
    analysis_output = (
        paths.repo_root / "results" / "final"
        if arguments.analysis_output is None
        else resolve_repo_or_cwd_path(arguments.analysis_output, paths.repo_root)
    )
    analysis = write_phase6_analysis(
        result.per_episode_metrics_path,
        result.experiment_ledger_path,
        analysis_output,
        require_complete_final=True,
        analysis_seed=arguments.analysis_seed,
        n_resamples=arguments.bootstrap_resamples,
        protocol_lock_path=result.protocol_lock_path,
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
                "protocol_lock": str(result.protocol_lock_path),
                "review_results": {
                    "per_episode_metrics": str(
                        analysis.per_episode_metrics_path
                    ),
                    "summary_metrics": str(analysis.summary_metrics_path),
                    "statistical_tests": str(analysis.statistical_tests_path),
                    "diagnostic_metrics": str(analysis.diagnostic_metrics_path),
                    "solver_metrics": str(analysis.solver_metrics_path),
                    "experiment_ledger": str(analysis.experiment_ledger_path),
                    "oracle_pairing_audit": str(
                        analysis.oracle_pairing_audit_path
                    ),
                    "protocol_lock": str(analysis.protocol_lock_path),
                },
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
