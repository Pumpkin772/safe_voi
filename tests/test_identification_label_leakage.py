"""Information-boundary tests for public identification artifacts."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pandas as pd

from d5freq.data import (
    PUBLIC_SAMPLE_COLUMNS,
    IdentificationGenerationConfig,
    SplitCounts,
    generate_identification_dataset,
    load_public_identification_data,
    write_identification_dataset,
)
from d5freq.models.hidden_mode_ibr import IBRModeParams


def _mode(name: str, time_constant_s: float) -> IBRModeParams:
    return IBRModeParams(
        name=name,
        command_gain=1.0,
        frequency_gain=4.0,
        command_filter_time_s=time_constant_s,
        power_response_time_s=2.0 * time_constant_s,
        delay_s=0.1,
        p_max_pos_pu=0.08,
        p_max_neg_pu=0.08,
        ramp_up_pu_per_s=0.05,
        ramp_down_pu_per_s=0.05,
        deadband_pu=0.0005,
    )


def _write_fixture(tmp_path: Path):
    config = IdentificationGenerationConfig(
        master_seed=8675309,
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
    result = generate_identification_dataset(
        {
            "nominal_hidden": _mode("nominal_hidden", 0.10),
            "sluggish_hidden": _mode("sluggish_hidden", 0.60),
        },
        config,
    )
    return result, write_identification_dataset(result, tmp_path)


def test_public_trajectory_object_and_table_have_only_whitelisted_fields(
    tmp_path: Path,
) -> None:
    result, written = _write_fixture(tmp_path)
    trajectory = result.public_trajectories[0]

    assert not hasattr(trajectory, "mode")
    assert not hasattr(trajectory, "true_mode")
    assert not hasattr(trajectory, "seed")
    assert not hasattr(trajectory, "family")
    assert tuple(trajectory.to_frame().columns) == PUBLIC_SAMPLE_COLUMNS

    parquet_paths = sorted(
        (written.public_directory / "trajectories").glob("*.parquet")
    )
    assert parquet_paths
    for path in parquet_paths:
        assert re.fullmatch(r"[0-9a-f]{32}\.parquet", path.name)
        assert tuple(pd.read_parquet(path).columns) == PUBLIC_SAMPLE_COLUMNS


def test_mode_names_and_seed_truth_exist_only_in_private_evaluation_metadata(
    tmp_path: Path,
) -> None:
    result, written = _write_fixture(tmp_path)
    truth_tokens = (
        "nominal_hidden",
        "sluggish_hidden",
        str(result.generation_config.master_seed),
    )
    public_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in written.public_directory.rglob("*")
        if path.suffix in {".json", ".csv"}
    )

    assert all(token not in public_text for token in truth_tokens)
    assert all(
        all(token not in path.name for token in truth_tokens)
        for path in written.public_directory.rglob("*")
    )
    private_path = written.private_directory / "evaluation_metadata.json"
    private_text = private_path.read_text(encoding="utf-8")
    assert "nominal_hidden" in private_text
    assert "sluggish_hidden" in private_text
    private_rows = json.loads(private_text)
    assert all("mode_name_eval_only" in row for row in private_rows)
    assert all("trajectory_seed_eval_only" in row for row in private_rows)


def test_public_loader_never_requires_the_private_truth_tree(tmp_path: Path) -> None:
    _, written = _write_fixture(tmp_path)
    hidden_private = written.output_directory / "private_not_visible_to_discovery"
    written.private_directory.rename(hidden_private)

    trajectories = load_public_identification_data(written.public_directory)

    assert len(trajectories) == 8
    assert all(re.fullmatch(r"[0-9a-f]{32}", item.trajectory_id) for item in trajectories)


def test_public_manifest_has_no_truth_bearing_keys(tmp_path: Path) -> None:
    _, written = _write_fixture(tmp_path)
    manifest = json.loads(
        (written.public_directory / "public_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    serialized_keys = " ".join(manifest).lower()

    for forbidden in ("mode", "seed", "family", "pair", "truth"):
        assert forbidden not in serialized_keys
