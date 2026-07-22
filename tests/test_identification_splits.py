"""Trajectory-level split, manifest, and integrity-hash tests."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from d5freq.data import (
    EXCITATION_FAMILIES,
    PUBLIC_SPLIT_COLUMNS,
    IdentificationGenerationConfig,
    SplitCounts,
    deterministic_pair_splits,
    generate_identification_dataset,
    load_public_identification_data,
    write_identification_dataset,
)
from d5freq.models.hidden_mode_ibr import IBRModeParams


def _config() -> IdentificationGenerationConfig:
    return IdentificationGenerationConfig(
        master_seed=20260722,
        trajectories_per_mode=4,
        trajectory_duration_s=20.0,
        control_period_s=0.5,
        integration_step_s=0.05,
        f0_hz=50.0,
        command_abs_limit_pu=0.06,
        command_rate_limit_pu_per_s=0.03,
        frequency_abs_limit_hz=0.10,
        power_measurement_noise_std_pu=2.0e-4,
        minimum_command_std_pu=2.0e-3,
        minimum_frequency_std_hz=2.0e-3,
        maximum_regression_condition_number=1.0e10,
        split_counts_per_mode=SplitCounts(1, 1, 1, 1),
    )


def _mode(name: str, gain: float) -> IBRModeParams:
    return IBRModeParams(
        name=name,
        command_gain=gain,
        frequency_gain=3.0,
        command_filter_time_s=0.2,
        power_response_time_s=0.3,
        delay_s=0.1,
        p_max_pos_pu=0.08,
        p_max_neg_pu=0.08,
        ramp_up_pu_per_s=0.05,
        ramp_down_pu_per_s=0.05,
        deadband_pu=0.0005,
    )


def _result():
    return generate_identification_dataset(
        {
            "resource_a": _mode("resource_a", 1.0),
            "resource_b": _mode("resource_b", 0.75),
        },
        _config(),
    )


def test_required_40_trajectory_split_is_exact_and_family_balanced() -> None:
    counts = SplitCounts(train=24, validation=8, ood_calibration=4, test=4)
    first = deterministic_pair_splits(40, counts, master_seed=20260722)
    second = deterministic_pair_splits(40, counts, master_seed=20260722)

    assert first == second
    assert {name: first.count(name) for name in counts.as_dict()} == counts.as_dict()
    expected_per_family = {
        "train": 6,
        "validation": 2,
        "ood_calibration": 1,
        "test": 1,
    }
    for family_index, _ in enumerate(EXCITATION_FAMILIES):
        selected = [first[index] for index in range(family_index, 40, 4)]
        assert {
            name: selected.count(name) for name in expected_per_family
        } == expected_per_family


def test_complete_excitation_pairs_never_cross_trajectory_splits() -> None:
    result = _result()
    pair_splits: dict[str, set[str]] = {}
    per_mode_counts: dict[str, dict[str, int]] = {}
    for metadata in result.private_evaluation_metadata:
        pair_splits.setdefault(metadata.excitation_pair_id_eval_only, set()).add(
            metadata.split
        )
        mode_counts = per_mode_counts.setdefault(
            metadata.mode_name_eval_only,
            {name: 0 for name in result.generation_config.split_counts_per_mode.as_dict()},
        )
        mode_counts[metadata.split] += 1

    assert all(len(splits) == 1 for splits in pair_splits.values())
    assert all(
        counts == result.generation_config.split_counts_per_mode.as_dict()
        for counts in per_mode_counts.values()
    )


def test_generation_is_bitwise_deterministic_for_same_seed() -> None:
    first = _result()
    second = _result()
    first_by_id = {item.trajectory_id: item for item in first.public_trajectories}
    second_by_id = {item.trajectory_id: item for item in second.public_trajectories}

    assert first.public_split_assignments == second.public_split_assignments
    assert first.private_evaluation_metadata == second.private_evaluation_metadata
    assert first_by_id.keys() == second_by_id.keys()
    for trajectory_id in first_by_id:
        left = first_by_id[trajectory_id]
        right = second_by_id[trajectory_id]
        np.testing.assert_array_equal(left.time_s, right.time_s)
        np.testing.assert_array_equal(left.u_ibr_pu, right.u_ibr_pu)
        np.testing.assert_array_equal(left.omega_pu, right.omega_pu)
        np.testing.assert_array_equal(left.p_ibr_pu, right.p_ibr_pu)


def test_public_split_manifest_hashes_every_parquet_file(tmp_path: Path) -> None:
    result = _result()
    written = write_identification_dataset(result, tmp_path)
    split_path = written.public_directory / "split_manifest.csv"
    with split_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)

    assert tuple(reader.fieldnames or ()) == PUBLIC_SPLIT_COLUMNS
    assert len(rows) == len(result.public_trajectories)
    assert all(len(row["sha256"]) == 64 for row in rows)
    loaded = load_public_identification_data(
        written.public_directory, split="train", verify_hashes=True
    )
    assert len(loaded) == 2
    assert all(
        result.split_by_trajectory_id[item.trajectory_id] == "train"
        for item in loaded
    )

    first_path = (
        written.public_directory
        / "trajectories"
        / f"{rows[0]['trajectory_id']}.parquet"
    )
    with first_path.open("ab") as stream:
        stream.write(b"tampered")
    try:
        load_public_identification_data(written.public_directory)
    except ValueError as exc:
        assert "hash mismatch" in str(exc)
    else:  # pragma: no cover - the branch documents the integrity contract.
        raise AssertionError("tampered Parquet data was accepted")
