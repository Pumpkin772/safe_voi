"""Adversarial integrity tests for the public identification-data loader."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pytest

from d5freq.data import (
    PUBLIC_SPLIT_COLUMNS,
    IdentificationGenerationConfig,
    IdentificationGenerationResult,
    IdentificationTrajectory,
    PrivateTrajectoryMetadata,
    SplitCounts,
    TrajectoryAudit,
    load_public_identification_data,
    write_identification_dataset,
)
from d5freq.utils.hashing import sha256_file, sha256_json


def _write_fixture(tmp_path: Path):
    config = IdentificationGenerationConfig(
        master_seed=17,
        trajectories_per_mode=4,
        trajectory_duration_s=2.0,
        control_period_s=0.5,
        integration_step_s=0.05,
        f0_hz=50.0,
        command_abs_limit_pu=0.06,
        command_rate_limit_pu_per_s=0.03,
        frequency_abs_limit_hz=0.10,
        power_measurement_noise_std_pu=0.0,
        minimum_command_std_pu=1.0e-4,
        minimum_frequency_std_hz=1.0e-4,
        maximum_regression_condition_number=1.0e10,
        split_counts_per_mode=SplitCounts(1, 1, 1, 1),
    )
    splits = ("train", "validation", "ood_calibration", "test")
    time = np.arange(5, dtype=float) * 0.5
    trajectories = []
    metadata = []
    audits = []
    assignments = []
    for index, split in enumerate(splits, start=1):
        trajectory_id = f"{index:032x}"
        trajectory = IdentificationTrajectory(
            trajectory_id=trajectory_id,
            time_s=time,
            u_ibr_pu=np.linspace(-0.01, 0.01, len(time)) + index * 1.0e-4,
            omega_pu=np.linspace(0.001, -0.001, len(time)),
            p_ibr_pu=np.linspace(-0.005, 0.006, len(time)),
        )
        trajectories.append(trajectory)
        assignments.append((trajectory_id, split))
        metadata.append(
            PrivateTrajectoryMetadata(
                trajectory_id=trajectory_id,
                mode_name_eval_only="hidden",
                trajectory_seed_eval_only=index,
                excitation_pair_id_eval_only=f"{index + 100:032x}",
                excitation_family_eval_only="prbs",
                split=split,
                excitation_sha256="a" * 64,
            )
        )
        audits.append(
            TrajectoryAudit(
                trajectory_id=trajectory_id,
                max_abs_command_pu=0.01,
                max_abs_command_rate_pu_per_s=0.01,
                max_abs_frequency_hz=0.05,
                command_std_pu=0.01,
                frequency_std_hz=0.01,
                regression_condition_number=10.0,
                command_amplitude_safe=True,
                command_rate_safe=True,
                frequency_safe=True,
                command_excitation_sufficient=True,
                frequency_excitation_sufficient=True,
                regression_conditioning_safe=True,
            )
        )
    result = IdentificationGenerationResult(
        public_trajectories=tuple(trajectories),
        public_split_assignments=tuple(assignments),
        private_evaluation_metadata=tuple(metadata),
        private_audits=tuple(audits),
        generation_config=config,
    )
    return write_identification_dataset(result, tmp_path / "dataset")


def _read_rows(public_directory: Path) -> list[dict[str, str]]:
    with (public_directory / "split_manifest.csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        return list(csv.DictReader(stream))


def _write_rows(public_directory: Path, rows: list[dict[str, str]]) -> None:
    with (public_directory / "split_manifest.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=PUBLIC_SPLIT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _read_manifest(public_directory: Path) -> dict[str, object]:
    return json.loads(
        (public_directory / "public_manifest.json").read_text(encoding="utf-8")
    )


def _write_manifest(public_directory: Path, manifest: dict[str, object]) -> None:
    (public_directory / "public_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _refresh_manifest(
    public_directory: Path, *, refresh_logical_hashes: bool = True
) -> None:
    manifest = _read_manifest(public_directory)
    split_path = public_directory / "split_manifest.csv"
    rows = _read_rows(public_directory)
    manifest["split_manifest_sha256"] = sha256_file(split_path)
    if refresh_logical_hashes:
        manifest["trajectory_manifest_sha256"] = sha256_json(rows)
        manifest["trajectory_count"] = len(rows)
        manifest["split_counts"] = {
            name: sum(row["split"] == name for row in rows)
            for name in ("train", "validation", "ood_calibration", "test")
        }
    manifest["dataset_sha256"] = sha256_json(
        {key: value for key, value in manifest.items() if key != "dataset_sha256"}
    )
    _write_manifest(public_directory, manifest)


def test_valid_public_dataset_loads_without_private_tree(tmp_path: Path) -> None:
    written = _write_fixture(tmp_path)
    shutil.rmtree(written.private_directory)

    trajectories = load_public_identification_data(written.public_directory)

    assert len(trajectories) == 4


@pytest.mark.parametrize("mutation", ["unknown_field", "missing_field", "version"])
def test_public_manifest_schema_and_version_are_strict(
    tmp_path: Path, mutation: str
) -> None:
    public_directory = _write_fixture(tmp_path).public_directory
    manifest = _read_manifest(public_directory)
    if mutation == "unknown_field":
        manifest["truth"] = "forbidden"
    elif mutation == "missing_field":
        del manifest["split_names"]
    else:
        manifest["schema_version"] = 2
    _write_manifest(public_directory, manifest)

    with pytest.raises(ValueError, match="whitelist|schema_version"):
        load_public_identification_data(public_directory)


def test_public_manifest_duplicate_json_key_is_rejected(tmp_path: Path) -> None:
    public_directory = _write_fixture(tmp_path).public_directory
    path = public_directory / "public_manifest.json"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            '"schema_version": 1,',
            '"schema_version": 1,\n  "schema_version": 1,',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_public_identification_data(public_directory)


def test_split_manifest_file_hash_is_always_verified(tmp_path: Path) -> None:
    public_directory = _write_fixture(tmp_path).public_directory
    with (public_directory / "split_manifest.csv").open(
        "a", encoding="utf-8", newline=""
    ) as stream:
        stream.write("\n")

    with pytest.raises(ValueError, match="split manifest hash mismatch"):
        load_public_identification_data(public_directory, verify_hashes=False)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("path_traversal", "invalid trajectory_id"),
        ("duplicate", "duplicate trajectory_id"),
        ("bad_split", "invalid split"),
        ("bad_sha", "lowercase SHA-256"),
    ],
)
def test_split_manifest_rows_reject_unsafe_or_ambiguous_values(
    tmp_path: Path, mutation: str, message: str
) -> None:
    public_directory = _write_fixture(tmp_path).public_directory
    rows = _read_rows(public_directory)
    if mutation == "path_traversal":
        rows[0]["trajectory_id"] = "../private/evaluation_metadata"
    elif mutation == "duplicate":
        rows[1]["trajectory_id"] = rows[0]["trajectory_id"]
    elif mutation == "bad_split":
        rows[0]["split"] = "training"
    else:
        rows[0]["sha256"] = "A" * 64
    _write_rows(public_directory, rows)
    _refresh_manifest(public_directory, refresh_logical_hashes=False)

    with pytest.raises(ValueError, match=message):
        load_public_identification_data(public_directory)


def test_split_manifest_unknown_column_is_rejected(tmp_path: Path) -> None:
    public_directory = _write_fixture(tmp_path).public_directory
    path = public_directory / "split_manifest.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(
        "\n".join([lines[0] + ",truth", *[line + ",x" for line in lines[1:]]])
        + "\n",
        encoding="utf-8",
    )
    _refresh_manifest(public_directory, refresh_logical_hashes=False)

    with pytest.raises(ValueError, match="non-whitelisted columns"):
        load_public_identification_data(public_directory)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_trajectory_directory_must_exactly_match_manifest(
    tmp_path: Path, mutation: str
) -> None:
    public_directory = _write_fixture(tmp_path).public_directory
    paths = sorted((public_directory / "trajectories").glob("*.parquet"))
    if mutation == "missing":
        paths[0].rename(paths[0].with_suffix(".removed"))
    else:
        shutil.copyfile(paths[0], public_directory / "trajectories" / "extra.parquet")

    with pytest.raises(ValueError, match="does not match split manifest"):
        load_public_identification_data(public_directory)


def test_logical_trajectory_and_dataset_hashes_are_verified(tmp_path: Path) -> None:
    public_directory = _write_fixture(tmp_path).public_directory
    manifest = _read_manifest(public_directory)
    manifest["trajectory_manifest_sha256"] = "0" * 64
    manifest["dataset_sha256"] = sha256_json(
        {key: value for key, value in manifest.items() if key != "dataset_sha256"}
    )
    _write_manifest(public_directory, manifest)
    with pytest.raises(ValueError, match="trajectory manifest logical hash"):
        load_public_identification_data(public_directory)

    manifest = _read_manifest(public_directory)
    manifest["trajectory_manifest_sha256"] = sha256_json(
        _read_rows(public_directory)
    )
    manifest["dataset_sha256"] = "0" * 64
    _write_manifest(public_directory, manifest)
    with pytest.raises(ValueError, match="dataset logical hash"):
        load_public_identification_data(public_directory)


def test_unselected_trajectory_hash_is_still_verified(tmp_path: Path) -> None:
    public_directory = _write_fixture(tmp_path).public_directory
    test_row = next(row for row in _read_rows(public_directory) if row["split"] == "test")
    path = public_directory / "trajectories" / f"{test_row['trajectory_id']}.parquet"
    with path.open("ab") as stream:
        stream.write(b"tampered")

    with pytest.raises(ValueError, match="trajectory hash mismatch"):
        load_public_identification_data(public_directory, split="train")


def test_parquet_unknown_column_is_rejected_even_without_hash_check(
    tmp_path: Path,
) -> None:
    public_directory = _write_fixture(tmp_path).public_directory
    row = next(row for row in _read_rows(public_directory) if row["split"] == "test")
    path = public_directory / "trajectories" / f"{row['trajectory_id']}.parquet"
    frame = pd.read_parquet(path)
    frame["mode_truth"] = "forbidden"
    frame.to_parquet(path, index=False, engine="pyarrow", compression="zstd")

    with pytest.raises(ValueError, match="columns must exactly match"):
        load_public_identification_data(
            public_directory, split="train", verify_hashes=False
        )
