from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pytest

from d5freq.data import IdentificationTrajectory


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "phase3_gmm_regularization_sensitivity.py"


def _load_script_module():
    specification = importlib.util.spec_from_file_location(
        "phase3_gmm_regularization_sensitivity_test_target",
        SCRIPT_PATH,
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


AUDIT = _load_script_module()


def _episode(identifier: int, theta: np.ndarray, *, seed: int) -> IdentificationTrajectory:
    rng = np.random.default_rng(seed)
    sample_count = 100
    command = rng.uniform(-0.055, 0.055, size=sample_count)
    omega = rng.uniform(-0.0018, 0.0018, size=sample_count)
    power = np.zeros(sample_count, dtype=np.float64)
    power[:2] = rng.normal(scale=1.0e-4, size=2)
    noise_scale = 1.0e-5 * (1.0 + 0.04 * (identifier % 5))
    for index in range(1, sample_count - 1):
        regressor = np.array(
            [
                power[index],
                power[index - 1],
                command[index],
                command[index - 1],
                omega[index],
                omega[index - 1],
                1.0,
            ]
        )
        power[index + 1] = float(
            theta @ regressor + rng.normal(scale=noise_scale)
        )
    return IdentificationTrajectory(
        trajectory_id=f"{identifier:032x}",
        time_s=np.arange(sample_count, dtype=np.float64) * 0.5,
        u_ibr_pu=command,
        omega_pu=omega,
        p_ibr_pu=power,
    )


def _training_episodes() -> tuple[IdentificationTrajectory, ...]:
    first = np.array([0.58, -0.05, 0.24, 0.02, -0.20, 0.05, 0.0])
    second = np.array([0.30, 0.10, 0.05, -0.01, -0.50, -0.05, 0.001])
    return tuple(
        [_episode(index + 1, first, seed=100 + index) for index in range(6)]
        + [_episode(index + 101, second, seed=200 + index) for index in range(6)]
    )


def _base_config() -> dict[str, object]:
    return {
        "schema_version": 1,
        "project": {"seed": 20260722},
        "identification": {
            "arx_order_y": 2,
            "arx_order_u": 2,
            "arx_order_f": 2,
            "ridge_lambda": 1.0e-7,
            "feature_variance_epsilon": 1.0e-12,
            "residual_variance_floor": 1.0e-12,
            "gmm_k_min": 1,
            "gmm_k_max": 3,
            "gmm_restarts": 2,
            "gmm_covariance_type": "diag",
            "gmm_max_iter": 200,
            "gmm_reg_covar": 1.0e-5,
        },
    }


def test_audit_is_source_isolated_and_cli_loads_only_train() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    lowered = source.lower()
    assert all(word not in lowered for word in ("private", "truth", "evaluation"))
    assert "mode_library" not in lowered
    assert "pca" not in lowered

    tree = ast.parse(source)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.append(node.module or "")
    assert all(not name.startswith("d5freq.evaluation") for name in imported_modules)

    loader_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "load_public_identification_data"
    ]
    assert len(loader_calls) == 1
    keywords = {keyword.arg: keyword.value for keyword in loader_calls[0].keywords}
    assert isinstance(keywords["split"], ast.Constant)
    assert keywords["split"].value == "train"
    assert isinstance(keywords["verify_hashes"], ast.Constant)
    assert keywords["verify_hashes"].value is True
    assert AUDIT.REGULARIZATION_GRID == (1.0e-5, 1.0e-4, 1.0e-3, 1.0e-2)


def test_audit_writes_only_diagnostic_csv_and_summary_and_preserves_sentinel(
    tmp_path: Path,
) -> None:
    operational_directory = tmp_path / "operational"
    operational_directory.mkdir()
    sentinel = operational_directory / "mode_library.json"
    sentinel_payload = b'{"sentinel":"must-remain-byte-identical"}\n'
    sentinel.write_bytes(sentinel_payload)

    result = AUDIT.run_sensitivity_audit(
        _training_episodes(),
        _base_config(),
        tmp_path / "sensitivity",
    )

    assert sentinel.read_bytes() == sentinel_payload
    assert {path.name for path in result.output_directory.iterdir()} == {
        AUDIT.CSV_FILENAME,
        AUDIT.SUMMARY_FILENAME,
    }
    assert not (result.output_directory / "mode_library.json").exists()

    with result.bic_table_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    assert tuple(reader.fieldnames or ()) == AUDIT.CSV_COLUMNS
    assert len(rows) == len(AUDIT.REGULARIZATION_GRID) * 3
    assert {float(row["reg_covar"]) for row in rows} == set(
        AUDIT.REGULARIZATION_GRID
    )
    for regularizer in AUDIT.REGULARIZATION_GRID:
        block = [row for row in rows if float(row["reg_covar"]) == regularizer]
        assert [int(row["K"]) for row in block] == [1, 2, 3]
        selected = [row for row in block if row["selected_for_that_reg"] == "true"]
        assert len(selected) == 1
        assert float(selected[0]["delta_bic"]) == pytest.approx(0.0)
        assert all(row["converged"] in {"true", "false"} for row in block)

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["scope"] == "diagnostic_only"
    assert summary["authoritative_model_selection"] is False
    assert summary["source_split"] == "train"
    assert summary["feature_dimension"] == 8
    assert summary["training_episode_count"] == len(_training_episodes())
    assert summary["regularization_grid"] == list(AUDIT.REGULARIZATION_GRID)
    assert summary["base_reg_covar"] == pytest.approx(1.0e-5)
    assert summary["fixed_gmm_settings"] == {
        "k_min": 1,
        "k_max": 3,
        "covariance_type": "diag",
        "n_init": 2,
        "random_seed": 20260722,
        "max_iter": 200,
    }
    assert summary["scaler"]["n_samples_seen"] == len(_training_episodes())
    assert len(summary["standardized_training_features_sha256"]) == 64
    assert len(summary["within_setting_selections"]) == len(
        AUDIT.REGULARIZATION_GRID
    )


def test_nonempty_output_is_rejected_without_touching_sentinel(tmp_path: Path) -> None:
    output = tmp_path / "already-populated"
    output.mkdir()
    sentinel = output / "mode_library.json"
    sentinel_payload = b"sentinel-library-content\n"
    sentinel.write_bytes(sentinel_payload)

    with pytest.raises(FileExistsError, match="not empty"):
        AUDIT.run_sensitivity_audit(
            _training_episodes(),
            _base_config(),
            output,
        )

    assert sentinel.read_bytes() == sentinel_payload
    assert {path.name for path in output.iterdir()} == {"mode_library.json"}
