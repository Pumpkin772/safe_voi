"""Phase-6 fixed-reference and offline-library ablation construction.

The main proposed controller always uses the frozen label-free K=6 library.
This module builds two *separate* ablation libraries:

* a public-signal-only discovery run with ``K`` pre-registered to four; and
* a training-label-informed K=4 upper-reference library.

The latter keeps semantic labels in an evaluation-only manifest.  Its runtime
``mode_library.json`` contains contiguous anonymous component identifiers and
no mode names.  Nothing in this module is imported by the simulator or by the
production proposed-controller factory.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
from numpy.typing import NDArray
import pandas as pd

from d5freq.controllers.final_arx_mpc import (
    FixedReferenceSelectionArtifact,
    ReferenceCandidateScore,
)
from d5freq.data import (
    IdentificationTrajectory,
    PrivateTrajectoryMetadata,
    load_public_identification_data,
)
from d5freq.evaluation.baselines.oracle import OracleARXArtifact, OracleARXRecord
from d5freq.identification.arx import validate_arx_multistep
from d5freq.identification.mode_discovery import (
    FeatureStandardizer,
    ModeValidationMetrics,
    evaluate_assigned_validation_episodes,
    fit_local_episode_models,
    refit_global_cluster_models,
    select_gmm_by_bic,
)
from d5freq.identification.model_library import (
    ARXModeModel,
    ModeLibrary,
    discovery_metadata_from_selection,
    mode_library_from_discovery,
)
from d5freq.identification.offline_pipeline import (
    LabelFreeDiscoveryRun,
    OfflinePipelineConfig,
    default_arx_fitter_api,
    frequency_errors_to_rocof_errors,
    offline_pipeline_config_from_base_config,
    propagate_grid_frequency_errors,
    run_label_free_mode_discovery,
)
from d5freq.models.grid_frequency import GridFrequencyModel
from d5freq.utils.config import config_sha256, load_yaml
from d5freq.utils.hashing import sha256_file, sha256_json


FloatArray = NDArray[np.float64]
LABELED_LIBRARY_SCHEMA_VERSION = "d5freq.labeled-training-library.v1"
FIXED_K4_SCHEMA_VERSION = "d5freq.fixed-k4-unlabeled-library.v1"
FIXED_K4_EVALUATION_MAPPING_SCHEMA_VERSION = (
    "d5freq.fixed-k4-component-evaluation-mapping.v1"
)
FIXED_REFERENCE_CRITERION = "validation_observed_symmetric_power_envelope_pu"
IDENTIFICATION_SUBSET_HASH_SCHEMA_VERSION = "d5freq.identification_subset_hash.v1"
IDENTIFICATION_SUBSET_MANIFEST_SCHEMA_VERSION = (
    "d5freq.identification_subset_hash_manifest.v1"
)
PHASE6_LIBRARY_ABLATION_BUILD_SCHEMA_VERSION = (
    "d5freq.phase6-library-ablation-build.v1"
)
_ANONYMOUS_ID_DOMAIN = "d5freq.phase6.labeled-library.anonymous-id.v1"
_FIXED_K4_MAPPING_RECORD_KEYS = frozenset(
    {
        "component_id",
        "selected_mode_name_eval_only",
        "training_episode_count",
        "majority_episode_count",
        "purity",
        "counts_by_mode_eval_only",
    }
)
_FIXED_K4_MAPPING_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "scope",
        "label_access",
        "assignment_split",
        "mapping_method",
        "tie_break_rule",
        "runtime_consumable",
        "validation_label_access",
        "test_label_access",
        "component_count",
        "mode_library_file_sha256",
        "mode_library_logical_sha256",
        "cluster_assignments_file_sha256",
        "private_training_projection_sha256",
        "components",
    }
)
_PHASE6_SOURCE_PATHS: tuple[str, ...] = (
    "scripts/phase6_build_library_ablations.py",
    "src/d5freq/evaluation/library_ablations.py",
    "src/d5freq/controllers/final_arx_mpc.py",
    "src/d5freq/identification/arx.py",
    "src/d5freq/identification/mode_discovery.py",
    "src/d5freq/identification/model_library.py",
    "src/d5freq/identification/offline_pipeline.py",
)


def _strict_json(path: Path) -> object:
    def reject_nonfinite(token: str) -> None:
        raise ValueError(f"non-standard JSON number {token!r} is forbidden")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_nonfinite)


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


def _empty_directory(path: str | Path) -> Path:
    output = Path(path).expanduser().resolve()
    if output.exists() and not output.is_dir():
        raise NotADirectoryError(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    return output


def _sha256_digest(value: object, name: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return normalized


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


def _artifact_hashes(output: Path) -> dict[str, str]:
    excluded = (output / "artifact_hashes.json").resolve()
    return {
        path.relative_to(output).as_posix(): sha256_file(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.resolve() != excluded
    }


def _write_artifact_hashes(output: Path) -> Path:
    destination = output / "artifact_hashes.json"
    _write_json(
        destination,
        {
            "schema_version": 1,
            "hash_algorithm": "sha256",
            "scope": "all_files_except_this_manifest",
            "sha256": _artifact_hashes(output),
        },
    )
    return destination


@dataclass(frozen=True, slots=True)
class IdentificationSubsetDigest:
    """Expanded audit evidence plus the canonical binding digest for a split.

    Each input digest is the exact Parquet *file-byte* SHA-256 recorded by the
    public split manifest.  Sorting removes path/enumeration-order dependence,
    but the result remains intentionally sensitive to Parquet compression,
    row-group organization, metadata, and any other byte-layout change.
    """

    split: str
    dataset_sha256: str
    trajectory_rows: tuple[Mapping[str, str], ...]

    def __post_init__(self) -> None:
        if self.split not in {"train", "validation"}:
            raise ValueError("subset split must be 'train' or 'validation'")
        object.__setattr__(
            self,
            "dataset_sha256",
            _sha256_digest(self.dataset_sha256, "subset dataset_sha256"),
        )
        rows = tuple(dict(row) for row in self.trajectory_rows)
        if not rows:
            raise ValueError("identification subset must not be empty")
        expected_keys = {"trajectory_id", "sha256"}
        if any(set(row) != expected_keys for row in rows):
            raise ValueError("identification subset rows have an invalid shape")
        identifiers = tuple(str(row["trajectory_id"]) for row in rows)
        if identifiers != tuple(sorted(identifiers)) or len(set(identifiers)) != len(rows):
            raise ValueError("identification subset IDs must be unique and sorted")
        digests = tuple(
            _sha256_digest(row["sha256"], "trajectory SHA-256") for row in rows
        )
        if len(set(digests)) != len(digests):
            raise ValueError("identification subset contains duplicate trajectory hashes")
        object.__setattr__(self, "trajectory_rows", rows)

    @property
    def canonical_hash_input(self) -> dict[str, object]:
        """Exact payload mandated by ``LibraryArtifactBinding``."""

        return {
            "schema_version": IDENTIFICATION_SUBSET_HASH_SCHEMA_VERSION,
            "split": self.split,
            "trajectory_sha256": sorted(
                row["sha256"] for row in self.trajectory_rows
            ),
        }

    @property
    def canonical_sha256(self) -> str:
        return sha256_json(self.canonical_hash_input)

    def to_dict(self) -> dict[str, object]:
        return {
            "split": self.split,
            "dataset_sha256": self.dataset_sha256,
            "trajectory_count": len(self.trajectory_rows),
            "canonical_sha256": self.canonical_sha256,
            "canonical_hash_input": self.canonical_hash_input,
            "trajectory_rows": [dict(row) for row in self.trajectory_rows],
        }


def identification_subset_digests(
    public_data_directory: str | Path,
) -> Mapping[str, IdentificationSubsetDigest]:
    """Derive train/validation binding hashes from the verified public manifest."""

    public = Path(public_data_directory).expanduser().resolve()
    public_manifest = _strict_json(public / "public_manifest.json")
    if not isinstance(public_manifest, Mapping):
        raise TypeError("public manifest must be a JSON object")
    dataset_digest = _sha256_digest(
        public_manifest.get("dataset_sha256"), "public dataset SHA-256"
    )
    split_frame = pd.read_csv(public / "split_manifest.csv", dtype=str)
    expected_columns = ["trajectory_id", "split", "sha256"]
    if split_frame.columns.tolist() != expected_columns:
        raise ValueError("public split manifest columns do not match the frozen schema")
    result: dict[str, IdentificationSubsetDigest] = {}
    for split in ("train", "validation"):
        selected = split_frame.loc[
            split_frame["split"] == split,
            ["trajectory_id", "sha256"],
        ].sort_values("trajectory_id", kind="stable")
        rows = tuple(selected.to_dict(orient="records"))
        result[split] = IdentificationSubsetDigest(
            split=split,
            dataset_sha256=dataset_digest,
            trajectory_rows=rows,
        )
    return MappingProxyType(result)


def save_identification_subset_hash_manifest(
    subsets: Mapping[str, IdentificationSubsetDigest],
    path: str | Path,
) -> Path:
    """Persist expanded hash inputs used by all three library bindings."""

    if set(subsets) != {"train", "validation"} or not all(
        isinstance(value, IdentificationSubsetDigest) for value in subsets.values()
    ):
        raise ValueError("subsets must contain train and validation digests")
    destination = Path(path).expanduser().resolve()
    _write_json(
        destination,
        {
            "schema_version": IDENTIFICATION_SUBSET_MANIFEST_SCHEMA_VERSION,
            "hash_algorithm": "sha256",
            "binding_definition": (
                "sha256_json(canonical_hash_input); inputs are exact Parquet "
                "file-byte SHA-256 values from split_manifest.csv; sorting makes "
                "the digest path/enumeration-order independent but it remains "
                "Parquet byte-layout sensitive"
            ),
            "source_digest_kind": "exact_parquet_file_bytes_sha256",
            "subsets": {
                split: subsets[split].to_dict()
                for split in ("train", "validation")
            },
        },
    )
    return destination


def _metadata_by_id(
    metadata: Sequence[PrivateTrajectoryMetadata],
) -> dict[str, PrivateTrajectoryMetadata]:
    rows = tuple(metadata)
    if not rows or not all(isinstance(row, PrivateTrajectoryMetadata) for row in rows):
        raise TypeError("metadata must contain PrivateTrajectoryMetadata records")
    result = {row.trajectory_id: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("private metadata contains duplicate trajectory IDs")
    return result


def private_training_projection_sha256(
    metadata: Sequence[PrivateTrajectoryMetadata],
) -> str:
    """Hash an ordered, training-only private metadata projection."""

    rows = tuple(metadata)
    by_id = _metadata_by_id(rows)
    if any(record.split != "train" for record in by_id.values()):
        raise ValueError("private projection must contain training rows only")
    return sha256_json(
        [asdict(by_id[trajectory_id]) for trajectory_id in sorted(by_id)]
    )


def load_private_metadata_evaluation_only(
    private_directory: str | Path,
    public_manifest_path: str | Path,
) -> tuple[PrivateTrajectoryMetadata, ...]:
    """Load label metadata after verifying its private/public provenance.

    The deliberately explicit ``evaluation_only`` name prevents this loader
    from being mistaken for a controller-side data source.
    """

    private = Path(private_directory).expanduser().resolve()
    public_manifest = Path(public_manifest_path).expanduser().resolve()
    private_manifest_path = private / "private_manifest.json"
    metadata_path = private / "evaluation_metadata.json"
    private_manifest = _strict_json(private_manifest_path)
    if not isinstance(private_manifest, dict):
        raise TypeError("private manifest must be a JSON object")
    if private_manifest.get("truth_access") != "evaluation_only":
        raise ValueError("private manifest must declare evaluation_only truth access")
    hashes = private_manifest.get("hashes")
    if not isinstance(hashes, Mapping):
        raise ValueError("private manifest must contain a hash mapping")
    if sha256_file(metadata_path) != hashes.get("evaluation_metadata_sha256"):
        raise ValueError("private evaluation metadata SHA-256 mismatch")
    if sha256_file(public_manifest) != hashes.get("public_manifest_sha256"):
        raise ValueError("private/public manifest provenance mismatch")
    payload = _strict_json(metadata_path)
    if not isinstance(payload, list) or not payload:
        raise ValueError("private evaluation metadata must be a non-empty JSON array")
    records = tuple(PrivateTrajectoryMetadata(**dict(item)) for item in payload)
    _metadata_by_id(records)
    return records


@dataclass(frozen=True, slots=True)
class FixedK4SemanticMajorityRecord:
    """Evaluation-only semantic summary for one anonymous K4 component."""

    component_id: int
    selected_mode_name_eval_only: str
    training_episode_count: int
    majority_episode_count: int
    purity: float
    counts_by_mode_eval_only: Mapping[str, int]

    def __post_init__(self) -> None:
        if (
            isinstance(self.component_id, (bool, np.bool_))
            or not isinstance(self.component_id, (int, np.integer))
            or int(self.component_id) < 0
        ):
            raise ValueError("component_id must be a non-negative integer")
        selected = str(self.selected_mode_name_eval_only).strip()
        if not selected:
            raise ValueError("selected_mode_name_eval_only must not be empty")
        counts = dict(self.counts_by_mode_eval_only)
        if not counts or any(
            not isinstance(name, str) or not name.strip() for name in counts
        ):
            raise ValueError("counts_by_mode_eval_only needs non-empty semantic names")
        if any(
            isinstance(count, (bool, np.bool_))
            or not isinstance(count, (int, np.integer))
            or int(count) < 0
            for count in counts.values()
        ):
            raise ValueError("semantic counts must be non-negative integers")
        normalized_counts = {
            name.strip(): int(count) for name, count in sorted(counts.items())
        }
        if len(normalized_counts) != len(counts):
            raise ValueError("semantic names must remain unique after trimming")
        total = sum(normalized_counts.values())
        if total <= 0 or self.training_episode_count != total:
            raise ValueError("training_episode_count must equal the semantic counts")
        maximum = max(normalized_counts.values())
        if self.majority_episode_count != maximum:
            raise ValueError("majority_episode_count must equal the largest count")
        deterministic_winner = min(
            name for name, count in normalized_counts.items() if count == maximum
        )
        if selected != deterministic_winner:
            raise ValueError("selected semantic name is not the deterministic majority")
        purity = float(self.purity)
        if not math.isfinite(purity) or not math.isclose(
            purity,
            maximum / total,
            rel_tol=0.0,
            abs_tol=1.0e-15,
        ):
            raise ValueError("purity must equal majority_episode_count / total")
        object.__setattr__(self, "component_id", int(self.component_id))
        object.__setattr__(self, "selected_mode_name_eval_only", selected)
        object.__setattr__(self, "training_episode_count", total)
        object.__setattr__(self, "majority_episode_count", maximum)
        object.__setattr__(self, "purity", purity)
        object.__setattr__(
            self,
            "counts_by_mode_eval_only",
            MappingProxyType(normalized_counts),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "selected_mode_name_eval_only": self.selected_mode_name_eval_only,
            "training_episode_count": self.training_episode_count,
            "majority_episode_count": self.majority_episode_count,
            "purity": self.purity,
            "counts_by_mode_eval_only": dict(self.counts_by_mode_eval_only),
        }

    @classmethod
    def from_dict(cls, value: object) -> "FixedK4SemanticMajorityRecord":
        mapping = _exact_mapping(
            value,
            _FIXED_K4_MAPPING_RECORD_KEYS,
            "fixed-K4 semantic majority record",
        )
        counts = mapping["counts_by_mode_eval_only"]
        if not isinstance(counts, Mapping):
            raise TypeError("counts_by_mode_eval_only must be a mapping")
        return cls(
            component_id=mapping["component_id"],  # type: ignore[arg-type]
            selected_mode_name_eval_only=mapping[
                "selected_mode_name_eval_only"
            ],  # type: ignore[arg-type]
            training_episode_count=mapping[
                "training_episode_count"
            ],  # type: ignore[arg-type]
            majority_episode_count=mapping[
                "majority_episode_count"
            ],  # type: ignore[arg-type]
            purity=mapping["purity"],  # type: ignore[arg-type]
            counts_by_mode_eval_only=counts,  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class FixedK4EvaluationMappingArtifact:
    """Private-training-only interpretation kept outside runtime artifacts.

    Multiple components may select the same semantic class.  This is an
    evaluator report only; it is neither a relabeling of native components nor
    an admissible input to online diagnosis or OOD calibration.
    """

    component_count: int
    mode_library_file_sha256: str
    mode_library_logical_sha256: str
    cluster_assignments_file_sha256: str
    private_training_projection_sha256: str
    components: tuple[FixedK4SemanticMajorityRecord, ...]
    schema_version: str = FIXED_K4_EVALUATION_MAPPING_SCHEMA_VERSION
    scope: str = "evaluation_only"
    label_access: str = "private_identification_train_only"
    assignment_split: str = "identification_train"
    mapping_method: str = "per_anonymous_component_majority"
    tie_break_rule: str = "lexicographically_smallest_mode_name"
    runtime_consumable: bool = False
    validation_label_access: bool = False
    test_label_access: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != FIXED_K4_EVALUATION_MAPPING_SCHEMA_VERSION:
            raise ValueError("invalid fixed-K4 evaluation mapping schema version")
        required_constants = {
            "scope": (self.scope, "evaluation_only"),
            "label_access": (
                self.label_access,
                "private_identification_train_only",
            ),
            "assignment_split": (self.assignment_split, "identification_train"),
            "mapping_method": (
                self.mapping_method,
                "per_anonymous_component_majority",
            ),
            "tie_break_rule": (
                self.tie_break_rule,
                "lexicographically_smallest_mode_name",
            ),
        }
        for name, (actual, expected) in required_constants.items():
            if actual != expected:
                raise ValueError(f"{name} must equal {expected!r}")
        if self.runtime_consumable is not False:
            raise ValueError("evaluation mapping must not be runtime consumable")
        if self.validation_label_access is not False or self.test_label_access is not False:
            raise ValueError("evaluation mapping cannot access validation/test labels")
        if (
            isinstance(self.component_count, (bool, np.bool_))
            or not isinstance(self.component_count, (int, np.integer))
            or int(self.component_count) != 4
        ):
            raise ValueError("fixed-K4 evaluation mapping requires component_count=4")
        records = tuple(self.components)
        if not all(isinstance(item, FixedK4SemanticMajorityRecord) for item in records):
            raise TypeError("components must contain semantic majority records")
        if tuple(item.component_id for item in records) != tuple(range(4)):
            raise ValueError("components must cover ordered anonymous IDs 0..3")
        semantic_universes = {
            tuple(item.counts_by_mode_eval_only) for item in records
        }
        if len(semantic_universes) != 1:
            raise ValueError("all components must report the same semantic universe")
        object.__setattr__(self, "component_count", 4)
        object.__setattr__(self, "components", records)
        for name in (
            "mode_library_file_sha256",
            "mode_library_logical_sha256",
            "cluster_assignments_file_sha256",
            "private_training_projection_sha256",
        ):
            object.__setattr__(
                self,
                name,
                _sha256_digest(getattr(self, name), name),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scope": self.scope,
            "label_access": self.label_access,
            "assignment_split": self.assignment_split,
            "mapping_method": self.mapping_method,
            "tie_break_rule": self.tie_break_rule,
            "runtime_consumable": self.runtime_consumable,
            "validation_label_access": self.validation_label_access,
            "test_label_access": self.test_label_access,
            "component_count": self.component_count,
            "mode_library_file_sha256": self.mode_library_file_sha256,
            "mode_library_logical_sha256": self.mode_library_logical_sha256,
            "cluster_assignments_file_sha256": (
                self.cluster_assignments_file_sha256
            ),
            "private_training_projection_sha256": (
                self.private_training_projection_sha256
            ),
            "components": [item.to_dict() for item in self.components],
        }

    @classmethod
    def from_dict(cls, value: object) -> "FixedK4EvaluationMappingArtifact":
        mapping = _exact_mapping(
            value,
            _FIXED_K4_MAPPING_TOP_LEVEL_KEYS,
            "fixed-K4 evaluation mapping artifact",
        )
        records = mapping["components"]
        if not isinstance(records, list):
            raise TypeError("components must be a JSON array")
        return cls(
            **{
                key: mapping[key]
                for key in _FIXED_K4_MAPPING_TOP_LEVEL_KEYS
                if key != "components"
            },  # type: ignore[arg-type]
            components=tuple(
                FixedK4SemanticMajorityRecord.from_dict(item) for item in records
            ),
        )

    @classmethod
    def load_json(cls, path: str | Path) -> "FixedK4EvaluationMappingArtifact":
        return cls.from_dict(_strict_json(Path(path).expanduser().resolve()))


def anonymous_component_mapping(
    class_names: Sequence[str],
) -> tuple[dict[str, int], dict[int, str]]:
    """Assign numeric IDs by a domain-separated hash, not semantic order."""

    names = tuple(str(value).strip() for value in class_names)
    if not names or any(not value for value in names) or len(set(names)) != len(names):
        raise ValueError("class_names must be non-empty and unique")

    def key(name: str) -> tuple[str, str]:
        digest = hashlib.sha256(f"{_ANONYMOUS_ID_DOMAIN}:{name}".encode()).hexdigest()
        return digest, name

    ordered = tuple(sorted(names, key=key))
    forward = {name: component for component, name in enumerate(ordered)}
    reverse = {component: name for name, component in forward.items()}
    return forward, reverse


def _trajectory_assignments_from_training_labels(
    trajectories: Sequence[IdentificationTrajectory],
    metadata: Mapping[str, PrivateTrajectoryMetadata],
    class_to_component: Mapping[str, int],
    *,
    expected_split: str,
) -> NDArray[np.int64]:
    values: list[int] = []
    for trajectory in trajectories:
        record = metadata.get(trajectory.trajectory_id)
        if record is None:
            raise ValueError("a public trajectory has no private metadata join row")
        if record.split != expected_split:
            raise ValueError("private metadata split differs from the public loader split")
        if record.mode_name_eval_only not in class_to_component:
            raise ValueError("private metadata contains a non-registered known class")
        values.append(int(class_to_component[record.mode_name_eval_only]))
    assignments = np.asarray(values, dtype=np.int64)
    expected = np.arange(len(class_to_component), dtype=np.int64)
    if not np.array_equal(np.unique(assignments), expected):
        raise ValueError(f"{expected_split} does not cover every anonymous component")
    return assignments


def assign_validation_by_training_feature_centroids(
    standardized_training_features: NDArray[np.float64],
    training_component_ids: NDArray[np.int64],
    standardized_validation_features: NDArray[np.float64],
    *,
    component_count: int,
) -> NDArray[np.int64]:
    """Assign validation episodes using training labels and public features.

    Each anonymous component centroid is fit using *training* labels only.
    Validation rows are then assigned by Euclidean distance in the frozen,
    standardized local-ARX feature space.  ``numpy.argmin`` supplies the
    preregistered lowest-component-ID tie break.  No validation/test label is
    an input to this function.
    """

    if isinstance(component_count, bool) or not isinstance(component_count, int):
        raise TypeError("component_count must be an integer")
    if component_count < 1:
        raise ValueError("component_count must be positive")
    training = np.asarray(standardized_training_features, dtype=np.float64)
    validation = np.asarray(standardized_validation_features, dtype=np.float64)
    components = np.asarray(training_component_ids)
    if training.ndim != 2 or validation.ndim != 2:
        raise ValueError("training and validation features must be matrices")
    if training.shape[1] != validation.shape[1]:
        raise ValueError("training and validation feature dimensions differ")
    if validation.shape[0] == 0 or training.shape[0] == 0:
        raise ValueError("training and validation features must be non-empty")
    if not np.all(np.isfinite(training)) or not np.all(np.isfinite(validation)):
        raise ValueError("features must be finite")
    if (
        np.iscomplexobj(components)
        or not np.issubdtype(components.dtype, np.integer)
        or components.shape != (training.shape[0],)
    ):
        raise TypeError("training_component_ids must be one integer per row")
    components = np.asarray(components, dtype=np.int64)
    if np.any(components < 0) or np.any(components >= component_count):
        raise ValueError("training_component_ids contain an invalid component")
    counts = np.bincount(components, minlength=component_count)
    if np.any(counts == 0):
        raise ValueError("every anonymous component needs training evidence")
    centroids = np.vstack(
        [training[components == component].mean(axis=0) for component in range(component_count)]
    )
    squared_distances = np.sum(
        (validation[:, None, :] - centroids[None, :, :]) ** 2,
        axis=2,
    )
    assignments = np.argmin(squared_distances, axis=1).astype(np.int64)
    assignments.setflags(write=False)
    return assignments


def _validation_error_blocks(
    trajectories: Sequence[IdentificationTrajectory],
    assignments: NDArray[np.int64],
    library_models: Sequence[object],
    *,
    horizon: int,
) -> dict[int, FloatArray]:
    blocks: dict[int, list[FloatArray]] = {
        int(getattr(model, "component_id")): [] for model in library_models
    }
    models = {int(getattr(model, "component_id")): model for model in library_models}
    for trajectory, component in zip(trajectories, assignments.tolist(), strict=True):
        model = models[int(component)]
        validation = validate_arx_multistep(
            getattr(model, "theta"),
            trajectory.p_ibr_pu,
            trajectory.u_ibr_pu,
            trajectory.omega_pu,
            horizon=horizon,
        )
        blocks[int(component)].append(np.asarray(validation.errors, dtype=np.float64))
    if any(not values for values in blocks.values()):
        raise ValueError("validation labels leave a component without error evidence")
    return {component: np.vstack(values) for component, values in blocks.items()}


def _one_hot_assignments_frame(
    training: Sequence[IdentificationTrajectory],
    validation: Sequence[IdentificationTrajectory],
    train_assignments: NDArray[np.int64],
    validation_assignments: NDArray[np.int64],
    *,
    component_count: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for split, trajectories, assignments in (
        ("train", training, train_assignments),
        ("validation", validation, validation_assignments),
    ):
        for trajectory, component in zip(trajectories, assignments.tolist(), strict=True):
            row: dict[str, object] = {
                "trajectory_id": trajectory.trajectory_id,
                "dataset_split": split,
                "component_id": int(component),
            }
            for index in range(component_count):
                row[f"component_probability_{index}"] = float(index == component)
            rows.append(row)
    return pd.DataFrame(rows)


def _labeled_metrics_frame(
    models: Sequence[object],
    metrics: Sequence[ModeValidationMetrics],
) -> pd.DataFrame:
    by_component = {metric.component_id: metric for metric in metrics}
    rows: list[dict[str, object]] = []
    for model in models:
        component = int(getattr(model, "component_id"))
        metric = by_component[component]
        capability = getattr(model, "capability")
        rows.append(
            {
                "component_id": component,
                "training_episode_count": int(getattr(model, "training_episode_count")),
                "training_sample_count": int(getattr(model, "training_sample_count")),
                "residual_variance": float(getattr(model, "residual_variance")),
                "condition_number": float(getattr(model, "condition_number")),
                "validation_episode_count": metric.validation_episode_count,
                "validation_prediction_origin_count": metric.prediction_origin_count,
                "validation_rmse_mean_over_leads_pu": float(np.mean(metric.rmse_by_lead)),
                "validation_mae_mean_over_leads_pu": float(np.mean(metric.mae_by_lead)),
                "power_bound_coverage": metric.power_bound_coverage,
                "directional_rate_bound_coverage": metric.directional_rate_bound_coverage,
                "p_output_min_pu": float(capability.p_output_min_pu),
                "p_output_max_pu": float(capability.p_output_max_pu),
                "ramp_down_pu_per_s": float(capability.ramp_down_pu_per_s),
                "ramp_up_pu_per_s": float(capability.ramp_up_pu_per_s),
            }
        )
    return pd.DataFrame(rows)


def _quantile_frame(
    metrics: Sequence[ModeValidationMetrics],
    frequency_errors: Mapping[int, FloatArray],
    rocof_errors: Mapping[int, FloatArray],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for metric in metrics:
        component = metric.component_id
        frequency = np.asarray(frequency_errors[component], dtype=np.float64)
        rocof = np.asarray(rocof_errors[component], dtype=np.float64)
        for lead in range(metric.rmse_by_lead.size):
            rows.append(
                {
                    "component_id": component,
                    "lead": lead + 1,
                    "power_error_q95_pu": float(metric.abs_error_quantile_95_by_lead[lead]),
                    "frequency_error_q95_hz": float(
                        np.quantile(np.abs(frequency[:, lead]), 0.95)
                    ),
                    "rocof_error_q95_hz_per_s": float(
                        np.quantile(np.abs(rocof[:, lead]), 0.95)
                    ),
                }
            )
    return pd.DataFrame(rows)


@dataclass(frozen=True, slots=True)
class LabeledTrainingLibraryRun:
    output_directory: Path
    mode_library: ModeLibrary
    mode_library_file_sha256: str
    mode_library_logical_sha256: str
    train_assignments: NDArray[np.int64]
    validation_assignments: NDArray[np.int64]
    component_to_class_eval_only: Mapping[int, str]


@dataclass(frozen=True, slots=True)
class OracleARXBuild:
    artifact: OracleARXArtifact
    path: Path
    file_sha256: str
    logical_sha256: str


def build_oracle_arx_artifact(
    labeled_run: LabeledTrainingLibraryRun,
    *,
    identification_train_dataset_sha256: str,
    training_config_sha256: str,
    output_path: str | Path,
) -> OracleARXBuild:
    """Create B4's semantic evaluator route from supervised pooled ARX fits."""

    if not isinstance(labeled_run, LabeledTrainingLibraryRun):
        raise TypeError("labeled_run must be a LabeledTrainingLibraryRun")
    train_digest = _sha256_digest(
        identification_train_dataset_sha256,
        "identification_train_dataset_sha256",
    )
    config_digest = _sha256_digest(training_config_sha256, "training_config_sha256")
    destination = Path(output_path).expanduser().resolve()
    if "evaluation_only" not in destination.parts:
        raise ValueError("Oracle ARX artifact must be stored under evaluation_only")
    models_by_component = {
        model.component_id: model for model in labeled_run.mode_library.models
    }
    mapping = dict(labeled_run.component_to_class_eval_only)
    expected = set(range(len(models_by_component)))
    if set(models_by_component) != expected or set(mapping) != expected:
        raise ValueError("labeled library/mapping must cover contiguous components")
    records = tuple(
        OracleARXRecord(
            evaluation_mode_key=mapping[component],
            arx_model=replace(models_by_component[component], component_id=0),
        )
        for component in range(len(models_by_component))
    )
    artifact = OracleARXArtifact(
        training_dataset_sha256=train_digest,
        config_sha256=config_digest,
        models=records,
    )
    _write_json(destination, artifact.to_dict())
    return OracleARXBuild(
        artifact=artifact,
        path=destination,
        file_sha256=sha256_file(destination),
        logical_sha256=sha256_json(artifact.to_dict()),
    )


def build_labeled_training_library(
    training: Sequence[IdentificationTrajectory],
    validation: Sequence[IdentificationTrajectory],
    private_training_metadata_eval_only: Sequence[PrivateTrajectoryMetadata],
    *,
    config: OfflinePipelineConfig,
    output_directory: str | Path,
    public_dataset_sha256: str,
    private_metadata_file_sha256: str,
    expected_private_training_projection_sha256: str,
) -> LabeledTrainingLibraryRun:
    """Fit K=4 ARX models using labels from identification training only.

    The private argument must be an exact projection of the training split;
    passing validation, calibration, or test metadata is rejected before any
    ARX fit.  Validation component assignment uses only frozen training
    centroids and public validation signals.
    """

    if not isinstance(config, OfflinePipelineConfig):
        raise TypeError("config must be an OfflinePipelineConfig")
    train = tuple(training)
    valid = tuple(validation)
    if not train or not valid:
        raise ValueError("training and validation trajectories must be non-empty")
    if set(item.trajectory_id for item in train) & set(item.trajectory_id for item in valid):
        raise ValueError("training and validation trajectory IDs must be disjoint")
    public_dataset_digest = _sha256_digest(
        public_dataset_sha256, "public_dataset_sha256"
    )
    private_metadata_digest = _sha256_digest(
        private_metadata_file_sha256, "private_metadata_file_sha256"
    )
    private_projection_digest = _sha256_digest(
        expected_private_training_projection_sha256,
        "expected_private_training_projection_sha256",
    )
    metadata = _metadata_by_id(private_training_metadata_eval_only)
    if any(record.split != "train" for record in metadata.values()):
        raise ValueError(
            "labeled-library construction accepts private training rows only"
        )
    training_ids = {trajectory.trajectory_id for trajectory in train}
    if set(metadata) != training_ids:
        raise ValueError(
            "private training projection must exactly cover public training IDs"
        )
    if private_training_projection_sha256(tuple(metadata.values())) != (
        private_projection_digest
    ):
        raise ValueError("private training projection SHA-256 mismatch")
    class_names = sorted(
        {
            record.mode_name_eval_only
            for record in metadata.values()
            if record.split == "train"
        }
    )
    if len(class_names) != 4:
        raise ValueError("the labeled-library ablation requires exactly four known classes")
    class_to_component, component_to_class = anonymous_component_mapping(class_names)
    train_assignments = _trajectory_assignments_from_training_labels(
        train,
        metadata,
        class_to_component,
        expected_split="train",
    )

    arx = default_arx_fitter_api()
    train_fits = fit_local_episode_models(
        train,
        arx=arx,
        ridge_lambda=config.discovery.ridge_lambda,
        variance_epsilon=config.discovery.variance_epsilon,
    )
    scaler = FeatureStandardizer.fit(
        np.vstack([record.raw_feature for record in train_fits])
    )
    standardized = scaler.transform(
        np.vstack([record.raw_feature for record in train_fits])
    )
    validation_fits = fit_local_episode_models(
        valid,
        arx=arx,
        ridge_lambda=config.discovery.ridge_lambda,
        variance_epsilon=config.discovery.variance_epsilon,
    )
    standardized_validation = scaler.transform(
        np.vstack([record.raw_feature for record in validation_fits])
    )
    validation_assignments = assign_validation_by_training_feature_centroids(
        standardized,
        train_assignments,
        standardized_validation,
        component_count=len(class_names),
    )
    # Compatibility metadata/scaler are public-signal-only.  The manifest below
    # states explicitly that these GMM assignments did not construct the four
    # ARX models in this label-informed ablation.
    compatibility_selection = select_gmm_by_bic(
        standardized,
        k_min=4,
        k_max=4,
        covariance_type=config.discovery.covariance_type,
        n_init=config.discovery.n_init,
        random_seed=config.discovery.random_seed,
        max_iter=config.discovery.max_iter,
        reg_covar=config.discovery.reg_covar,
    )
    discovery_metadata = discovery_metadata_from_selection(
        compatibility_selection,
        random_seed=config.discovery.random_seed,
    )
    models = refit_global_cluster_models(
        train,
        train_fits,
        train_assignments,
        arx=arx,
        ridge_lambda=config.discovery.ridge_lambda,
        sample_time_s=config.sample_time_s,
        residual_variance_floor=config.discovery.residual_variance_floor,
        lower_power_quantile=config.discovery.lower_power_quantile,
        upper_power_quantile=config.discovery.upper_power_quantile,
        directional_rate_quantile=config.discovery.directional_rate_quantile,
    )
    metrics = evaluate_assigned_validation_episodes(
        valid,
        validation_assignments,
        models,
        sample_time_s=config.sample_time_s,
        horizon=config.multi_step_horizon,
        validate_trajectory=validate_arx_multistep,
    )
    power_error_blocks = _validation_error_blocks(
        valid,
        validation_assignments,
        models,
        horizon=config.multi_step_horizon,
    )
    grid_model = GridFrequencyModel(config.grid_params)
    frequency_errors = {
        component: propagate_grid_frequency_errors(errors, grid_model=grid_model)
        for component, errors in power_error_blocks.items()
    }
    rocof_errors = {
        component: frequency_errors_to_rocof_errors(
            errors, sample_time_s=config.sample_time_s
        )
        for component, errors in frequency_errors.items()
    }
    power_quantiles = {
        metric.component_id: metric.error_quantiles_for_library for metric in metrics
    }
    frequency_quantiles = {
        component: {
            lead + 1: float(np.quantile(np.abs(errors[:, lead]), 0.95))
            for lead in range(errors.shape[1])
        }
        for component, errors in frequency_errors.items()
    }
    rocof_quantiles = {
        component: {
            lead + 1: float(np.quantile(np.abs(errors[:, lead]), 0.95))
            for lead in range(errors.shape[1])
        }
        for component, errors in rocof_errors.items()
    }
    count = len(models)
    stay_probability = (
        1.0
        if count == 1
        else 1.0 - (count - 1) * config.switch_epsilon
    )
    if not 0.0 <= stay_probability <= 1.0:
        raise ValueError("switch_epsilon is invalid for the labeled component count")
    library = mode_library_from_discovery(
        models,
        feature_scaler=scaler,
        discovery_metadata=discovery_metadata,
        multi_step_power_error_quantiles_pu=power_quantiles,
        multi_step_frequency_error_quantiles_hz=frequency_quantiles,
        multi_step_rocof_error_quantiles_hz_per_s=rocof_quantiles,
        stay_probability=stay_probability,
    )

    output = _empty_directory(output_directory)
    runtime = output / "runtime"
    evaluation_only = output / "evaluation_only"
    runtime.mkdir()
    evaluation_only.mkdir()
    library_path = runtime / "mode_library.json"
    library.save_json(library_path)
    assignments = _one_hot_assignments_frame(
        train,
        valid,
        train_assignments,
        validation_assignments,
        component_count=count,
    )
    assignments.to_csv(evaluation_only / "cluster_assignments.csv", index=False)
    _labeled_metrics_frame(models, metrics).to_csv(
        evaluation_only / "mode_model_metrics.csv", index=False
    )
    _quantile_frame(metrics, frequency_errors, rocof_errors).to_csv(
        evaluation_only / "multi_step_error_quantiles.csv", index=False
    )
    file_digest = sha256_file(library_path)
    logical_digest = sha256_json(library.to_dict())
    _write_json(
        runtime / "runtime_manifest.json",
        {
            "schema_version": LABELED_LIBRARY_SCHEMA_VERSION,
            "role": "phase6_labeled_training_library_ablation",
            "runtime_component_identifiers": "anonymous_contiguous_hash_order",
            "semantic_mode_names_present": False,
            "training_label_access": True,
            "validation_label_access": False,
            "test_label_access": False,
            "model_construction": "pooled_ARX_refit_by_private_training_label",
            "validation_assignment": (
                "nearest_training_label_centroid_in_frozen_standardized_"
                "local_arx_feature_space"
            ),
            "compatibility_scaler_and_gmm_metadata": (
                "fit_from_public_training_signals_only; not used for ARX grouping"
            ),
            "component_count": count,
            "mode_library_file_sha256": file_digest,
            "mode_library_logical_sha256": logical_digest,
            "public_dataset_sha256": public_dataset_digest,
            "private_metadata_file_sha256": private_metadata_digest,
            "private_training_projection_sha256": private_projection_digest,
            "training_episode_count": len(train),
            "validation_episode_count": len(valid),
        },
    )
    _write_json(
        evaluation_only / "component_mapping_eval_only.json",
        {
            "schema_version": LABELED_LIBRARY_SCHEMA_VERSION,
            "truth_access": "evaluation_only",
            "anonymous_id_assignment": "domain_separated_sha256_order",
            "component_to_class": {
                str(component): component_to_class[component]
                for component in range(count)
            },
        },
    )
    _write_artifact_hashes(output)
    return LabeledTrainingLibraryRun(
        output_directory=output,
        mode_library=library,
        mode_library_file_sha256=file_digest,
        mode_library_logical_sha256=logical_digest,
        train_assignments=train_assignments.copy(),
        validation_assignments=validation_assignments.copy(),
        component_to_class_eval_only=dict(component_to_class),
    )


def _load_label_free_cluster_assignments(
    path: str | Path,
    *,
    component_count: int,
) -> pd.DataFrame:
    """Strictly load native-ID assignments without any semantic column."""

    if isinstance(component_count, bool) or not isinstance(component_count, int):
        raise TypeError("component_count must be an integer")
    if component_count < 1:
        raise ValueError("component_count must be positive")
    assignments = pd.read_csv(Path(path).expanduser().resolve())
    probability_columns = [
        f"component_probability_{component}"
        for component in range(component_count)
    ]
    expected_columns = [
        "trajectory_id",
        "dataset_split",
        "component_id",
        *probability_columns,
    ]
    if assignments.columns.tolist() != expected_columns:
        raise ValueError("cluster assignments do not match the truth-free schema")
    if assignments.empty or assignments["trajectory_id"].duplicated().any():
        raise ValueError("cluster assignments must be non-empty with unique IDs")
    if set(assignments["dataset_split"]) != {"train", "validation"}:
        raise ValueError("cluster assignments must contain train and validation only")
    component_values = assignments["component_id"].to_numpy()
    if (
        not np.issubdtype(component_values.dtype, np.integer)
        or np.any(component_values < 0)
        or np.any(component_values >= component_count)
    ):
        raise ValueError("cluster assignments contain invalid component IDs")
    probabilities = assignments[probability_columns].to_numpy(dtype=np.float64)
    if (
        not np.all(np.isfinite(probabilities))
        or np.any(probabilities < 0.0)
        or not np.allclose(
            probabilities.sum(axis=1), 1.0, rtol=0.0, atol=1.0e-10
        )
    ):
        raise ValueError("cluster assignment probabilities must be row-stochastic")
    if not np.array_equal(
        np.argmax(probabilities, axis=1),
        component_values.astype(np.int64),
    ):
        raise ValueError("component IDs disagree with maximum assignment probability")
    return assignments


def build_fixed_k4_evaluation_mapping(
    library: ModeLibrary,
    private_training_metadata: Sequence[PrivateTrajectoryMetadata],
    *,
    mode_library_path: str | Path,
    cluster_assignments_path: str | Path,
    expected_private_training_projection_sha256: str,
    output_path: str | Path,
) -> FixedK4EvaluationMappingArtifact:
    """Join K4's label-free train assignments to private train labels.

    This post-hoc majority table is evaluation-only.  It preserves the native
    anonymous IDs, permits multiple IDs to map to one semantic class, and does
    not alter the assignment file used by future known-only OOD calibration.
    """

    if not isinstance(library, ModeLibrary) or len(library.models) != 4:
        raise ValueError("library must be a strict four-component ModeLibrary")
    library_path = Path(mode_library_path).expanduser().resolve()
    assignments_path = Path(cluster_assignments_path).expanduser().resolve()
    destination = Path(output_path).expanduser().resolve()
    loaded_library = ModeLibrary.load_json(library_path)
    if sha256_json(loaded_library.to_dict()) != sha256_json(library.to_dict()):
        raise ValueError("mode-library object differs from the bound file")

    metadata = _metadata_by_id(tuple(private_training_metadata))
    if any(record.split != "train" for record in metadata.values()):
        raise ValueError("fixed-K4 evaluation mapping accepts training rows only")
    private_projection_digest = private_training_projection_sha256(
        tuple(metadata.values())
    )
    if private_projection_digest != _sha256_digest(
        expected_private_training_projection_sha256,
        "expected_private_training_projection_sha256",
    ):
        raise ValueError("private training projection SHA-256 mismatch")

    assignments = _load_label_free_cluster_assignments(
        assignments_path,
        component_count=4,
    )
    training_rows = assignments.loc[
        assignments["dataset_split"] == "train",
        ["trajectory_id", "component_id"],
    ].copy()
    assignment_ids = set(training_rows["trajectory_id"])
    if assignment_ids != set(metadata):
        missing = sorted(assignment_ids - set(metadata))
        extra = sorted(set(metadata) - assignment_ids)
        raise ValueError(
            "private training metadata does not exactly cover label-free train "
            f"assignments; missing_metadata={missing}, extra_metadata={extra}"
        )
    semantic_names = tuple(
        sorted({record.mode_name_eval_only for record in metadata.values()})
    )
    semantic_by_id = {
        trajectory_id: record.mode_name_eval_only
        for trajectory_id, record in metadata.items()
    }
    training_rows["mode_name_eval_only"] = training_rows["trajectory_id"].map(
        semantic_by_id
    )
    records: list[FixedK4SemanticMajorityRecord] = []
    for component in range(4):
        names = training_rows.loc[
            training_rows["component_id"] == component,
            "mode_name_eval_only",
        ].tolist()
        if not names:
            raise ValueError(
                f"fixed-K4 component {component} has no training assignment evidence"
            )
        counts = {name: names.count(name) for name in semantic_names}
        maximum = max(counts.values())
        selected = min(name for name, count in counts.items() if count == maximum)
        records.append(
            FixedK4SemanticMajorityRecord(
                component_id=component,
                selected_mode_name_eval_only=selected,
                training_episode_count=len(names),
                majority_episode_count=maximum,
                purity=maximum / len(names),
                counts_by_mode_eval_only=counts,
            )
        )

    artifact = FixedK4EvaluationMappingArtifact(
        component_count=4,
        mode_library_file_sha256=sha256_file(library_path),
        mode_library_logical_sha256=sha256_json(library.to_dict()),
        cluster_assignments_file_sha256=sha256_file(assignments_path),
        private_training_projection_sha256=private_projection_digest,
        components=tuple(records),
    )
    _write_json(destination, artifact.to_dict())
    return artifact


@dataclass(frozen=True, slots=True)
class FixedK4LibraryRun:
    discovery_run: LabelFreeDiscoveryRun
    construction_manifest_path: Path
    evaluation_mapping: FixedK4EvaluationMappingArtifact
    evaluation_mapping_path: Path
    artifact_hashes_path: Path


def build_fixed_k4_unlabeled_library(
    training: Sequence[IdentificationTrajectory],
    validation: Sequence[IdentificationTrajectory],
    private_training_metadata: Sequence[PrivateTrajectoryMetadata],
    *,
    config: OfflinePipelineConfig,
    output_directory: str | Path,
    public_dataset_sha256: str,
    public_manifest_file_sha256: str,
    expected_private_training_projection_sha256: str,
) -> FixedK4LibraryRun:
    """Run label-free fixed-K4, then emit a separate evaluator-only mapping."""

    if not isinstance(config, OfflinePipelineConfig):
        raise TypeError("config must be an OfflinePipelineConfig")
    dataset_digest = _sha256_digest(
        public_dataset_sha256, "public_dataset_sha256"
    )
    manifest_digest = _sha256_digest(
        public_manifest_file_sha256, "public_manifest_file_sha256"
    )
    train = tuple(training)
    valid = tuple(validation)
    fixed_discovery = replace(config.discovery, k_min=4, k_max=4)
    fixed_config = replace(config, discovery=fixed_discovery)
    run = run_label_free_mode_discovery(
        train,
        valid,
        config=fixed_config,
        output_directory=output_directory,
    )
    if len(run.mode_library.models) != 4:
        raise RuntimeError("fixed-K4 discovery did not produce four models")
    library_path = run.output_directory / "mode_library.json"
    assignments_path = run.output_directory / "cluster_assignments.csv"
    mapping_path = (
        run.output_directory
        / "evaluation_only"
        / "component_mapping_eval_only.json"
    )
    evaluation_mapping = build_fixed_k4_evaluation_mapping(
        run.mode_library,
        private_training_metadata,
        mode_library_path=library_path,
        cluster_assignments_path=assignments_path,
        expected_private_training_projection_sha256=(
            expected_private_training_projection_sha256
        ),
        output_path=mapping_path,
    )
    manifest_path = run.output_directory / "phase6_construction_manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": FIXED_K4_SCHEMA_VERSION,
            "role": "phase6_fixed_k4_unlabeled_library_ablation",
            "runtime_library_information_boundary": (
                "public_train_and_validation_only"
            ),
            "evaluation_mapping_information_boundary": (
                "private_identification_train_labels_only"
            ),
            "runtime_training_label_access": False,
            "runtime_validation_label_access": False,
            "runtime_test_label_access": False,
            "evaluation_mapping_training_label_access": True,
            "evaluation_mapping_validation_label_access": False,
            "evaluation_mapping_test_label_access": False,
            "evaluation_mapping_runtime_consumable": False,
            "future_ood_calibration_assignment_source": "cluster_assignments.csv",
            "future_ood_calibration_semantic_mapping_access": False,
            "candidate_k_min": 4,
            "candidate_k_max": 4,
            "selected_k": 4,
            "public_dataset_sha256": dataset_digest,
            "public_manifest_file_sha256": manifest_digest,
            "training_episode_count": len(train),
            "validation_episode_count": len(valid),
            "mode_library_file_sha256": sha256_file(library_path),
            "mode_library_logical_sha256": sha256_json(run.mode_library.to_dict()),
            "cluster_assignments_file_sha256": sha256_file(assignments_path),
            "evaluation_mapping_file": (
                mapping_path.relative_to(run.output_directory).as_posix()
            ),
            "evaluation_mapping_file_sha256": sha256_file(mapping_path),
            "private_training_projection_sha256": (
                evaluation_mapping.private_training_projection_sha256
            ),
        },
    )
    artifact_hashes_path = _write_artifact_hashes(run.output_directory)
    return FixedK4LibraryRun(
        run,
        manifest_path,
        evaluation_mapping,
        mapping_path,
        artifact_hashes_path,
    )


def _verify_label_free_artifact_hashes(
    manifest_path: Path,
    *,
    mode_library_path: Path,
    cluster_assignments_path: Path,
) -> None:
    payload = _strict_json(manifest_path)
    manifest = _exact_mapping(
        payload,
        frozenset({"schema_version", "scope", "sha256"}),
        "label-free artifact hash manifest",
    )
    if manifest["schema_version"] != 1:
        raise ValueError("label-free artifact hash manifest schema_version must be 1")
    if manifest["scope"] != "label_free_artifacts_before_reference_evaluation":
        raise ValueError("label-free artifact hash manifest has the wrong scope")
    hashes = manifest["sha256"]
    if not isinstance(hashes, Mapping) or not all(
        isinstance(key, str) for key in hashes
    ):
        raise TypeError("label-free artifact hashes must be a string-keyed mapping")
    manifest_directory = manifest_path.parent.resolve()
    for relative_name, raw_digest in hashes.items():
        relative = Path(relative_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("label-free artifact manifest contains an unsafe path")
        declared_path = (manifest_directory / relative).resolve()
        if not declared_path.is_relative_to(manifest_directory):
            raise ValueError("label-free artifact path escapes its manifest directory")
        declared_digest = _sha256_digest(
            raw_digest, f"label-free hash for {relative_name}"
        )
        if not declared_path.is_file() or sha256_file(declared_path) != declared_digest:
            raise ValueError(f"label-free artifact SHA-256 mismatch: {relative_name}")
    expected = {
        "mode_library.json": mode_library_path,
        "cluster_assignments.csv": cluster_assignments_path,
    }
    for artifact_name, artifact_path in expected.items():
        declared = _sha256_digest(
            hashes.get(artifact_name),
            f"label-free hash for {artifact_name}",
        )
        if sha256_file(artifact_path) != declared:
            raise ValueError(f"label-free {artifact_name} SHA-256 mismatch")


def public_validation_split_sha256(public_data_directory: str | Path) -> str:
    """Return the canonical ``LibraryArtifactBinding`` validation digest."""

    return identification_subset_digests(public_data_directory)[
        "validation"
    ].canonical_sha256


def build_fixed_reference_selection(
    *,
    mode_library_path: str | Path,
    cluster_assignments_path: str | Path,
    label_free_artifact_hashes_path: str | Path,
    public_data_directory: str | Path,
    protocol_sha256: str,
) -> FixedReferenceSelectionArtifact:
    """Select B1 by a registered, truth-free validation capability criterion.

    Every validation episode assigned to a component is retained.  The score
    is the smaller magnitude of its 1% and 99% observed power quantiles.  Thus
    the fixed reference represents the anonymous component with the widest
    symmetric demonstrated validation envelope; no mode label is consulted.
    """

    library_path = Path(mode_library_path).expanduser().resolve()
    assignments_path = Path(cluster_assignments_path).expanduser().resolve()
    hashes_path = Path(label_free_artifact_hashes_path).expanduser().resolve()
    public = Path(public_data_directory).expanduser().resolve()
    _verify_label_free_artifact_hashes(
        hashes_path,
        mode_library_path=library_path,
        cluster_assignments_path=assignments_path,
    )
    library = ModeLibrary.load_json(library_path)
    assignments = pd.read_csv(assignments_path)
    probability_columns = [
        f"component_probability_{component}"
        for component in range(len(library.models))
    ]
    expected_columns = [
        "trajectory_id",
        "dataset_split",
        "component_id",
        *probability_columns,
    ]
    if assignments.columns.tolist() != expected_columns:
        raise ValueError("cluster assignments do not match the truth-free schema")
    if assignments["trajectory_id"].duplicated().any():
        raise ValueError("cluster assignments contain duplicate trajectory IDs")
    if set(assignments["dataset_split"]) != {"train", "validation"}:
        raise ValueError("cluster assignments must contain train and validation only")
    component_values = assignments["component_id"].to_numpy()
    if (
        not np.issubdtype(component_values.dtype, np.integer)
        or np.any(component_values < 0)
        or np.any(component_values >= len(library.models))
    ):
        raise ValueError("cluster assignments contain invalid component IDs")
    probabilities = assignments[probability_columns].to_numpy(dtype=np.float64)
    if (
        not np.all(np.isfinite(probabilities))
        or np.any(probabilities < 0.0)
        or not np.allclose(
            probabilities.sum(axis=1), 1.0, rtol=0.0, atol=1.0e-10
        )
    ):
        raise ValueError("cluster assignment probabilities must be row-stochastic")
    if not np.array_equal(
        np.argmax(probabilities, axis=1),
        component_values.astype(np.int64),
    ):
        raise ValueError("component IDs disagree with maximum assignment probability")
    validation = tuple(
        load_public_identification_data(public, split="validation", verify_hashes=True)
    )
    validation_by_id = {trajectory.trajectory_id: trajectory for trajectory in validation}
    rows = assignments.loc[
        assignments["dataset_split"] == "validation",
        ["trajectory_id", "component_id"],
    ].copy()
    if rows["trajectory_id"].duplicated().any():
        raise ValueError("validation assignments contain duplicate trajectory IDs")
    if set(rows["trajectory_id"]) != set(validation_by_id):
        raise ValueError("validation assignments do not exactly cover the public split")

    scores: list[ReferenceCandidateScore] = []
    for component in range(len(library.models)):
        identifiers = rows.loc[
            rows["component_id"] == component, "trajectory_id"
        ].tolist()
        if not identifiers:
            raise ValueError(f"component {component} has no validation episodes")
        powers = np.concatenate(
            [
                np.asarray(validation_by_id[str(identifier)].p_ibr_pu, dtype=np.float64)
                for identifier in identifiers
            ]
        )
        lower, upper = np.quantile(powers, [0.01, 0.99])
        score = min(abs(float(lower)), abs(float(upper)))
        if not math.isfinite(score):
            raise FloatingPointError("fixed-reference score is non-finite")
        scores.append(
            ReferenceCandidateScore(
                component_id=component,
                score=score,
                registered_episode_count=len(identifiers),
                retained_episode_count=len(identifiers),
                failed_episode_count=0,
            )
        )
    selected = max(scores, key=lambda item: (item.score, -item.component_id))
    return FixedReferenceSelectionArtifact(
        mode_library_file_sha256=sha256_file(library_path),
        mode_library_logical_sha256=sha256_json(library.to_dict()),
        component_count=len(library.models),
        selected_component_id=selected.component_id,
        selection_split="identification_validation",
        criterion=FIXED_REFERENCE_CRITERION,
        direction="maximize",
        selection_dataset_sha256=public_validation_split_sha256(public),
        protocol_sha256=_sha256_digest(protocol_sha256, "protocol_sha256"),
        label_access="none",
        candidate_scores=tuple(scores),
    )


def save_fixed_reference_selection(
    artifact: FixedReferenceSelectionArtifact,
    path: str | Path,
) -> Path:
    if not isinstance(artifact, FixedReferenceSelectionArtifact):
        raise TypeError("artifact must be a FixedReferenceSelectionArtifact")
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_json(destination, artifact.to_dict())
    return destination


@dataclass(frozen=True, slots=True)
class Phase6LibraryAblationBuild:
    output_directory: Path
    fixed_k4: FixedK4LibraryRun
    labeled_library: LabeledTrainingLibraryRun
    oracle_arx: OracleARXBuild
    fixed_reference_selection: FixedReferenceSelectionArtifact
    subset_hash_manifest_path: Path
    binding_inputs_path: Path
    build_manifest_path: Path
    artifact_hashes_path: Path


def _phase6_source_hashes(repository_root: Path) -> Mapping[str, str]:
    hashes: dict[str, str] = {}
    for relative_name in _PHASE6_SOURCE_PATHS:
        path = repository_root / Path(relative_name)
        if not path.is_file():
            raise FileNotFoundError(path)
        hashes[relative_name] = sha256_file(path)
    return MappingProxyType(hashes)


def _library_binding_input(
    *,
    artifact_id: str,
    construction_protocol: str,
    library: ModeLibrary,
    library_path: Path,
    subsets: Mapping[str, IdentificationSubsetDigest],
    subset_manifest_sha256: str,
) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "construction_protocol": construction_protocol,
        "component_count": len(library.models),
        "mode_library_file_sha256": sha256_file(library_path),
        "mode_library_logical_sha256": sha256_json(library.to_dict()),
        "ood_calibration_file_sha256": None,
        "ood_binding_status": "pending_separate_known_only_calibration",
        "identification_train_dataset_sha256": subsets["train"].canonical_sha256,
        "identification_validation_dataset_sha256": (
            subsets["validation"].canonical_sha256
        ),
        "identification_subset_hash_manifest_sha256": subset_manifest_sha256,
        "runtime_label_access": "none",
    }


def build_phase6_library_ablations_from_artifacts(
    *,
    base_config_path: str | Path,
    experiments_config_path: str | Path,
    public_data_directory: str | Path,
    private_data_directory: str | Path,
    mode_discovery_directory: str | Path,
    output_directory: str | Path,
) -> Phase6LibraryAblationBuild:
    """Build all pre-calibration Phase-6 library and B1/B4 artifacts.

    The output root must be new or empty.  This function never deletes files,
    never overwrites an existing artifact, and deliberately does not construct
    or invoke an OOD calibration pipeline.
    """

    output = _empty_directory(output_directory)
    base_path = Path(base_config_path).expanduser().resolve()
    experiments_path = Path(experiments_config_path).expanduser().resolve()
    public = Path(public_data_directory).expanduser().resolve()
    private = Path(private_data_directory).expanduser().resolve()
    discovery_directory = Path(mode_discovery_directory).expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[3]

    base_payload = load_yaml(base_path)
    pipeline_config = offline_pipeline_config_from_base_config(base_payload)
    # Import locally so no controller can acquire this evaluation-only module
    # through a shared runtime dependency.
    from d5freq.evaluation.closed_loop_scenarios import load_experiment_protocol

    load_experiment_protocol(experiments_path)
    experiments_payload = load_yaml(experiments_path)
    protocol_digest = config_sha256(experiments_payload)
    base_config_digest = config_sha256(base_payload)

    training = tuple(
        load_public_identification_data(public, split="train", verify_hashes=True)
    )
    validation = tuple(
        load_public_identification_data(
            public, split="validation", verify_hashes=True
        )
    )
    public_manifest_path = public / "public_manifest.json"
    public_manifest = _strict_json(public_manifest_path)
    if not isinstance(public_manifest, Mapping):
        raise TypeError("public manifest must be a JSON object")
    public_dataset_digest = _sha256_digest(
        public_manifest.get("dataset_sha256"), "public dataset SHA-256"
    )
    public_manifest_file_digest = sha256_file(public_manifest_path)
    subsets = identification_subset_digests(public)

    private_metadata_path = private / "evaluation_metadata.json"
    all_private_metadata = load_private_metadata_evaluation_only(
        private,
        public_manifest_path,
    )
    private_training_metadata = tuple(
        record for record in all_private_metadata if record.split == "train"
    )
    private_projection_digest = private_training_projection_sha256(
        private_training_metadata
    )
    private_metadata_file_digest = sha256_file(private_metadata_path)

    source_hashes = _phase6_source_hashes(repository_root)
    provenance_directory = output / "provenance"
    provenance_directory.mkdir()
    subset_manifest_path = save_identification_subset_hash_manifest(
        subsets,
        provenance_directory / "identification_subset_hashes.json",
    )
    subset_manifest_digest = sha256_file(subset_manifest_path)

    fixed_k4 = build_fixed_k4_unlabeled_library(
        training,
        validation,
        private_training_metadata,
        config=pipeline_config,
        output_directory=output / "fixed_k4_unlabeled",
        public_dataset_sha256=public_dataset_digest,
        public_manifest_file_sha256=public_manifest_file_digest,
        expected_private_training_projection_sha256=private_projection_digest,
    )
    labeled = build_labeled_training_library(
        training,
        validation,
        private_training_metadata,
        config=pipeline_config,
        output_directory=output / "labeled_training_library",
        public_dataset_sha256=public_dataset_digest,
        private_metadata_file_sha256=private_metadata_file_digest,
        expected_private_training_projection_sha256=private_projection_digest,
    )

    evaluation_only_directory = output / "evaluation_only"
    evaluation_only_directory.mkdir()
    oracle = build_oracle_arx_artifact(
        labeled,
        identification_train_dataset_sha256=subsets["train"].canonical_sha256,
        training_config_sha256=base_config_digest,
        output_path=evaluation_only_directory / "oracle_arx_artifact.json",
    )

    canonical_library_path = discovery_directory / "mode_library.json"
    canonical_assignments_path = discovery_directory / "cluster_assignments.csv"
    canonical_hashes_path = discovery_directory / "label_free_artifact_hashes.json"
    fixed_reference = build_fixed_reference_selection(
        mode_library_path=canonical_library_path,
        cluster_assignments_path=canonical_assignments_path,
        label_free_artifact_hashes_path=canonical_hashes_path,
        public_data_directory=public,
        protocol_sha256=protocol_digest,
    )
    fixed_reference_directory = output / "fixed_reference"
    fixed_reference_runtime = fixed_reference_directory / "runtime"
    fixed_reference_runtime.mkdir(parents=True)
    fixed_reference_path = save_fixed_reference_selection(
        fixed_reference,
        fixed_reference_runtime / "fixed_reference_selection.json",
    )
    _write_json(
        fixed_reference_runtime / "runtime_manifest.json",
        {
            "schema_version": "d5freq.fixed-reference-runtime.v1",
            "information_boundary": "public_identification_validation_only",
            "runtime_label_access": "none",
            "test_access": False,
            "selection_artifact_sha256": sha256_file(fixed_reference_path),
            "selection_dataset_sha256": fixed_reference.selection_dataset_sha256,
            "protocol_sha256": fixed_reference.protocol_sha256,
        },
    )
    _write_artifact_hashes(fixed_reference_directory)

    canonical_library = ModeLibrary.load_json(canonical_library_path)
    binding_inputs = {
        "schema_version": "d5freq.library_binding_inputs.v1",
        "ood_calibration_status": (
            "not_built_here; each library requires separate known-only calibration"
        ),
        "identification_subset_hash_manifest": (
            subset_manifest_path.relative_to(output).as_posix()
        ),
        "libraries": [
            _library_binding_input(
                artifact_id="native_k6_discovered",
                construction_protocol="discovered_bic_label_free",
                library=canonical_library,
                library_path=canonical_library_path,
                subsets=subsets,
                subset_manifest_sha256=subset_manifest_digest,
            ),
            _library_binding_input(
                artifact_id="fixed_k4_unlabeled",
                construction_protocol="fixed_k4_unlabeled",
                library=fixed_k4.discovery_run.mode_library,
                library_path=(
                    fixed_k4.discovery_run.output_directory / "mode_library.json"
                ),
                subsets=subsets,
                subset_manifest_sha256=subset_manifest_digest,
            ),
            _library_binding_input(
                artifact_id="labeled_training_only_k4",
                construction_protocol="labeled_training_only",
                library=labeled.mode_library,
                library_path=labeled.output_directory / "runtime" / "mode_library.json",
                subsets=subsets,
                subset_manifest_sha256=subset_manifest_digest,
            ),
        ],
    }
    binding_inputs_path = provenance_directory / "library_binding_inputs.json"
    _write_json(binding_inputs_path, binding_inputs)

    known_class_names = {
        record.mode_name_eval_only for record in private_training_metadata
    }
    runtime_text_paths = (
        fixed_k4.discovery_run.output_directory / "mode_library.json",
        fixed_k4.discovery_run.output_directory / "cluster_assignments.csv",
        fixed_k4.construction_manifest_path,
        labeled.output_directory / "runtime" / "mode_library.json",
        labeled.output_directory / "runtime" / "runtime_manifest.json",
        fixed_reference_path,
        fixed_reference_runtime / "runtime_manifest.json",
    )
    leaked = {
        path.relative_to(output).as_posix(): sorted(
            name
            for name in known_class_names
            if name in path.read_text(encoding="utf-8")
        )
        for path in runtime_text_paths
    }
    leaked = {path: names for path, names in leaked.items() if names}
    if leaked:
        raise RuntimeError(f"semantic names leaked into runtime artifacts: {leaked}")

    build_manifest_path = output / "build_manifest.json"
    _write_json(
        build_manifest_path,
        {
            "schema_version": PHASE6_LIBRARY_ABLATION_BUILD_SCHEMA_VERSION,
            "scope": "pre_ood_calibration_library_ablations_and_b1_b4",
            "ood_calibration_invoked": False,
            "information_boundaries": {
                "fixed_k4_unlabeled": "public_train_and_validation_only",
                "fixed_k4_semantic_mapping": (
                    "evaluation_only_private_training_labels_only"
                ),
                "labeled_library_model_fit": "private_training_labels_only",
                "labeled_library_validation_assignment": "public_signals_only",
                "fixed_reference": "public_identification_validation_only",
                "oracle_arx": "evaluation_only_semantic_routing",
            },
            "input_hashes": {
                "base_config_file_sha256": sha256_file(base_path),
                "base_config_logical_sha256": base_config_digest,
                "experiments_config_file_sha256": sha256_file(experiments_path),
                "experiments_protocol_logical_sha256": protocol_digest,
                "public_manifest_file_sha256": public_manifest_file_digest,
                "public_dataset_sha256": public_dataset_digest,
                "private_manifest_file_sha256": sha256_file(
                    private / "private_manifest.json"
                ),
                "private_metadata_file_sha256": private_metadata_file_digest,
                "private_training_projection_sha256": private_projection_digest,
                "canonical_label_free_hash_manifest_sha256": sha256_file(
                    canonical_hashes_path
                ),
            },
            "source_hashes": dict(source_hashes),
            "subset_hashes": {
                "train": subsets["train"].canonical_sha256,
                "validation": subsets["validation"].canonical_sha256,
                "manifest_file_sha256": subset_manifest_digest,
            },
            "outputs": {
                "fixed_k4_mode_library_file_sha256": sha256_file(
                    fixed_k4.discovery_run.output_directory / "mode_library.json"
                ),
                "fixed_k4_mode_library_logical_sha256": sha256_json(
                    fixed_k4.discovery_run.mode_library.to_dict()
                ),
                "fixed_k4_evaluation_mapping_file_sha256": sha256_file(
                    fixed_k4.evaluation_mapping_path
                ),
                "fixed_k4_evaluation_mapping_logical_sha256": sha256_json(
                    fixed_k4.evaluation_mapping.to_dict()
                ),
                "labeled_mode_library_file_sha256": labeled.mode_library_file_sha256,
                "labeled_mode_library_logical_sha256": (
                    labeled.mode_library_logical_sha256
                ),
                "fixed_reference_selection_file_sha256": sha256_file(
                    fixed_reference_path
                ),
                "oracle_arx_file_sha256": oracle.file_sha256,
                "oracle_arx_logical_sha256": oracle.logical_sha256,
            },
            "episode_counts": {
                "identification_train": len(training),
                "identification_validation": len(validation),
            },
            "runtime_semantic_name_scan": "passed_no_matches",
        },
    )
    artifact_hashes_path = _write_artifact_hashes(output)
    return Phase6LibraryAblationBuild(
        output_directory=output,
        fixed_k4=fixed_k4,
        labeled_library=labeled,
        oracle_arx=oracle,
        fixed_reference_selection=fixed_reference,
        subset_hash_manifest_path=subset_manifest_path,
        binding_inputs_path=binding_inputs_path,
        build_manifest_path=build_manifest_path,
        artifact_hashes_path=artifact_hashes_path,
    )


__all__ = [
    "FIXED_K4_EVALUATION_MAPPING_SCHEMA_VERSION",
    "FIXED_K4_SCHEMA_VERSION",
    "FIXED_REFERENCE_CRITERION",
    "IDENTIFICATION_SUBSET_HASH_SCHEMA_VERSION",
    "IDENTIFICATION_SUBSET_MANIFEST_SCHEMA_VERSION",
    "LABELED_LIBRARY_SCHEMA_VERSION",
    "PHASE6_LIBRARY_ABLATION_BUILD_SCHEMA_VERSION",
    "FixedK4EvaluationMappingArtifact",
    "FixedK4LibraryRun",
    "FixedK4SemanticMajorityRecord",
    "IdentificationSubsetDigest",
    "LabeledTrainingLibraryRun",
    "OracleARXBuild",
    "Phase6LibraryAblationBuild",
    "anonymous_component_mapping",
    "assign_validation_by_training_feature_centroids",
    "build_fixed_k4_evaluation_mapping",
    "build_fixed_k4_unlabeled_library",
    "build_fixed_reference_selection",
    "build_labeled_training_library",
    "build_oracle_arx_artifact",
    "build_phase6_library_ablations_from_artifacts",
    "identification_subset_digests",
    "load_private_metadata_evaluation_only",
    "private_training_projection_sha256",
    "public_validation_split_sha256",
    "save_fixed_reference_selection",
    "save_identification_subset_hash_manifest",
]
