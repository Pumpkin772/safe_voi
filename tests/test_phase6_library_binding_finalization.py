from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from d5freq.estimation.ood_detector import OODCalibrationArtifact
from d5freq.evaluation.controller_factories import LibraryArtifactBinding
from d5freq.identification.model_library import (
    ARXModeModel,
    BICRecord,
    DiscoveryMetadata,
    FeatureScalerState,
    ModeLibrary,
    sticky_transition_matrix,
)
from d5freq.utils.hashing import sha256_file, sha256_json
from scripts.phase6_finalize_library_bindings import (
    finalize_phase6_library_bindings,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _library(component_count: int) -> ModeLibrary:
    models = tuple(
        ARXModeModel(
            component_id=component,
            theta=np.array(
                [0.7, -0.1, 0.2, 0.02, -0.4, 0.05, component * 1.0e-4]
            ),
            residual_variance=1.0e-4 * (component + 1),
            multi_step_power_error_quantiles_pu={1: 0.001},
            multi_step_frequency_error_quantiles_hz={1: 0.01},
            multi_step_rocof_error_quantiles_hz_per_s={1: 0.1},
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
            bic_table=(BICRecord(component_count, 10.0, 0.0, True, 2),),
        ),
    )


def _calibration(
    library: ModeLibrary,
    library_path: Path,
    *,
    component_ids: tuple[int, ...] | None = None,
) -> OODCalibrationArtifact:
    identifiers = component_ids or tuple(range(len(library.models)))
    return OODCalibrationArtifact(
        calibration_scores=(0.1, 0.2, 0.3),
        dataset_sha256="a" * 64,
        split_manifest_sha256="b" * 64,
        mode_library_sha256=sha256_file(library_path),
        mode_library_logical_sha256=sha256_json(library.to_dict()),
        source_trajectory_sha256=("c" * 64,),
        known_component_ids=identifiers,
        covered_component_ids=identifiers,
        measurement_noise_variance_pu2=1.0e-8,
        variance_floor_pu2=1.0e-12,
    )


def _hysteresis_selection(hold_on_steps: int) -> dict[str, object]:
    return {
        "schema_version": "d5freq.phase4.v1",
        "ood_data_used_for_selection": False,
        "search_range": {
            "alpha_off": [0.05, 0.1, 0.2],
            "alpha_on": [0.005, 0.01, 0.02, 0.05],
            "hold_off_steps": [3, 5, 7],
            "hold_on_steps": [2, 3, 4],
        },
        "selected": {
            "alpha_off": 0.1,
            "alpha_on": 0.01,
            "hold_off_steps": 5,
            "hold_on_steps": hold_on_steps,
            "variance_floor": 1.0e-8,
        },
        "selection_objective": [
            "false_active_episode_count",
            "false_active_sample_count",
            "false_alert_sample_count",
            "distance_to_predeclared_default",
        ],
        "selection_population": "known_modes_only",
        "selection_unit": "leave_one_trajectory_out",
        "state_machine_confirmation_semantics": (
            "The L_on-th consecutive low p-value enters SUSPECT; the next "
            "continuing low p-value enters OOD_ACTIVE, exactly following the "
            "four-state specification diagram."
        ),
    }


def _write_phase4_manifest(directory: Path) -> None:
    files = [
        {
            "path": path.name,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(
            (
                directory / "ood_calibration_artifact.json",
                directory / "ood_hysteresis_selection.json",
            )
        )
    ]
    manifest_path = directory / "artifact_manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": "d5freq.phase4.v1",
            "scope": "all_phase4_artifacts_except_manifest_and_hash_sidecar",
            "artifact_set_sha256": sha256_json(files),
            "files": files,
        },
    )
    (directory / "artifact_manifest.sha256").write_text(
        sha256_file(manifest_path) + "\n",
        encoding="ascii",
        newline="\n",
    )


def _inputs(tmp_path: Path) -> tuple[dict[str, Path], dict[str, object]]:
    specs = {
        "native_k6_discovered": (6, "discovered_bic_label_free", 3),
        "fixed_k4_unlabeled": (4, "fixed_k4_unlabeled", 4),
        "labeled_training_only_k4": (4, "labeled_training_only", 3),
    }
    paths: dict[str, Path] = {}
    source_rows: list[dict[str, object]] = []
    bundle = tmp_path / "bundle"
    subset_manifest = bundle / "provenance" / "identification_subset_hashes.json"
    _write_json(subset_manifest, {"strict_test_fixture": True})
    for artifact_id, (component_count, protocol, hold_on_steps) in specs.items():
        library = _library(component_count)
        library_path = tmp_path / "libraries" / artifact_id / "mode_library.json"
        library.save_json(library_path)
        diagnosis = tmp_path / "diagnosis" / artifact_id
        calibration_path = diagnosis / "ood_calibration_artifact.json"
        selection_path = diagnosis / "ood_hysteresis_selection.json"
        _write_json(calibration_path, _calibration(library, library_path).to_dict())
        _write_json(selection_path, _hysteresis_selection(hold_on_steps))
        _write_phase4_manifest(diagnosis)
        paths[f"{artifact_id}_library"] = library_path
        paths[f"{artifact_id}_calibration"] = calibration_path
        paths[f"{artifact_id}_selection"] = selection_path
        source_rows.append(
            {
                "artifact_id": artifact_id,
                "component_count": component_count,
                "construction_protocol": protocol,
                "identification_subset_hash_manifest_sha256": sha256_file(
                    subset_manifest
                ),
                "identification_train_dataset_sha256": "d" * 64,
                "identification_validation_dataset_sha256": "e" * 64,
                "mode_library_file_sha256": sha256_file(library_path),
                "mode_library_logical_sha256": sha256_json(library.to_dict()),
                "ood_binding_status": "pending_separate_known_only_calibration",
                "ood_calibration_file_sha256": None,
                "runtime_label_access": "none",
            }
        )
    binding_inputs = bundle / "provenance" / "library_binding_inputs.json"
    source_payload = {
        "schema_version": "d5freq.library_binding_inputs.v1",
        "ood_calibration_status": (
            "not_built_here; each library requires separate known-only calibration"
        ),
        "identification_subset_hash_manifest": (
            "provenance/identification_subset_hashes.json"
        ),
        "libraries": source_rows,
    }
    _write_json(binding_inputs, source_payload)
    paths["binding_inputs"] = binding_inputs
    return paths, source_payload


def _arguments(paths: dict[str, Path], output: Path) -> dict[str, Path]:
    return {
        "binding_inputs_path": paths["binding_inputs"],
        "native_mode_library_path": paths["native_k6_discovered_library"],
        "fixed_k4_mode_library_path": paths["fixed_k4_unlabeled_library"],
        "labeled_mode_library_path": paths["labeled_training_only_k4_library"],
        "native_ood_calibration_path": paths["native_k6_discovered_calibration"],
        "fixed_k4_ood_calibration_path": paths[
            "fixed_k4_unlabeled_calibration"
        ],
        "labeled_ood_calibration_path": paths[
            "labeled_training_only_k4_calibration"
        ],
        "native_hysteresis_selection_path": paths[
            "native_k6_discovered_selection"
        ],
        "fixed_k4_hysteresis_selection_path": paths[
            "fixed_k4_unlabeled_selection"
        ],
        "labeled_hysteresis_selection_path": paths[
            "labeled_training_only_k4_selection"
        ],
        "output_directory": output,
    }


def test_finalizer_writes_three_strict_bindings_and_protocol_lock(
    tmp_path: Path,
) -> None:
    paths, _ = _inputs(tmp_path)
    arguments = _arguments(paths, tmp_path / "runtime_bindings")
    result = finalize_phase6_library_bindings(**arguments)

    assert set(result.bindings) == {
        "native_k6_discovered",
        "fixed_k4_unlabeled",
        "labeled_training_only_k4",
    }
    for artifact_id, binding_path in result.binding_paths.items():
        binding = LibraryArtifactBinding.load_json(binding_path)
        assert binding == result.bindings[artifact_id]
        binding.validate_files(
            paths[f"{artifact_id}_library"],
            paths[f"{artifact_id}_calibration"],
        )
        serialized = binding_path.read_text(encoding="utf-8").lower()
        assert "null" not in serialized
        assert "pending" not in serialized
        assert binding.runtime_label_access == "none"

    manifest = json.loads(
        result.finalization_manifest_path.read_text(encoding="utf-8")
    )
    assert manifest["runtime_selected_hysteresis"] is True
    assert manifest["runtime_label_access"] == "none"
    assert manifest["placeholder_values_present"] is False
    rows = {row["artifact_id"]: row for row in manifest["bindings"]}
    assert rows["native_k6_discovered"]["selected_hysteresis"]["L_on"] == 3
    assert rows["fixed_k4_unlabeled"]["selected_hysteresis"]["L_on"] == 4
    assert rows["labeled_training_only_k4"]["selected_hysteresis"]["L_on"] == 3
    for artifact_id, row in rows.items():
        assert row["ood_hysteresis_selection_file_sha256"] == sha256_file(
            paths[f"{artifact_id}_selection"]
        )
        assert row["phase4_artifact_manifest_file_sha256"] == sha256_file(
            paths[f"{artifact_id}_calibration"].parent / "artifact_manifest.json"
        )
        assert row["binding_file"] == result.binding_paths[artifact_id].name
        assert row["mode_library_path"]
        assert row["ood_calibration_path"]
        assert row["ood_hysteresis_selection_path"]

    hashes = json.loads(result.artifact_hashes_path.read_text(encoding="utf-8"))
    declared = hashes["sha256"]
    actual = {
        path.relative_to(result.output_directory).as_posix(): sha256_file(path)
        for path in sorted(result.output_directory.rglob("*"))
        if path.is_file() and path != result.artifact_hashes_path
    }
    assert declared == actual


def test_finalizer_rejects_crosswired_calibration_and_unordered_components(
    tmp_path: Path,
) -> None:
    paths, _ = _inputs(tmp_path)
    crosswired = _arguments(paths, tmp_path / "crosswired")
    crosswired["fixed_k4_ood_calibration_path"] = paths[
        "native_k6_discovered_calibration"
    ]
    crosswired["fixed_k4_hysteresis_selection_path"] = paths[
        "native_k6_discovered_selection"
    ]
    with pytest.raises(ValueError, match="fixed_k4_unlabeled OOD calibration"):
        finalize_phase6_library_bindings(**crosswired)

    labeled_library_path = paths["labeled_training_only_k4_library"]
    labeled_library = ModeLibrary.load_json(labeled_library_path)
    unordered = _calibration(
        labeled_library,
        labeled_library_path,
        component_ids=(1, 0, 2, 3),
    )
    _write_json(paths["labeled_training_only_k4_calibration"], unordered.to_dict())
    _write_phase4_manifest(paths["labeled_training_only_k4_calibration"].parent)
    with pytest.raises(ValueError, match="known component IDs are not ordered"):
        finalize_phase6_library_bindings(
            **_arguments(paths, tmp_path / "unordered")
        )


def test_finalizer_locks_k4_hysteresis_selection_and_rejects_label_access(
    tmp_path: Path,
) -> None:
    paths, source = _inputs(tmp_path)
    _write_json(
        paths["fixed_k4_unlabeled_selection"],
        _hysteresis_selection(3),
    )
    with pytest.raises(ValueError, match="artifact manifest SHA-256 mismatch"):
        finalize_phase6_library_bindings(
            **_arguments(paths, tmp_path / "tampered_hysteresis")
        )
    _write_phase4_manifest(paths["fixed_k4_unlabeled_selection"].parent)
    with pytest.raises(ValueError, match="must select L_on=4"):
        finalize_phase6_library_bindings(
            **_arguments(paths, tmp_path / "wrong_hysteresis")
        )

    source["libraries"][0]["runtime_label_access"] = "private_labels"  # type: ignore[index]
    _write_json(paths["binding_inputs"], source)
    with pytest.raises(ValueError, match="runtime label access"):
        finalize_phase6_library_bindings(
            **_arguments(paths, tmp_path / "label_access")
        )


def test_finalizer_refuses_nonempty_output_without_overwriting(tmp_path: Path) -> None:
    paths, _ = _inputs(tmp_path)
    output = tmp_path / "occupied"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        finalize_phase6_library_bindings(**_arguments(paths, output))
    assert sentinel.read_text(encoding="utf-8") == "preserve"
