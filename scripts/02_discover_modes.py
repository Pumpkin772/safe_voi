"""Discover hidden IBR modes from public identification trajectories."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from d5freq.data import load_public_identification_data
from d5freq.identification.offline_pipeline import (
    REQUIRED_LABEL_FREE_ARTIFACTS,
    offline_pipeline_config_from_base_config,
    run_label_free_mode_discovery,
)
from d5freq.utils.config import config_sha256, load_yaml, save_yaml
from d5freq.utils.hashing import sha256_file


LABEL_FREE_SOURCE_PATHS: tuple[str, ...] = (
    "scripts/02_discover_modes.py",
    "src/d5freq/identification/offline_pipeline.py",
    "src/d5freq/identification/mode_discovery.py",
    "src/d5freq/identification/arx.py",
    "src/d5freq/identification/model_library.py",
)


def label_free_source_hashes(repository_root: Path) -> dict[str, str]:
    """Hash the exact in-repository sources that produce the frozen library."""

    root = repository_root.expanduser().resolve()
    hashes: dict[str, str] = {}
    for relative in LABEL_FREE_SOURCE_PATHS:
        source = root / Path(relative)
        if not source.is_file():
            raise FileNotFoundError(source)
        hashes[relative] = sha256_file(source)
    return hashes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run training-only ARX/GMM mode discovery, frozen validation, and "
            "a subsequent evaluation-only private-label audit."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/base.yaml"),
        help="base YAML configuration",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("artifacts/identification_data"),
        help="identification dataset root containing public/ and private/",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/mode_discovery"),
        help="new or empty output directory",
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    base_config = load_yaml(arguments.config)
    pipeline_config = offline_pipeline_config_from_base_config(base_config)
    public_directory = arguments.data_dir / "public"

    # These loaders have no path or API to the private evaluation tree.
    training = load_public_identification_data(
        public_directory,
        split="train",
        verify_hashes=True,
    )
    validation = load_public_identification_data(
        public_directory,
        split="validation",
        verify_hashes=True,
    )
    run = run_label_free_mode_discovery(
        training,
        validation,
        config=pipeline_config,
        output_directory=arguments.output_dir,
    )
    save_yaml(base_config, run.output_directory / "resolved_base_config.yaml")
    label_free_summary_path = run.output_directory / "label_free_summary.json"
    label_free_summary = json.loads(
        label_free_summary_path.read_text(encoding="utf-8")
    )
    label_free_summary["base_config_sha256"] = config_sha256(base_config)
    public_manifest_path = public_directory / "public_manifest.json"
    public_manifest = json.loads(public_manifest_path.read_text(encoding="utf-8"))
    label_free_summary["public_dataset_sha256"] = public_manifest["dataset_sha256"]
    label_free_summary["public_manifest_file_sha256"] = sha256_file(
        public_manifest_path
    )
    repository_root = Path(__file__).resolve().parents[1]
    label_free_summary["source_hashes"] = label_free_source_hashes(repository_root)
    label_free_summary["resolved_config_artifact"] = "resolved_base_config.yaml"
    label_free_summary_path.write_text(
        json.dumps(
            label_free_summary,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    artifact_hashes = {
        name: sha256_file(run.output_directory / name)
        for name in (
            *REQUIRED_LABEL_FREE_ARTIFACTS,
            "label_free_summary.json",
            "resolved_base_config.yaml",
        )
    }
    (run.output_directory / "label_free_artifact_hashes.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scope": "label_free_artifacts_before_reference_evaluation",
                "sha256": artifact_hashes,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # Read private labels only after every label-free result, including the
    # frozen model-library hash, has been persisted.
    from d5freq.evaluation.offline_mode_discovery_evaluation import (
        REQUIRED_MODE_DISCOVERY_ARTIFACTS,
        evaluate_discovery_with_private_metadata,
    )

    private_evaluation = evaluate_discovery_with_private_metadata(
        output_directory=run.output_directory,
        private_metadata_path=(
            arguments.data_dir / "private" / "evaluation_metadata.json"
        ),
    )
    missing = [
        name for name in REQUIRED_MODE_DISCOVERY_ARTIFACTS
        if not (run.output_directory / name).is_file()
    ]
    if missing:
        raise RuntimeError(f"mode-discovery artifact set is incomplete: {missing}")

    selected_score = next(
        score
        for score in run.discovery.mixture.candidate_scores
        if score.component_count == run.discovery.mixture.selected_k
    )
    summary = {
        "output_directory": str(run.output_directory),
        "training_episode_count": len(training),
        "validation_episode_count": len(validation),
        "selected_k": run.discovery.mixture.selected_k,
        "selected_by": "minimum_training_bic",
        "selected_gmm_converged": selected_score.converged,
        "hit_configured_k_max": (
            run.discovery.mixture.selected_k == pipeline_config.discovery.k_max
        ),
        "model_library_sha256": run.model_library_sha256,
        "private_evaluation_only": {
            "adjusted_rand_index": private_evaluation.adjusted_rand_index,
            "normalized_mutual_information": (
                private_evaluation.normalized_mutual_information
            ),
            "macro_f1": private_evaluation.macro_f1,
            "discovered_component_count": len(private_evaluation.component_ids),
            "reference_class_count": len(private_evaluation.reference_classes),
            "mode_count_matches_private_truth": (
                len(private_evaluation.component_ids)
                == len(private_evaluation.reference_classes)
            ),
        },
        "required_artifact_count": len(REQUIRED_MODE_DISCOVERY_ARTIFACTS),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
