"""Replay and export the deterministic Phase-7 trajectory audit subset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from d5freq.evaluation.phase6_trajectory_export import (
    export_final_selected_trajectories,
)
from d5freq.utils.hashing import sha256_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the complete locked Phase-6 final matrix, deterministically "
            "select representative/worst runs, replay their FINAL specs, and "
            "publish authenticated ZSTD Parquet traces for Phase 7."
        )
    )
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results/final"),
        help="canonical six-CSV final result directory, relative to repo root",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="atomically replace an earlier generated selected-trajectory pair",
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    repo_root = arguments.repo_root.resolve()
    results_dir = (
        arguments.results_dir
        if arguments.results_dir.is_absolute()
        else repo_root / arguments.results_dir
    )
    result = export_final_selected_trajectories(
        repo_root=repo_root,
        results_dir=results_dir,
        replace=arguments.replace,
    )
    print(
        json.dumps(
            {
                "representative_manifest": str(result.representative_manifest),
                "representative_manifest_sha256": sha256_file(
                    result.representative_manifest
                ),
                "representative_entry_count": result.representative_count,
                "worst_manifest": str(result.worst_manifest),
                "worst_manifest_sha256": sha256_file(result.worst_manifest),
                "worst_entry_count": result.worst_count,
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
