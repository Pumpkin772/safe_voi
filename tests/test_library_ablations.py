from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from d5freq.controllers.final_arx_mpc import FixedReferenceSelectionArtifact
from d5freq.data import PrivateTrajectoryMetadata
from d5freq.evaluation.baselines.oracle import OracleARXArtifact
from d5freq.evaluation.library_ablations import (
    FixedK4EvaluationMappingArtifact,
    IDENTIFICATION_SUBSET_HASH_SCHEMA_VERSION,
    IdentificationSubsetDigest,
    LabeledTrainingLibraryRun,
    anonymous_component_mapping,
    assign_validation_by_training_feature_centroids,
    build_fixed_k4_evaluation_mapping,
    build_fixed_reference_selection,
    build_labeled_training_library,
    build_oracle_arx_artifact,
    build_phase6_library_ablations_from_artifacts,
    identification_subset_digests,
    private_training_projection_sha256,
    save_fixed_reference_selection,
)
from d5freq.identification.model_library import (
    ARXModeModel,
    BICRecord,
    DiscoveryMetadata,
    FeatureScalerState,
    ModeLibrary,
    sticky_transition_matrix,
)
from d5freq.identification.offline_pipeline import (
    offline_pipeline_config_from_base_config,
)
from d5freq.utils.config import config_sha256, load_yaml
from d5freq.utils.hashing import sha256_file, sha256_json


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "artifacts" / "identification_data" / "public"
DISCOVERY = ROOT / "artifacts" / "mode_discovery"


def _library(component_count: int = 4) -> ModeLibrary:
    models = tuple(
        ARXModeModel(
            component_id=component,
            theta=np.array(
                [0.7, -0.1, 0.2, 0.02, -0.4, 0.05, component * 1.0e-4]
            ),
            residual_variance=1.0e-4 * (component + 1),
            multi_step_power_error_quantiles_pu={1: 0.001, 2: 0.002},
            multi_step_frequency_error_quantiles_hz={1: 0.01, 2: 0.02},
            multi_step_rocof_error_quantiles_hz_per_s={1: 0.1, 2: 0.2},
            p_output_min_pu=-0.05,
            p_output_max_pu=0.05,
            ramp_down_pu_per_s=0.02,
            ramp_up_pu_per_s=0.02,
            training_episode_count=4,
            training_sample_count=100,
        )
        for component in range(component_count)
    )
    return ModeLibrary(
        models=models,
        transition_matrix=sticky_transition_matrix(component_count),
        feature_scaler=FeatureScalerState(
            mean=np.zeros(8),
            scale=np.ones(8),
            variance=np.ones(8),
            n_samples_seen=16,
        ),
        discovery_metadata=DiscoveryMetadata(
            selected_k=component_count,
            candidate_k_min=component_count,
            candidate_k_max=component_count,
            covariance_type="full",
            n_init=2,
            random_seed=3,
            bic_table=(
                BICRecord(component_count, 10.0, 0.0, True, 2),
            ),
        ),
    )


def test_anonymous_component_ids_are_order_invariant_and_not_input_order() -> None:
    names = ("nominal", "sluggish", "derated", "unavailable")
    forward, reverse = anonymous_component_mapping(names)
    shuffled, shuffled_reverse = anonymous_component_mapping(tuple(reversed(names)))

    assert forward == shuffled
    assert reverse == shuffled_reverse
    assert set(forward.values()) == {0, 1, 2, 3}
    assert [forward[name] for name in names] != [0, 1, 2, 3]


def test_fixed_k4_semantic_mapping_is_eval_only_training_majority_and_many_to_one(
    tmp_path: Path,
) -> None:
    library = _library()
    runtime_directory = tmp_path / "runtime"
    library_path = runtime_directory / "mode_library.json"
    library.save_json(library_path)

    labels_by_component = {
        0: ("semantic-alpha", "semantic-alpha"),
        1: ("semantic-alpha", "semantic-beta"),
        2: ("semantic-beta", "semantic-beta"),
        3: ("semantic-alpha", "semantic-alpha"),
    }
    metadata: list[PrivateTrajectoryMetadata] = []
    assignment_rows: list[dict[str, object]] = []
    sequence = 1
    for component, labels in labels_by_component.items():
        for label in labels:
            trajectory_id = f"{sequence:032x}"
            metadata.append(
                PrivateTrajectoryMetadata(
                    trajectory_id=trajectory_id,
                    mode_name_eval_only=label,
                    trajectory_seed_eval_only=sequence,
                    excitation_pair_id_eval_only=f"{sequence + 100:032x}",
                    excitation_family_eval_only="prbs",
                    split="train",
                    excitation_sha256=f"{sequence % 16:x}" * 64,
                )
            )
            assignment_rows.append(
                {
                    "trajectory_id": trajectory_id,
                    "dataset_split": "train",
                    "component_id": component,
                    **{
                        f"component_probability_{candidate}": float(
                            candidate == component
                        )
                        for candidate in range(4)
                    },
                }
            )
            sequence += 1
    for component in range(4):
        assignment_rows.append(
            {
                "trajectory_id": f"{sequence:032x}",
                "dataset_split": "validation",
                "component_id": component,
                **{
                    f"component_probability_{candidate}": float(
                        candidate == component
                    )
                    for candidate in range(4)
                },
            }
        )
        sequence += 1
    assignments_path = runtime_directory / "cluster_assignments.csv"
    pd.DataFrame(assignment_rows).to_csv(assignments_path, index=False)
    assignment_digest = sha256_file(assignments_path)
    destination = (
        tmp_path / "evaluation_only" / "component_mapping_eval_only.json"
    )

    artifact = build_fixed_k4_evaluation_mapping(
        library,
        tuple(metadata),
        mode_library_path=library_path,
        cluster_assignments_path=assignments_path,
        expected_private_training_projection_sha256=(
            private_training_projection_sha256(tuple(metadata))
        ),
        output_path=destination,
    )
    restored = FixedK4EvaluationMappingArtifact.load_json(destination)

    assert restored.to_dict() == artifact.to_dict()
    assert [
        item.selected_mode_name_eval_only for item in artifact.components
    ] == ["semantic-alpha", "semantic-alpha", "semantic-beta", "semantic-alpha"]
    assert artifact.components[1].purity == 0.5
    assert artifact.tie_break_rule == "lexicographically_smallest_mode_name"
    assert artifact.runtime_consumable is False
    assert artifact.validation_label_access is False
    assert artifact.test_label_access is False
    assert sha256_file(assignments_path) == assignment_digest
    runtime_text = library_path.read_text(encoding="utf-8") + assignments_path.read_text(
        encoding="utf-8"
    )
    assert "semantic-alpha" not in runtime_text
    assert "semantic-beta" not in runtime_text
    with pytest.raises(FileExistsError, match="overwrite"):
        build_fixed_k4_evaluation_mapping(
            library,
            tuple(metadata),
            mode_library_path=library_path,
            cluster_assignments_path=assignments_path,
            expected_private_training_projection_sha256=(
                private_training_projection_sha256(tuple(metadata))
            ),
            output_path=destination,
        )


def test_validation_assignment_uses_frozen_training_centroids_with_stable_ties() -> None:
    training = np.array([[0.0, 0.0], [0.2, 0.0], [2.0, 0.0], [2.2, 0.0]])
    components = np.array([0, 0, 1, 1], dtype=np.int64)
    validation = np.array([[0.1, 0.0], [2.1, 0.0], [1.1, 0.0]])

    assigned = assign_validation_by_training_feature_centroids(
        training,
        components,
        validation,
        component_count=2,
    )

    np.testing.assert_array_equal(assigned, np.array([0, 1, 0]))
    assert assigned.flags.writeable is False


def test_labeled_builder_rejects_nontraining_private_metadata_before_arx_fit(
    tmp_path: Path,
) -> None:
    training_id = "1" * 32
    validation_id = "2" * 32
    leaked_validation_row = PrivateTrajectoryMetadata(
        trajectory_id=training_id,
        mode_name_eval_only="hidden",
        trajectory_seed_eval_only=1,
        excitation_pair_id_eval_only="3" * 32,
        excitation_family_eval_only="prbs",
        split="validation",
        excitation_sha256="a" * 64,
    )
    config = offline_pipeline_config_from_base_config(
        load_yaml(ROOT / "configs" / "base.yaml")
    )

    with pytest.raises(ValueError, match="training rows only"):
        build_labeled_training_library(
            (SimpleNamespace(trajectory_id=training_id),),
            (SimpleNamespace(trajectory_id=validation_id),),
            (leaked_validation_row,),
            config=config,
            output_directory=tmp_path / "must_not_exist",
            public_dataset_sha256="b" * 64,
            private_metadata_file_sha256="c" * 64,
            expected_private_training_projection_sha256="d" * 64,
        )
    assert not (tmp_path / "must_not_exist").exists()


def test_identification_subset_hash_matches_binding_definition_and_is_expanded() -> None:
    subsets = identification_subset_digests(PUBLIC)
    assert len(subsets["train"].trajectory_rows) == 96
    assert len(subsets["validation"].trajectory_rows) == 32
    for split in ("train", "validation"):
        subset = subsets[split]
        expected = {
            "schema_version": IDENTIFICATION_SUBSET_HASH_SCHEMA_VERSION,
            "split": split,
            "trajectory_sha256": sorted(
                row["sha256"] for row in subset.trajectory_rows
            ),
        }
        assert subset.canonical_hash_input == expected
        assert subset.canonical_sha256 == sha256_json(expected)
        assert [row["trajectory_id"] for row in subset.trajectory_rows] == sorted(
            row["trajectory_id"] for row in subset.trajectory_rows
        )


def test_identification_subset_rejects_duplicate_hashes() -> None:
    rows = (
        {"trajectory_id": "1" * 32, "sha256": "a" * 64},
        {"trajectory_id": "2" * 32, "sha256": "a" * 64},
    )
    with pytest.raises(ValueError, match="duplicate trajectory hashes"):
        IdentificationSubsetDigest("train", "b" * 64, rows)


@pytest.fixture(scope="module")
def fixed_reference() -> FixedReferenceSelectionArtifact:
    return build_fixed_reference_selection(
        mode_library_path=DISCOVERY / "mode_library.json",
        cluster_assignments_path=DISCOVERY / "cluster_assignments.csv",
        label_free_artifact_hashes_path=(
            DISCOVERY / "label_free_artifact_hashes.json"
        ),
        public_data_directory=PUBLIC,
        protocol_sha256=config_sha256(load_yaml(ROOT / "configs" / "experiments.yaml")),
    )


def test_b1_selection_is_validation_only_truth_free_and_hash_bound(
    fixed_reference: FixedReferenceSelectionArtifact,
) -> None:
    subsets = identification_subset_digests(PUBLIC)
    assert fixed_reference.selection_split == "identification_validation"
    assert fixed_reference.label_access == "none"
    assert fixed_reference.selection_dataset_sha256 == subsets[
        "validation"
    ].canonical_sha256
    assert fixed_reference.selected_component_id == 3
    assert all(
        score.registered_episode_count == score.retained_episode_count
        for score in fixed_reference.candidate_scores
    )
    serialized = json.dumps(fixed_reference.to_dict(), sort_keys=True)
    assert all(name not in serialized for name in ("nominal", "sluggish", "derated"))


def test_b1_rejects_assignment_file_not_bound_by_label_free_manifest(
    tmp_path: Path,
) -> None:
    tampered = tmp_path / "cluster_assignments.csv"
    tampered.write_bytes(
        (DISCOVERY / "cluster_assignments.csv").read_bytes() + b"\n"
    )
    with pytest.raises(ValueError, match="cluster_assignments.csv SHA-256 mismatch"):
        build_fixed_reference_selection(
            mode_library_path=DISCOVERY / "mode_library.json",
            cluster_assignments_path=tampered,
            label_free_artifact_hashes_path=(
                DISCOVERY / "label_free_artifact_hashes.json"
            ),
            public_data_directory=PUBLIC,
            protocol_sha256="e" * 64,
        )


def test_oracle_artifact_is_evaluation_only_and_uses_local_component_zero(
    tmp_path: Path,
) -> None:
    library = _library()
    labeled = LabeledTrainingLibraryRun(
        output_directory=tmp_path,
        mode_library=library,
        mode_library_file_sha256="a" * 64,
        mode_library_logical_sha256=sha256_json(library.to_dict()),
        train_assignments=np.arange(4, dtype=np.int64),
        validation_assignments=np.arange(4, dtype=np.int64),
        component_to_class_eval_only={
            0: "semantic-a",
            1: "semantic-b",
            2: "semantic-c",
            3: "semantic-d",
        },
    )
    destination = tmp_path / "evaluation_only" / "oracle_arx_artifact.json"
    built = build_oracle_arx_artifact(
        labeled,
        identification_train_dataset_sha256="b" * 64,
        training_config_sha256="c" * 64,
        output_path=destination,
    )
    restored = OracleARXArtifact.load_json(destination)

    assert restored.to_dict() == built.artifact.to_dict()
    assert restored.training_dataset_sha256 == "b" * 64
    assert restored.config_sha256 == "c" * 64
    assert set(restored.models_by_key) == {
        "semantic-a",
        "semantic-b",
        "semantic-c",
        "semantic-d",
    }
    assert all(model.component_id == 0 for model in restored.models_by_key.values())
    with pytest.raises(FileExistsError, match="overwrite"):
        build_oracle_arx_artifact(
            labeled,
            identification_train_dataset_sha256="b" * 64,
            training_config_sha256="c" * 64,
            output_path=destination,
        )


def test_fixed_reference_save_and_full_builder_refuse_existing_content(
    tmp_path: Path,
    fixed_reference: FixedReferenceSelectionArtifact,
) -> None:
    selection_path = tmp_path / "selection.json"
    save_fixed_reference_selection(fixed_reference, selection_path)
    with pytest.raises(FileExistsError, match="overwrite"):
        save_fixed_reference_selection(fixed_reference, selection_path)

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    sentinel = occupied / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError, match="not empty"):
        build_phase6_library_ablations_from_artifacts(
            base_config_path=tmp_path / "missing-base.yaml",
            experiments_config_path=tmp_path / "missing-experiments.yaml",
            public_data_directory=tmp_path / "missing-public",
            private_data_directory=tmp_path / "missing-private",
            mode_discovery_directory=tmp_path / "missing-discovery",
            output_directory=occupied,
        )
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_controller_runtime_does_not_import_evaluation_ablation_builder() -> None:
    controller_root = ROOT / "src" / "d5freq" / "controllers"
    offenders = [
        path.name
        for path in controller_root.glob("*.py")
        if "library_ablations" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
