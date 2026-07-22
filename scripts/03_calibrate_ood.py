"""Calibrate and evaluate Phase-4 online mode diagnosis and OOD detection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from d5freq.evaluation.phase4_pipeline import run_phase4_pipeline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build known-only conformal calibration, freeze truth-free runtime "
            "logs, and then run evaluation-only Phase-4 metrics."
        )
    )
    parser.add_argument(
        "--config", type=Path, default=Path("configs/base.yaml")
    )
    parser.add_argument(
        "--known-modes-config",
        type=Path,
        default=Path("configs/modes_known.yaml"),
    )
    parser.add_argument(
        "--ood-modes-config",
        type=Path,
        default=Path("configs/modes_ood.yaml"),
    )
    parser.add_argument(
        "--public-data-dir",
        type=Path,
        default=Path("artifacts/identification_data/public"),
    )
    parser.add_argument(
        "--private-data-dir",
        type=Path,
        default=Path("artifacts/identification_data/private"),
    )
    parser.add_argument(
        "--mode-library",
        type=Path,
        default=Path("artifacts/mode_discovery/mode_library.json"),
    )
    parser.add_argument(
        "--cluster-assignments",
        type=Path,
        default=Path("artifacts/mode_discovery/cluster_assignments.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/online_diagnosis"),
        help="new or empty output directory",
    )
    parser.add_argument(
        "--skip-trajectory-hash-verification",
        action="store_true",
        help=(
            "skip only the expensive per-Parquet hashes; manifest/schema/logical "
            "hash checks remain mandatory (canonical runs must not use this flag)"
        ),
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    result = run_phase4_pipeline(
        base_config_path=arguments.config,
        known_modes_config_path=arguments.known_modes_config,
        ood_modes_config_path=arguments.ood_modes_config,
        public_data_directory=arguments.public_data_dir,
        private_data_directory=arguments.private_data_dir,
        mode_library_path=arguments.mode_library,
        cluster_assignments_path=arguments.cluster_assignments,
        output_directory=arguments.output_dir,
        verify_trajectory_hashes=(
            not arguments.skip_trajectory_hash_verification
        ),
    )
    print(
        json.dumps(
            {
                "artifact_manifest_sha256": result.artifact_manifest_sha256,
                "calibration_artifact_sha256": (
                    result.calibration_artifact_sha256
                ),
                "output_directory": str(result.output_directory),
                "runtime_log_sha256": result.runtime_log_sha256,
                "selected_ood_config": {
                    "alpha_on": result.selected_ood_config.alpha_on,
                    "alpha_off": result.selected_ood_config.alpha_off,
                    "hold_on_steps": result.selected_ood_config.L_on,
                    "hold_off_steps": result.selected_ood_config.L_off,
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
