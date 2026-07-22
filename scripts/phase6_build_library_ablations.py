"""Build frozen Phase-6 library ablations plus B1/B4 artifacts.

This command consumes the existing verified identification and label-free
discovery artifacts.  It intentionally does not run OOD calibration; each
library is calibrated later by the separate known-only calibration stage.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from d5freq.evaluation.library_ablations import (
    build_phase6_library_ablations_from_artifacts,
)
from d5freq.utils.hashing import sha256_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build fixed-K4 unlabeled and labeled-training-only libraries, "
            "the fixed-K4 private-train-only evaluation mapping, the "
            "validation-only B1 selection, the evaluation-only B4 ARX "
            "artifact, and canonical identification subset hashes."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/base.yaml"),
        help="frozen base YAML configuration",
    )
    parser.add_argument(
        "--experiments-config",
        type=Path,
        default=Path("configs/experiments.yaml"),
        help="frozen Phase-6 protocol YAML",
    )
    parser.add_argument(
        "--public-data-dir",
        type=Path,
        default=Path("artifacts/identification_data/public"),
        help="verified public identification artifact directory",
    )
    parser.add_argument(
        "--private-data-dir",
        type=Path,
        default=Path("artifacts/identification_data/private"),
        help="evaluation-only private metadata directory",
    )
    parser.add_argument(
        "--mode-discovery-dir",
        type=Path,
        default=Path("artifacts/mode_discovery"),
        help="frozen native K6 discovery artifact directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/phase6_library_ablations"),
        help="new or empty output directory; existing content is never replaced",
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    result = build_phase6_library_ablations_from_artifacts(
        base_config_path=arguments.config,
        experiments_config_path=arguments.experiments_config,
        public_data_directory=arguments.public_data_dir,
        private_data_directory=arguments.private_data_dir,
        mode_discovery_directory=arguments.mode_discovery_dir,
        output_directory=arguments.output_dir,
    )
    print(
        json.dumps(
            {
                "artifact_hashes_file_sha256": sha256_file(
                    result.artifact_hashes_path
                ),
                "build_manifest_file_sha256": sha256_file(
                    result.build_manifest_path
                ),
                "fixed_k4_component_count": len(
                    result.fixed_k4.discovery_run.mode_library.models
                ),
                "fixed_k4_evaluation_mapping_file_sha256": sha256_file(
                    result.fixed_k4.evaluation_mapping_path
                ),
                "fixed_reference_component_id": (
                    result.fixed_reference_selection.selected_component_id
                ),
                "labeled_component_count": len(
                    result.labeled_library.mode_library.models
                ),
                "oracle_arx_model_count": len(result.oracle_arx.artifact.models),
                "output_directory": str(result.output_directory),
                "subset_hash_manifest_file_sha256": sha256_file(
                    result.subset_hash_manifest_path
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
