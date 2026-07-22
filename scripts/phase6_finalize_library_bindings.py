"""Finalize the three Phase-6 runtime library/calibration bindings.

This command consumes independently generated OOD calibration artifacts.  It
never runs calibration, never reads evaluation labels, and never edits the
pre-calibration library bundle.  The output directory must be new or empty.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from d5freq.estimation.ood_detector import OODCalibrationArtifact, OODDetectorConfig
from d5freq.evaluation.controller_factories import (
    LibraryArtifactBinding,
    LibraryConstructionProtocol,
)
from d5freq.identification.model_library import ModeLibrary
from d5freq.utils.hashing import sha256_file, sha256_json


SOURCE_SCHEMA_VERSION = "d5freq.library_binding_inputs.v1"
FINALIZATION_SCHEMA_VERSION = "d5freq.library_binding_finalization.v1"
_SOURCE_TOP_KEYS = frozenset(
    {
        "schema_version",
        "ood_calibration_status",
        "identification_subset_hash_manifest",
        "libraries",
    }
)
_SOURCE_LIBRARY_KEYS = frozenset(
    {
        "artifact_id",
        "component_count",
        "construction_protocol",
        "identification_subset_hash_manifest_sha256",
        "identification_train_dataset_sha256",
        "identification_validation_dataset_sha256",
        "mode_library_file_sha256",
        "mode_library_logical_sha256",
        "ood_binding_status",
        "ood_calibration_file_sha256",
        "runtime_label_access",
    }
)
_SOURCE_OOD_STATUS = (
    "not_built_here; each library requires separate known-only calibration"
)
_SOURCE_BINDING_STATUS = "pending_separate_known_only_calibration"
_HYSTERESIS_SCHEMA_VERSION = "d5freq.phase4.v1"
_HYSTERESIS_TOP_KEYS = frozenset(
    {
        "schema_version",
        "ood_data_used_for_selection",
        "search_range",
        "selected",
        "selection_objective",
        "selection_population",
        "selection_unit",
        "state_machine_confirmation_semantics",
    }
)
_HYSTERESIS_SEARCH_KEYS = frozenset(
    {"alpha_off", "alpha_on", "hold_off_steps", "hold_on_steps"}
)
_HYSTERESIS_SELECTED_KEYS = frozenset(
    {"alpha_off", "alpha_on", "hold_off_steps", "hold_on_steps", "variance_floor"}
)
_PHASE4_MANIFEST_KEYS = frozenset(
    {"schema_version", "scope", "artifact_set_sha256", "files"}
)
_PHASE4_MANIFEST_FILE_KEYS = frozenset({"path", "sha256", "size_bytes"})
_CONFIRMATION_SEMANTICS = (
    "The L_on-th consecutive low p-value enters SUSPECT; the next continuing "
    "low p-value enters OOD_ACTIVE, exactly following the four-state "
    "specification diagram."
)
_EXPECTED_LIBRARIES: tuple[
    tuple[str, LibraryConstructionProtocol, int, int, str], ...
] = (
    (
        "native_k6_discovered",
        LibraryConstructionProtocol.DISCOVERED_BIC_LABEL_FREE,
        6,
        3,
        "native_k6_discovered.json",
    ),
    (
        "fixed_k4_unlabeled",
        LibraryConstructionProtocol.FIXED_K4_UNLABELED,
        4,
        4,
        "fixed_k4_unlabeled.json",
    ),
    (
        "labeled_training_only_k4",
        LibraryConstructionProtocol.LABELED_TRAINING_ONLY,
        4,
        3,
        "labeled_training_only_k4.json",
    ),
)


def _strict_json(path: Path, name: str) -> object:
    def reject_nonfinite(token: str) -> None:
        raise ValueError(f"{name} contains forbidden JSON number {token!r}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_nonfinite)


def _exact_mapping(
    value: object,
    expected: frozenset[str],
    name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise TypeError(f"{name} must be a string-keyed mapping")
    actual = frozenset(value)
    if actual != expected:
        raise ValueError(
            f"{name} keys mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    return value


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _empty_directory(path: str | Path) -> Path:
    output = Path(path).expanduser().resolve()
    if output.exists() and not output.is_dir():
        raise NotADirectoryError(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    return output


def _write_json(path: Path, payload: object) -> None:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(serialized + "\n")


def _write_artifact_hashes(output: Path) -> Path:
    destination = output / "artifact_hashes.json"
    hashes = {
        path.relative_to(output).as_posix(): sha256_file(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.resolve() != destination.resolve()
    }
    _write_json(
        destination,
        {
            "schema_version": 1,
            "hash_algorithm": "sha256",
            "scope": "all_files_except_this_manifest",
            "sha256": hashes,
        },
    )
    return destination


def _reject_runtime_placeholders(value: object, path: str = "binding") -> None:
    if value is None:
        raise ValueError(f"{path} contains a null runtime binding value")
    if isinstance(value, str) and "pending" in value.strip().lower():
        raise ValueError(f"{path} contains a pending runtime binding value")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_runtime_placeholders(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            _reject_runtime_placeholders(item, f"{path}[{index}]")


def _load_source_entries(path: Path) -> Mapping[str, Mapping[str, Any]]:
    payload = _exact_mapping(
        _strict_json(path, "library binding inputs"),
        _SOURCE_TOP_KEYS,
        "library binding inputs",
    )
    if payload["schema_version"] != SOURCE_SCHEMA_VERSION:
        raise ValueError("library binding input schema_version mismatch")
    if payload["ood_calibration_status"] != _SOURCE_OOD_STATUS:
        raise ValueError("unexpected pre-calibration source status")
    relative_manifest = Path(str(payload["identification_subset_hash_manifest"]))
    if relative_manifest.is_absolute() or ".." in relative_manifest.parts:
        raise ValueError("identification subset manifest path must be safe and relative")
    bundle_root = path.parent.parent.resolve()
    subset_manifest = (bundle_root / relative_manifest).resolve()
    if not subset_manifest.is_relative_to(bundle_root) or not subset_manifest.is_file():
        raise ValueError("identification subset hash manifest is missing or escapes bundle")

    raw_entries = payload["libraries"]
    if not isinstance(raw_entries, list) or len(raw_entries) != 3:
        raise ValueError("library binding inputs must contain exactly three libraries")
    entries: dict[str, Mapping[str, Any]] = {}
    for index, raw_entry in enumerate(raw_entries):
        entry = _exact_mapping(
            raw_entry,
            _SOURCE_LIBRARY_KEYS,
            f"library binding input {index}",
        )
        artifact_id = str(entry["artifact_id"])
        if artifact_id in entries:
            raise ValueError("library binding inputs contain duplicate artifact IDs")
        if entry["ood_binding_status"] != _SOURCE_BINDING_STATUS:
            raise ValueError("source binding status is not the registered pending state")
        if entry["ood_calibration_file_sha256"] is not None:
            raise ValueError("source binding unexpectedly contains a calibration hash")
        if entry["runtime_label_access"] != "none":
            raise ValueError("runtime label access must be exactly 'none'")
        for hash_name in (
            "identification_subset_hash_manifest_sha256",
            "identification_train_dataset_sha256",
            "identification_validation_dataset_sha256",
            "mode_library_file_sha256",
            "mode_library_logical_sha256",
        ):
            _sha256(entry[hash_name], hash_name)
        entries[artifact_id] = entry

    expected_ids = {item[0] for item in _EXPECTED_LIBRARIES}
    if set(entries) != expected_ids:
        raise ValueError("library binding inputs do not contain the registered artifact IDs")
    subset_manifest_digest = sha256_file(subset_manifest)
    subset_bindings = {
        (
            entry["identification_subset_hash_manifest_sha256"],
            entry["identification_train_dataset_sha256"],
            entry["identification_validation_dataset_sha256"],
        )
        for entry in entries.values()
    }
    if len(subset_bindings) != 1:
        raise ValueError("three library inputs disagree on identification provenance")
    if next(iter(subset_bindings))[0] != subset_manifest_digest:
        raise ValueError("identification subset hash manifest SHA-256 mismatch")

    for artifact_id, protocol, component_count, _, _ in _EXPECTED_LIBRARIES:
        entry = entries[artifact_id]
        if entry["construction_protocol"] != protocol.value:
            raise ValueError(f"{artifact_id} construction protocol mismatch")
        if (
            isinstance(entry["component_count"], bool)
            or not isinstance(entry["component_count"], int)
            or entry["component_count"] != component_count
        ):
            raise ValueError(f"{artifact_id} component count mismatch")
    return MappingProxyType(entries)


def _load_hysteresis_selection(
    path: Path,
    *,
    artifact_id: str,
    expected_hold_on_steps: int,
) -> tuple[str, dict[str, object]]:
    payload = _exact_mapping(
        _strict_json(path, f"{artifact_id} OOD hysteresis selection"),
        _HYSTERESIS_TOP_KEYS,
        f"{artifact_id} OOD hysteresis selection",
    )
    if payload["schema_version"] != _HYSTERESIS_SCHEMA_VERSION:
        raise ValueError(f"{artifact_id} hysteresis selection schema mismatch")
    if payload["ood_data_used_for_selection"] is not False:
        raise ValueError(f"{artifact_id} hysteresis selection accessed OOD data")
    if payload["selection_population"] != "known_modes_only":
        raise ValueError(f"{artifact_id} hysteresis selection is not known-only")
    if payload["selection_unit"] != "leave_one_trajectory_out":
        raise ValueError(f"{artifact_id} hysteresis selection unit mismatch")
    if payload["state_machine_confirmation_semantics"] != _CONFIRMATION_SEMANTICS:
        raise ValueError(f"{artifact_id} state-machine semantics mismatch")
    expected_objective = [
        "false_active_episode_count",
        "false_active_sample_count",
        "false_alert_sample_count",
        "distance_to_predeclared_default",
    ]
    if payload["selection_objective"] != expected_objective:
        raise ValueError(f"{artifact_id} hysteresis selection objective mismatch")
    search = _exact_mapping(
        payload["search_range"],
        _HYSTERESIS_SEARCH_KEYS,
        f"{artifact_id} hysteresis search range",
    )
    selected = _exact_mapping(
        payload["selected"],
        _HYSTERESIS_SELECTED_KEYS,
        f"{artifact_id} selected hysteresis parameters",
    )
    for name in _HYSTERESIS_SEARCH_KEYS:
        values = search[name]
        if (
            isinstance(values, (str, bytes))
            or not isinstance(values, list)
            or not values
            or len(set(values)) != len(values)
        ):
            raise ValueError(f"{artifact_id} search range {name} is invalid")
        if selected[name] not in values:
            raise ValueError(f"{artifact_id} selected {name} is outside its search range")
    config = OODDetectorConfig(
        alpha_on=selected["alpha_on"],  # type: ignore[arg-type]
        alpha_off=selected["alpha_off"],  # type: ignore[arg-type]
        L_on=selected["hold_on_steps"],  # type: ignore[arg-type]
        L_off=selected["hold_off_steps"],  # type: ignore[arg-type]
        variance_floor=selected["variance_floor"],  # type: ignore[arg-type]
    )
    if config.L_on != expected_hold_on_steps:
        raise ValueError(
            f"{artifact_id} must select L_on={expected_hold_on_steps}, "
            f"got {config.L_on}"
        )
    return sha256_file(path), {
        "alpha_on": config.alpha_on,
        "alpha_off": config.alpha_off,
        "L_on": config.L_on,
        "L_off": config.L_off,
        "variance_floor": config.variance_floor,
    }


def _verify_phase4_artifact_manifest(
    directory: Path,
    *,
    artifact_id: str,
    calibration_path: Path,
    selection_path: Path,
) -> str:
    manifest_path = directory / "artifact_manifest.json"
    sidecar_path = directory / "artifact_manifest.sha256"
    manifest = _exact_mapping(
        _strict_json(manifest_path, f"{artifact_id} Phase4 artifact manifest"),
        _PHASE4_MANIFEST_KEYS,
        f"{artifact_id} Phase4 artifact manifest",
    )
    if manifest["schema_version"] != _HYSTERESIS_SCHEMA_VERSION:
        raise ValueError(f"{artifact_id} Phase4 artifact manifest schema mismatch")
    if manifest["scope"] != "all_phase4_artifacts_except_manifest_and_hash_sidecar":
        raise ValueError(f"{artifact_id} Phase4 artifact manifest scope mismatch")
    raw_files = manifest["files"]
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError(f"{artifact_id} Phase4 artifact manifest files are empty")
    files: dict[str, Mapping[str, Any]] = {}
    normalized_files: list[dict[str, object]] = []
    for index, raw_file in enumerate(raw_files):
        record = _exact_mapping(
            raw_file,
            _PHASE4_MANIFEST_FILE_KEYS,
            f"{artifact_id} Phase4 manifest file {index}",
        )
        relative_name = record["path"]
        if not isinstance(relative_name, str):
            raise TypeError("Phase4 manifest file path must be a string")
        relative = Path(relative_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Phase4 artifact manifest contains an unsafe path")
        if relative_name in files:
            raise ValueError("Phase4 artifact manifest contains a duplicate path")
        digest = _sha256(record["sha256"], f"Phase4 hash for {relative_name}")
        size = record["size_bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("Phase4 artifact size must be a non-negative integer")
        normalized = {"path": relative_name, "sha256": digest, "size_bytes": size}
        files[relative_name] = normalized
        normalized_files.append(normalized)
    if _sha256(manifest["artifact_set_sha256"], "artifact_set_sha256") != sha256_json(
        normalized_files
    ):
        raise ValueError(f"{artifact_id} Phase4 artifact-set SHA-256 mismatch")

    expected_paths = {
        "ood_calibration_artifact.json": calibration_path,
        "ood_hysteresis_selection.json": selection_path,
    }
    for relative_name, actual_path in expected_paths.items():
        record = files.get(relative_name)
        if record is None:
            raise ValueError(f"{artifact_id} Phase4 manifest omits {relative_name}")
        if sha256_file(actual_path) != record["sha256"]:
            raise ValueError(
                f"{artifact_id} {relative_name} artifact manifest SHA-256 mismatch"
            )
        if actual_path.stat().st_size != record["size_bytes"]:
            raise ValueError(f"{artifact_id} {relative_name} size mismatch")
    manifest_digest = sha256_file(manifest_path)
    sidecar_digest = sidecar_path.read_text(encoding="ascii").strip()
    if _sha256(sidecar_digest, "artifact_manifest.sha256") != manifest_digest:
        raise ValueError(f"{artifact_id} Phase4 artifact manifest sidecar mismatch")
    return manifest_digest


def _manifest_path(path: Path) -> str:
    repository_root = Path(__file__).resolve().parents[1]
    try:
        return path.relative_to(repository_root).as_posix()
    except ValueError:
        return str(path)


@dataclass(frozen=True, slots=True)
class Phase6LibraryBindingFinalization:
    output_directory: Path
    bindings: Mapping[str, LibraryArtifactBinding]
    binding_paths: Mapping[str, Path]
    finalization_manifest_path: Path
    artifact_hashes_path: Path


def finalize_phase6_library_bindings(
    *,
    binding_inputs_path: str | Path,
    native_mode_library_path: str | Path,
    fixed_k4_mode_library_path: str | Path,
    labeled_mode_library_path: str | Path,
    native_ood_calibration_path: str | Path,
    fixed_k4_ood_calibration_path: str | Path,
    labeled_ood_calibration_path: str | Path,
    native_hysteresis_selection_path: str | Path,
    fixed_k4_hysteresis_selection_path: str | Path,
    labeled_hysteresis_selection_path: str | Path,
    output_directory: str | Path,
) -> Phase6LibraryBindingFinalization:
    """Validate three independent calibrations and freeze runtime bindings."""

    output = _empty_directory(output_directory)
    source_path = Path(binding_inputs_path).expanduser().resolve()
    entries = _load_source_entries(source_path)
    path_pairs = {
        "native_k6_discovered": (
            Path(native_mode_library_path).expanduser().resolve(),
            Path(native_ood_calibration_path).expanduser().resolve(),
            Path(native_hysteresis_selection_path).expanduser().resolve(),
        ),
        "fixed_k4_unlabeled": (
            Path(fixed_k4_mode_library_path).expanduser().resolve(),
            Path(fixed_k4_ood_calibration_path).expanduser().resolve(),
            Path(fixed_k4_hysteresis_selection_path).expanduser().resolve(),
        ),
        "labeled_training_only_k4": (
            Path(labeled_mode_library_path).expanduser().resolve(),
            Path(labeled_ood_calibration_path).expanduser().resolve(),
            Path(labeled_hysteresis_selection_path).expanduser().resolve(),
        ),
    }

    bindings: dict[str, LibraryArtifactBinding] = {}
    binding_payloads: dict[str, dict[str, object]] = {}
    selection_digests: dict[str, str] = {}
    selected_hysteresis: dict[str, dict[str, object]] = {}
    phase4_manifest_digests: dict[str, str] = {}
    for (
        artifact_id,
        protocol,
        component_count,
        expected_hold_on_steps,
        _,
    ) in _EXPECTED_LIBRARIES:
        entry = entries[artifact_id]
        library_path, calibration_path, selection_path = path_pairs[artifact_id]
        if selection_path.parent != calibration_path.parent:
            raise ValueError(
                f"{artifact_id} calibration and hysteresis selection must be colocated"
            )
        phase4_manifest_digests[artifact_id] = _verify_phase4_artifact_manifest(
            calibration_path.parent,
            artifact_id=artifact_id,
            calibration_path=calibration_path,
            selection_path=selection_path,
        )
        library = ModeLibrary.load_json(library_path)
        library_file_digest = sha256_file(library_path)
        library_logical_digest = sha256_json(library.to_dict())
        if library_file_digest != entry["mode_library_file_sha256"]:
            raise ValueError(f"{artifact_id} mode-library file SHA-256 mismatch")
        if library_logical_digest != entry["mode_library_logical_sha256"]:
            raise ValueError(f"{artifact_id} mode-library logical SHA-256 mismatch")
        expected_ids = tuple(range(component_count))
        if tuple(model.component_id for model in library.models) != expected_ids:
            raise ValueError(f"{artifact_id} library component IDs are not ordered")

        calibration_payload = _strict_json(
            calibration_path,
            f"{artifact_id} OOD calibration",
        )
        if not isinstance(calibration_payload, Mapping):
            raise TypeError(f"{artifact_id} OOD calibration must be a mapping")
        calibration = OODCalibrationArtifact.from_dict(calibration_payload)
        if tuple(calibration.known_component_ids) != expected_ids:
            raise ValueError(
                f"{artifact_id} OOD calibration known component IDs are not ordered"
            )
        if tuple(calibration.covered_component_ids) != expected_ids:
            raise ValueError(
                f"{artifact_id} OOD calibration covered component IDs are not ordered"
            )
        if calibration.mode_library_sha256 != library_file_digest:
            raise ValueError(f"{artifact_id} OOD calibration is bound to the wrong library file")
        if calibration.mode_library_logical_sha256 != library_logical_digest:
            raise ValueError(
                f"{artifact_id} OOD calibration is bound to the wrong library content"
            )
        selection_digest, selection_summary = _load_hysteresis_selection(
            selection_path,
            artifact_id=artifact_id,
            expected_hold_on_steps=expected_hold_on_steps,
        )
        selection_digests[artifact_id] = selection_digest
        selected_hysteresis[artifact_id] = selection_summary

        binding = LibraryArtifactBinding(
            artifact_id=artifact_id,
            construction_protocol=protocol,
            component_count=component_count,
            mode_library_file_sha256=library_file_digest,
            mode_library_logical_sha256=library_logical_digest,
            ood_calibration_file_sha256=sha256_file(calibration_path),
            identification_train_dataset_sha256=entry[
                "identification_train_dataset_sha256"
            ],
            identification_validation_dataset_sha256=entry[
                "identification_validation_dataset_sha256"
            ],
            runtime_label_access=entry["runtime_label_access"],
        )
        binding.validate_files(library_path, calibration_path)
        binding_payload = binding.to_dict()
        _reject_runtime_placeholders(binding_payload)
        bindings[artifact_id] = binding
        binding_payloads[artifact_id] = binding_payload

    binding_paths: dict[str, Path] = {}
    manifest_rows: list[dict[str, object]] = []
    for artifact_id, _, component_count, _, filename in _EXPECTED_LIBRARIES:
        destination = output / filename
        _write_json(destination, binding_payloads[artifact_id])
        binding_paths[artifact_id] = destination
        manifest_rows.append(
            {
                "artifact_id": artifact_id,
                "binding_file": filename,
                "binding_file_sha256": sha256_file(destination),
                "mode_library_path": _manifest_path(path_pairs[artifact_id][0]),
                "ood_calibration_path": _manifest_path(path_pairs[artifact_id][1]),
                "ood_hysteresis_selection_path": _manifest_path(
                    path_pairs[artifact_id][2]
                ),
                "phase4_artifact_manifest_path": _manifest_path(
                    path_pairs[artifact_id][1].parent / "artifact_manifest.json"
                ),
                "mode_library_file_sha256": bindings[
                    artifact_id
                ].mode_library_file_sha256,
                "ood_calibration_file_sha256": bindings[
                    artifact_id
                ].ood_calibration_file_sha256,
                "ood_hysteresis_selection_file_sha256": selection_digests[
                    artifact_id
                ],
                "phase4_artifact_manifest_file_sha256": (
                    phase4_manifest_digests[artifact_id]
                ),
                "selected_hysteresis": selected_hysteresis[artifact_id],
                "ordered_component_ids": list(range(component_count)),
            }
        )

    finalization_manifest_path = output / "finalization_manifest.json"
    finalization_manifest = {
        "schema_version": FINALIZATION_SCHEMA_VERSION,
        "scope": "three_runtime_library_calibration_bindings",
        "source_binding_inputs_file_sha256": sha256_file(source_path),
        "runtime_label_access": "none",
        "runtime_selected_hysteresis": True,
        "placeholder_values_present": False,
        "bindings": manifest_rows,
    }
    _reject_runtime_placeholders(finalization_manifest)
    _write_json(finalization_manifest_path, finalization_manifest)
    artifact_hashes_path = _write_artifact_hashes(output)
    return Phase6LibraryBindingFinalization(
        output_directory=output,
        bindings=MappingProxyType(bindings),
        binding_paths=MappingProxyType(binding_paths),
        finalization_manifest_path=finalization_manifest_path,
        artifact_hashes_path=artifact_hashes_path,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate three independently calibrated Phase-6 libraries and "
            "write strict runtime LibraryArtifactBinding JSON files."
        )
    )
    parser.add_argument(
        "--binding-inputs",
        type=Path,
        default=Path(
            "artifacts/phase6_library_ablations/provenance/library_binding_inputs.json"
        ),
    )
    parser.add_argument(
        "--native-library",
        type=Path,
        default=Path("artifacts/mode_discovery/mode_library.json"),
    )
    parser.add_argument(
        "--fixed-k4-library",
        type=Path,
        default=Path("artifacts/phase6_library_ablations/fixed_k4_unlabeled/mode_library.json"),
    )
    parser.add_argument(
        "--labeled-library",
        type=Path,
        default=Path(
            "artifacts/phase6_library_ablations/labeled_training_library/runtime/mode_library.json"
        ),
    )
    parser.add_argument(
        "--native-calibration",
        type=Path,
        default=Path("artifacts/online_diagnosis/ood_calibration_artifact.json"),
    )
    parser.add_argument(
        "--fixed-k4-calibration",
        type=Path,
        default=Path(
            "artifacts/online_diagnosis_fixed_k4/ood_calibration_artifact.json"
        ),
    )
    parser.add_argument(
        "--labeled-calibration",
        type=Path,
        default=Path(
            "artifacts/online_diagnosis_labeled/ood_calibration_artifact.json"
        ),
    )
    parser.add_argument(
        "--native-hysteresis-selection",
        type=Path,
        default=Path("artifacts/online_diagnosis/ood_hysteresis_selection.json"),
    )
    parser.add_argument(
        "--fixed-k4-hysteresis-selection",
        type=Path,
        default=Path(
            "artifacts/online_diagnosis_fixed_k4/ood_hysteresis_selection.json"
        ),
    )
    parser.add_argument(
        "--labeled-hysteresis-selection",
        type=Path,
        default=Path(
            "artifacts/online_diagnosis_labeled/ood_hysteresis_selection.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/phase6_library_bindings"),
        help="new or empty output directory; existing content is never replaced",
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    result = finalize_phase6_library_bindings(
        binding_inputs_path=arguments.binding_inputs,
        native_mode_library_path=arguments.native_library,
        fixed_k4_mode_library_path=arguments.fixed_k4_library,
        labeled_mode_library_path=arguments.labeled_library,
        native_ood_calibration_path=arguments.native_calibration,
        fixed_k4_ood_calibration_path=arguments.fixed_k4_calibration,
        labeled_ood_calibration_path=arguments.labeled_calibration,
        native_hysteresis_selection_path=arguments.native_hysteresis_selection,
        fixed_k4_hysteresis_selection_path=(
            arguments.fixed_k4_hysteresis_selection
        ),
        labeled_hysteresis_selection_path=(
            arguments.labeled_hysteresis_selection
        ),
        output_directory=arguments.output_dir,
    )
    print(
        json.dumps(
            {
                "artifact_hashes_file_sha256": sha256_file(
                    result.artifact_hashes_path
                ),
                "binding_file_sha256": {
                    artifact_id: sha256_file(path)
                    for artifact_id, path in result.binding_paths.items()
                },
                "finalization_manifest_file_sha256": sha256_file(
                    result.finalization_manifest_path
                ),
                "output_directory": str(result.output_directory),
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
