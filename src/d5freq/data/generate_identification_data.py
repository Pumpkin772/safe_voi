"""Generate, audit, split, and serialize unlabeled IBR identification data."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import csv
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.utils.hashing import sha256_file, sha256_json
from d5freq.utils.seeds import SeedManager

from .excitation import excitation_sha256, generate_safe_excitation
from .identification_bench import (
    audit_identification_trajectory,
    simulate_identification_trajectory,
)
from .schemas import (
    EXCITATION_FAMILIES,
    PUBLIC_SAMPLE_COLUMNS,
    PUBLIC_SPLIT_COLUMNS,
    SPLIT_NAMES,
    IdentificationGenerationConfig,
    IdentificationTrajectory,
    PrivateTrajectoryMetadata,
    SplitCounts,
    TrajectoryAudit,
)


SCHEMA_VERSION = 1
_OPAQUE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "sample_columns",
        "split_columns",
        "split_names",
        "trajectory_count",
        "split_counts",
        "split_manifest_sha256",
        "trajectory_manifest_sha256",
        "dataset_sha256",
    }
)


@dataclass(frozen=True, slots=True)
class IdentificationGenerationResult:
    """In-memory generation result with explicitly separated truth metadata."""

    public_trajectories: tuple[IdentificationTrajectory, ...]
    public_split_assignments: tuple[tuple[str, str], ...]
    private_evaluation_metadata: tuple[PrivateTrajectoryMetadata, ...]
    private_audits: tuple[TrajectoryAudit, ...]
    generation_config: IdentificationGenerationConfig

    def __post_init__(self) -> None:
        identifiers = [item.trajectory_id for item in self.public_trajectories]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("public trajectory IDs must be unique")
        identifier_set = set(identifiers)
        split_ids = [item[0] for item in self.public_split_assignments]
        private_ids = [item.trajectory_id for item in self.private_evaluation_metadata]
        audit_ids = [item.trajectory_id for item in self.private_audits]
        if set(split_ids) != identifier_set or len(split_ids) != len(identifier_set):
            raise ValueError("split assignments must cover every public ID exactly once")
        if set(private_ids) != identifier_set or len(private_ids) != len(identifier_set):
            raise ValueError("private metadata must cover every public ID exactly once")
        if set(audit_ids) != identifier_set or len(audit_ids) != len(identifier_set):
            raise ValueError("private audits must cover every public ID exactly once")
        for _, split in self.public_split_assignments:
            if split not in SPLIT_NAMES:
                raise ValueError(f"invalid public split: {split!r}")

    @property
    def split_by_trajectory_id(self) -> dict[str, str]:
        return dict(self.public_split_assignments)

    def trajectories_for_split(
        self, split: str
    ) -> tuple[IdentificationTrajectory, ...]:
        """Return public trajectories for one split without touching truth."""

        if split not in SPLIT_NAMES:
            raise ValueError(f"unknown split: {split!r}")
        assignments = self.split_by_trajectory_id
        return tuple(
            trajectory
            for trajectory in self.public_trajectories
            if assignments[trajectory.trajectory_id] == split
        )


@dataclass(frozen=True, slots=True)
class WrittenIdentificationDataset:
    """Paths and integrity hashes returned after serialization."""

    output_directory: Path
    public_directory: Path
    private_directory: Path
    public_manifest_sha256: str
    private_metadata_sha256: str
    dataset_sha256: str
    trajectory_count: int


def generation_config_from_base_config(
    base_config: Mapping[str, Any],
    *,
    trajectories_per_mode: int | None = None,
    trajectory_duration_s: float | None = None,
    split_counts_per_mode: SplitCounts | Mapping[str, int] | None = None,
) -> IdentificationGenerationConfig:
    """Build the strict generation schema from the fully resolved base YAML."""

    try:
        project = base_config["project"]
        grid = base_config["grid"]
        identification = base_config["identification"]
        generation = identification["generation"]
    except (KeyError, TypeError) as exc:
        raise ValueError("base config is missing identification generation fields") from exc
    configured_families = tuple(generation.get("excitation_families", ()))
    if configured_families != EXCITATION_FAMILIES:
        raise ValueError(
            "identification.generation.excitation_families must be exactly "
            f"{EXCITATION_FAMILIES}"
        )
    count = int(
        identification["trajectories_per_mode"]
        if trajectories_per_mode is None
        else trajectories_per_mode
    )
    duration = float(
        identification["trajectory_duration_s"]
        if trajectory_duration_s is None
        else trajectory_duration_s
    )
    if split_counts_per_mode is None:
        configured_counts = SplitCounts.from_mapping(
            generation["split_counts_per_mode"]
        )
        if configured_counts.total == count:
            counts = configured_counts
        elif trajectories_per_mode is not None:
            counts = proportional_split_counts(count)
        else:
            counts = configured_counts
    elif isinstance(split_counts_per_mode, SplitCounts):
        counts = split_counts_per_mode
    else:
        counts = SplitCounts.from_mapping(split_counts_per_mode)
    return IdentificationGenerationConfig(
        master_seed=int(project["seed"]),
        trajectories_per_mode=count,
        trajectory_duration_s=duration,
        control_period_s=float(grid["control_period_s"]),
        integration_step_s=float(grid["integration_step_s"]),
        f0_hz=float(grid["f0_hz"]),
        command_abs_limit_pu=float(generation["command_abs_limit_pu"]),
        command_rate_limit_pu_per_s=float(
            generation["command_rate_limit_pu_per_s"]
        ),
        frequency_abs_limit_hz=float(generation["frequency_abs_limit_hz"]),
        power_measurement_noise_std_pu=float(
            generation["power_measurement_noise_std_pu"]
        ),
        minimum_command_std_pu=float(generation["minimum_command_std_pu"]),
        minimum_frequency_std_hz=float(
            generation["minimum_frequency_std_hz"]
        ),
        maximum_regression_condition_number=float(
            generation["maximum_regression_condition_number"]
        ),
        split_counts_per_mode=counts,
    )


def proportional_split_counts(trajectories_per_mode: int) -> SplitCounts:
    """Scale the required 60/20/10/10 split for a small deterministic run."""

    if isinstance(trajectories_per_mode, bool):
        raise TypeError("trajectories_per_mode must be an integer")
    count = int(trajectories_per_mode)
    if count <= 0 or count != trajectories_per_mode:
        raise ValueError("trajectories_per_mode must be a positive integer")
    fractions = dict(
        zip(SPLIT_NAMES, (0.60, 0.20, 0.10, 0.10), strict=True)
    )
    raw = {name: count * fractions[name] for name in SPLIT_NAMES}
    counts = {name: int(np.floor(raw[name])) for name in SPLIT_NAMES}
    counts["train"] = max(1, counts["train"])
    while sum(counts.values()) < count:
        candidates = sorted(
            SPLIT_NAMES,
            key=lambda name: (-(raw[name] - counts[name]), SPLIT_NAMES.index(name)),
        )
        counts[candidates[0]] += 1
    while sum(counts.values()) > count:
        candidates = sorted(
            (name for name in SPLIT_NAMES if counts[name] > (1 if name == "train" else 0)),
            key=lambda name: (raw[name] - counts[name], -SPLIT_NAMES.index(name)),
        )
        if not candidates:
            raise RuntimeError("cannot construct proportional split counts")
        counts[candidates[0]] -= 1
    return SplitCounts(**counts)


def deterministic_pair_splits(
    trajectories_per_mode: int,
    split_counts: SplitCounts,
    *,
    master_seed: int,
) -> tuple[str, ...]:
    """Assign complete excitation pairs to splits with family stratification."""

    if split_counts.total != trajectories_per_mode:
        raise ValueError("split counts must sum to trajectories_per_mode")
    manager = SeedManager(master_seed)
    queues: dict[str, deque[int]] = {}
    for family_index, family in enumerate(EXCITATION_FAMILIES):
        pair_indices = np.arange(
            family_index, trajectories_per_mode, len(EXCITATION_FAMILIES), dtype=int
        )
        rng = manager.rng("split-family-order", family)
        shuffled = pair_indices[rng.permutation(len(pair_indices))].tolist()
        queues[family] = deque(int(index) for index in shuffled)

    family_order = list(EXCITATION_FAMILIES)
    family_rng = manager.rng("split-family-cycle")
    family_order = [family_order[int(index)] for index in family_rng.permutation(4)]
    stratified_order: list[int] = []
    while any(queues.values()):
        for family in family_order:
            if queues[family]:
                stratified_order.append(queues[family].popleft())
    if len(stratified_order) != trajectories_per_mode:
        raise RuntimeError("pair split construction lost a trajectory")

    assignments = [""] * trajectories_per_mode
    cursor = 0
    for split in SPLIT_NAMES:
        stop = cursor + getattr(split_counts, split)
        members = stratified_order[cursor:stop]
        split_rng = manager.rng("split-member-order", split)
        for offset in split_rng.permutation(len(members)):
            assignments[members[int(offset)]] = split
        cursor = stop
    if cursor != trajectories_per_mode or any(not value for value in assignments):
        raise RuntimeError("pair split assignment is incomplete")
    return tuple(assignments)


def _opaque_id(manager: SeedManager, *namespace: object) -> str:
    return manager.rng("opaque-id", *namespace).bytes(16).hex()


def _validate_modes(
    modes: Mapping[str, IBRModeParams] | Sequence[IBRModeParams],
) -> tuple[IBRModeParams, ...]:
    if isinstance(modes, Mapping):
        normalized: list[IBRModeParams] = []
        for name, params in modes.items():
            if not isinstance(params, IBRModeParams):
                raise TypeError("every mode must be an IBRModeParams instance")
            if str(name) != params.name:
                raise ValueError("mode mapping key must match IBRModeParams.name")
            normalized.append(params)
    else:
        normalized = list(modes)
        if any(not isinstance(item, IBRModeParams) for item in normalized):
            raise TypeError("every mode must be an IBRModeParams instance")
    if not normalized:
        raise ValueError("at least one known mode is required")
    names = [item.name for item in normalized]
    if len(names) != len(set(names)):
        raise ValueError("known mode names must be unique")
    if any(item.delay_profile is not None for item in normalized):
        raise ValueError("known-mode identification data must use fixed delays")
    return tuple(sorted(normalized, key=lambda item: item.name))


def generate_identification_dataset(
    modes: Mapping[str, IBRModeParams] | Sequence[IBRModeParams],
    config: IdentificationGenerationConfig,
) -> IdentificationGenerationResult:
    """Generate a deterministic fixed-mode dataset with no public truth labels.

    Each pair index generates one excitation exactly once.  That same command
    and frequency array is then applied to every known truth mode.  Complete
    pairs share a trajectory-level split, preventing time-point leakage and
    making excitation distributions identical across modes.
    """

    if not isinstance(config, IdentificationGenerationConfig):
        raise TypeError("config must be an IdentificationGenerationConfig")
    known_modes = _validate_modes(modes)
    manager = SeedManager(config.master_seed)
    pair_splits = deterministic_pair_splits(
        config.trajectories_per_mode,
        config.split_counts_per_mode,
        master_seed=config.master_seed,
    )

    trajectories: list[IdentificationTrajectory] = []
    private_metadata: list[PrivateTrajectoryMetadata] = []
    audits: list[TrajectoryAudit] = []
    identifiers: set[str] = set()
    for pair_index in range(config.trajectories_per_mode):
        family = EXCITATION_FAMILIES[pair_index % len(EXCITATION_FAMILIES)]
        excitation_seed = manager.seed("excitation", pair_index)
        signals = generate_safe_excitation(
            config,
            family=family,
            seed=excitation_seed,
        )
        signal_digest = excitation_sha256(signals)
        pair_id = _opaque_id(manager, "excitation-pair", pair_index)
        split = pair_splits[pair_index]
        for params in known_modes:
            trajectory_id = _opaque_id(
                manager, "trajectory", pair_index, params.name
            )
            if trajectory_id in identifiers:
                raise RuntimeError("opaque trajectory ID collision")
            identifiers.add(trajectory_id)
            trajectory_seed = manager.seed(
                "trajectory-measurement", pair_index, params.name
            )
            trajectory = simulate_identification_trajectory(
                params,
                signals,
                config,
                trajectory_id=trajectory_id,
                measurement_seed=trajectory_seed,
            )
            audit = audit_identification_trajectory(trajectory, config)
            if not audit.passed:
                raise RuntimeError(
                    "generated trajectory failed safety/conditioning audit: "
                    f"{trajectory_id}: {audit}"
                )
            trajectories.append(trajectory)
            audits.append(audit)
            private_metadata.append(
                PrivateTrajectoryMetadata(
                    trajectory_id=trajectory_id,
                    mode_name_eval_only=params.name,
                    trajectory_seed_eval_only=trajectory_seed,
                    excitation_pair_id_eval_only=pair_id,
                    excitation_family_eval_only=family,
                    split=split,
                    excitation_sha256=signal_digest,
                )
            )

    # The public in-memory order is independently permuted after generation, so
    # neither mode loop order nor excitation-pair order is observable.
    public_order_rng = manager.rng("public-trajectory-order")
    order = public_order_rng.permutation(len(trajectories))
    public_trajectories = tuple(trajectories[int(index)] for index in order)
    private_by_id = {item.trajectory_id: item for item in private_metadata}
    audit_by_id = {item.trajectory_id: item for item in audits}
    assignments = tuple(
        sorted(
            (
                (item.trajectory_id, item.split)
                for item in private_metadata
            ),
            key=lambda item: item[0],
        )
    )
    return IdentificationGenerationResult(
        public_trajectories=public_trajectories,
        public_split_assignments=assignments,
        private_evaluation_metadata=tuple(
            private_by_id[trajectory_id] for trajectory_id, _ in assignments
        ),
        private_audits=tuple(
            audit_by_id[trajectory_id] for trajectory_id, _ in assignments
        ),
        generation_config=config,
    )


def _json_write(value: Any, path: Path) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _validate_source_hashes(source_hashes: Mapping[str, str] | None) -> dict[str, str]:
    if source_hashes is None:
        return {}
    normalized: dict[str, str] = {}
    for name, digest in source_hashes.items():
        if not isinstance(name, str) or not name:
            raise ValueError("source hash names must be non-empty strings")
        if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
            raise ValueError("source hashes must be lowercase SHA-256 digests")
        normalized[name] = digest
    return dict(sorted(normalized.items()))


def write_identification_dataset(
    result: IdentificationGenerationResult,
    output_directory: str | Path,
    *,
    source_hashes: Mapping[str, str] | None = None,
) -> WrittenIdentificationDataset:
    """Write public Parquet data and private evaluation truth separately.

    The public split manifest has exactly three whitelisted columns: opaque
    trajectory ID, split, and the corresponding Parquet file SHA-256.
    """

    if not isinstance(result, IdentificationGenerationResult):
        raise TypeError("result must be an IdentificationGenerationResult")
    output = Path(output_directory).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    public_directory = output / "public"
    private_directory = output / "private"
    trajectory_directory = public_directory / "trajectories"
    trajectory_directory.mkdir(parents=True)
    private_directory.mkdir(parents=True)

    split_by_id = result.split_by_trajectory_id
    split_rows: list[dict[str, str]] = []
    for trajectory in sorted(
        result.public_trajectories, key=lambda item: item.trajectory_id
    ):
        frame = trajectory.to_frame()
        if tuple(frame.columns) != PUBLIC_SAMPLE_COLUMNS:
            raise RuntimeError("public serializer attempted a non-whitelisted column")
        path = trajectory_directory / f"{trajectory.trajectory_id}.parquet"
        frame.to_parquet(path, index=False, engine="pyarrow", compression="zstd")
        split_rows.append(
            {
                "trajectory_id": trajectory.trajectory_id,
                "split": split_by_id[trajectory.trajectory_id],
                "sha256": sha256_file(path),
            }
        )

    split_manifest_path = public_directory / "split_manifest.csv"
    with split_manifest_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=PUBLIC_SPLIT_COLUMNS)
        writer.writeheader()
        writer.writerows(split_rows)
    split_counts = Counter(row["split"] for row in split_rows)
    public_manifest = {
        "schema_version": SCHEMA_VERSION,
        "sample_columns": list(PUBLIC_SAMPLE_COLUMNS),
        "split_columns": list(PUBLIC_SPLIT_COLUMNS),
        "split_names": list(SPLIT_NAMES),
        "trajectory_count": len(split_rows),
        "split_counts": {
            name: int(split_counts.get(name, 0)) for name in SPLIT_NAMES
        },
        "split_manifest_sha256": sha256_file(split_manifest_path),
        "trajectory_manifest_sha256": sha256_json(split_rows),
    }
    public_manifest["dataset_sha256"] = sha256_json(public_manifest)
    public_manifest_path = public_directory / "public_manifest.json"
    _json_write(public_manifest, public_manifest_path)

    private_metadata_path = private_directory / "evaluation_metadata.json"
    private_rows = [
        asdict(item)
        for item in sorted(
            result.private_evaluation_metadata,
            key=lambda item: item.trajectory_id,
        )
    ]
    _json_write(private_rows, private_metadata_path)
    private_audit_path = private_directory / "generation_audits.json"
    audit_rows = [
        {**asdict(item), "passed": item.passed}
        for item in sorted(result.private_audits, key=lambda item: item.trajectory_id)
    ]
    _json_write(audit_rows, private_audit_path)
    mode_counts = Counter(
        item.mode_name_eval_only for item in result.private_evaluation_metadata
    )
    private_manifest = {
        "schema_version": SCHEMA_VERSION,
        "truth_access": "evaluation_only",
        "generation_config": asdict(result.generation_config),
        "mode_counts_eval_only": dict(sorted(mode_counts.items())),
        "source_hashes": _validate_source_hashes(source_hashes),
        "hashes": {
            "public_manifest_sha256": sha256_file(public_manifest_path),
            "evaluation_metadata_sha256": sha256_file(private_metadata_path),
            "generation_audits_sha256": sha256_file(private_audit_path),
        },
    }
    private_manifest_path = private_directory / "private_manifest.json"
    _json_write(private_manifest, private_manifest_path)
    return WrittenIdentificationDataset(
        output_directory=output,
        public_directory=public_directory,
        private_directory=private_directory,
        public_manifest_sha256=sha256_file(public_manifest_path),
        private_metadata_sha256=sha256_file(private_metadata_path),
        dataset_sha256=str(public_manifest["dataset_sha256"]),
        trajectory_count=len(split_rows),
    )


def load_public_identification_data(
    public_directory: str | Path,
    *,
    split: str | None = None,
    verify_hashes: bool = True,
) -> tuple[IdentificationTrajectory, ...]:
    """Load a fully authenticated public dataset without opening private files.

    ``verify_hashes`` controls the comparatively expensive hash of every
    Parquet payload.  The small manifest, logical-manifest, and dataset hashes
    are always checked: disabling those checks would make schema validation
    depend on unauthenticated metadata.
    """

    raw_directory = Path(public_directory).expanduser()
    if raw_directory.is_symlink():
        raise ValueError("public dataset directory must not be a symbolic link")
    directory = raw_directory.resolve()
    if not directory.is_dir():
        raise NotADirectoryError(directory)
    if split is not None and split not in SPLIT_NAMES:
        raise ValueError(f"unknown split: {split!r}")
    if not isinstance(verify_hashes, bool):
        raise TypeError("verify_hashes must be a boolean")

    public_manifest_path = directory / "public_manifest.json"
    split_manifest_path = directory / "split_manifest.csv"
    trajectory_directory = directory / "trajectories"
    for path, description in (
        (public_manifest_path, "public manifest"),
        (split_manifest_path, "split manifest"),
    ):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"{description} must be a regular file")
    if trajectory_directory.is_symlink() or not trajectory_directory.is_dir():
        raise ValueError("public trajectory directory must be a regular directory")

    public_manifest = _read_strict_json_object(public_manifest_path)
    _validate_public_manifest_schema(public_manifest)
    if sha256_file(split_manifest_path) != public_manifest["split_manifest_sha256"]:
        raise ValueError("public split manifest hash mismatch")

    with split_manifest_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != PUBLIC_SPLIT_COLUMNS:
            raise ValueError("public split manifest contains non-whitelisted columns")
        rows = list(reader)

    normalized_rows = _validate_public_split_rows(rows)
    _validate_public_manifest_contents(public_manifest, normalized_rows)
    paths_by_id = _validate_trajectory_directory(
        trajectory_directory,
        tuple(row["trajectory_id"] for row in normalized_rows),
    )
    if verify_hashes:
        for row in normalized_rows:
            trajectory_id = row["trajectory_id"]
            if sha256_file(paths_by_id[trajectory_id]) != row["sha256"]:
                raise ValueError(f"trajectory hash mismatch: {trajectory_id}")
    _validate_trajectory_schemas(paths_by_id)

    selected = [
        row for row in normalized_rows if split is None or row["split"] == split
    ]
    trajectories: list[IdentificationTrajectory] = []
    for row in selected:
        trajectory_id = row["trajectory_id"]
        path = paths_by_id[trajectory_id]
        frame = pd.read_parquet(path, engine="pyarrow")
        trajectory = IdentificationTrajectory.from_frame(frame)
        if trajectory.trajectory_id != trajectory_id:
            raise ValueError("trajectory file ID does not match split manifest")
        trajectories.append(trajectory)
    return tuple(trajectories)


def _read_strict_json_object(path: Path) -> dict[str, Any]:
    """Read JSON while rejecting duplicate keys and non-standard constants."""

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key in public manifest: {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant in public manifest: {value}")

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("public manifest is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("public manifest root must be a JSON object")
    return value


def _is_plain_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _validate_public_manifest_schema(manifest: Mapping[str, Any]) -> None:
    fields = set(manifest)
    if fields != _PUBLIC_MANIFEST_FIELDS:
        raise ValueError(
            "public manifest fields must exactly match the whitelist; "
            f"missing={sorted(_PUBLIC_MANIFEST_FIELDS - fields)}, "
            f"unknown={sorted(fields - _PUBLIC_MANIFEST_FIELDS)}"
        )
    if not _is_plain_integer(manifest["schema_version"]):
        raise ValueError("public manifest schema_version must be an integer")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError(
            "unsupported public manifest schema_version: "
            f"{manifest['schema_version']!r}"
        )
    for name, expected in (
        ("sample_columns", PUBLIC_SAMPLE_COLUMNS),
        ("split_columns", PUBLIC_SPLIT_COLUMNS),
        ("split_names", SPLIT_NAMES),
    ):
        value = manifest[name]
        if not isinstance(value, list) or value != list(expected):
            raise ValueError(f"public manifest {name} does not match the whitelist")
    count = manifest["trajectory_count"]
    if not _is_plain_integer(count) or count < 0:
        raise ValueError("public manifest trajectory_count must be non-negative")
    split_counts = manifest["split_counts"]
    if not isinstance(split_counts, dict) or set(split_counts) != set(SPLIT_NAMES):
        raise ValueError("public manifest split_counts has invalid fields")
    if any(
        not _is_plain_integer(split_counts[name]) or split_counts[name] < 0
        for name in SPLIT_NAMES
    ):
        raise ValueError("public manifest split_counts must be non-negative integers")
    for name in (
        "split_manifest_sha256",
        "trajectory_manifest_sha256",
        "dataset_sha256",
    ):
        _validate_sha256(manifest[name], f"public manifest {name}")


def _validate_public_split_rows(
    rows: Sequence[Mapping[str | None, str | list[str] | None]],
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    identifiers: set[str] = set()
    for row_index, row in enumerate(rows, start=2):
        if set(row) != set(PUBLIC_SPLIT_COLUMNS):
            raise ValueError(f"split manifest row {row_index} has an invalid shape")
        values = {name: row[name] for name in PUBLIC_SPLIT_COLUMNS}
        if any(not isinstance(value, str) for value in values.values()):
            raise ValueError(f"split manifest row {row_index} has a missing field")
        trajectory_id = values["trajectory_id"]
        split = values["split"]
        digest = values["sha256"]
        assert isinstance(trajectory_id, str)
        assert isinstance(split, str)
        assert isinstance(digest, str)
        if _OPAQUE_ID_PATTERN.fullmatch(trajectory_id) is None:
            raise ValueError(
                f"split manifest row {row_index} has an invalid trajectory_id"
            )
        if trajectory_id in identifiers:
            raise ValueError(f"duplicate trajectory_id in split manifest: {trajectory_id}")
        if split not in SPLIT_NAMES:
            raise ValueError(f"split manifest row {row_index} has an invalid split")
        _validate_sha256(digest, f"split manifest row {row_index} sha256")
        identifiers.add(trajectory_id)
        normalized.append(
            {"trajectory_id": trajectory_id, "split": split, "sha256": digest}
        )
    if [row["trajectory_id"] for row in normalized] != sorted(identifiers):
        raise ValueError("split manifest rows must be sorted by trajectory_id")
    return normalized


def _validate_public_manifest_contents(
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, str]],
) -> None:
    if manifest["trajectory_count"] != len(rows):
        raise ValueError("public manifest trajectory_count does not match split manifest")
    actual_counts = Counter(row["split"] for row in rows)
    expected_counts = {name: int(actual_counts.get(name, 0)) for name in SPLIT_NAMES}
    if manifest["split_counts"] != expected_counts:
        raise ValueError("public manifest split_counts does not match split manifest")
    if sum(expected_counts.values()) != manifest["trajectory_count"]:
        raise ValueError("public manifest split counts do not cover every trajectory")
    if sha256_json(rows) != manifest["trajectory_manifest_sha256"]:
        raise ValueError("public trajectory manifest logical hash mismatch")
    dataset_fields = {
        key: value for key, value in manifest.items() if key != "dataset_sha256"
    }
    if sha256_json(dataset_fields) != manifest["dataset_sha256"]:
        raise ValueError("public dataset logical hash mismatch")


def _validate_trajectory_directory(
    trajectory_directory: Path,
    trajectory_ids: Sequence[str],
) -> dict[str, Path]:
    expected_names = {f"{trajectory_id}.parquet" for trajectory_id in trajectory_ids}
    actual_relative_names: set[str] = set()
    for path in trajectory_directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("public trajectory directory must not contain symlinks")
        if path.is_file() and path.suffix.lower() == ".parquet":
            actual_relative_names.add(path.relative_to(trajectory_directory).as_posix())
    missing = expected_names - actual_relative_names
    extra = actual_relative_names - expected_names
    if missing or extra:
        raise ValueError(
            "public trajectory directory does not match split manifest; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    resolved_directory = trajectory_directory.resolve()
    paths: dict[str, Path] = {}
    for trajectory_id in trajectory_ids:
        path = trajectory_directory / f"{trajectory_id}.parquet"
        resolved_path = path.resolve()
        if resolved_path.parent != resolved_directory or not resolved_path.is_file():
            raise ValueError(f"invalid trajectory path for {trajectory_id}")
        paths[trajectory_id] = resolved_path
    return paths


def _validate_trajectory_schemas(paths_by_id: Mapping[str, Path]) -> None:
    for path in paths_by_id.values():
        if tuple(pq.read_schema(path).names) != PUBLIC_SAMPLE_COLUMNS:
            raise ValueError(
                "public trajectory columns must exactly match "
                f"{PUBLIC_SAMPLE_COLUMNS}"
            )


__all__ = [
    "IdentificationGenerationResult",
    "WrittenIdentificationDataset",
    "deterministic_pair_splits",
    "generate_identification_dataset",
    "generation_config_from_base_config",
    "load_public_identification_data",
    "proportional_split_counts",
    "write_identification_dataset",
]
