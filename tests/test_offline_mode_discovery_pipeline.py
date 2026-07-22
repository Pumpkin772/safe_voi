from __future__ import annotations

import json
import inspect
from pathlib import Path
import re
import runpy

import numpy as np
import pandas as pd
import pytest

from d5freq.data import IdentificationTrajectory
from d5freq.identification.mode_discovery import ModeDiscoveryConfig
from d5freq.identification.arx import validate_arx_multistep
from d5freq.identification.mode_discovery import evaluate_assigned_validation_episodes
from d5freq.identification.model_library import ModeLibrary
from d5freq.identification.offline_pipeline import (
    REQUIRED_LABEL_FREE_ARTIFACTS,
    OfflinePipelineConfig,
    offline_pipeline_config_from_base_config,
    propagate_grid_frequency_errors,
    run_label_free_mode_discovery,
)
from d5freq.evaluation.offline_mode_discovery_evaluation import (
    REQUIRED_MODE_DISCOVERY_ARTIFACTS,
    evaluate_discovery_with_private_metadata,
)
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.utils.hashing import sha256_file
from d5freq.utils.config import load_yaml


THETA_FIRST = np.array([0.72, -0.08, 0.24, 0.04, -0.65, 0.12, 0.0])
THETA_SECOND = np.array([0.28, 0.14, 0.035, -0.015, -0.12, -0.08, 0.0015])


def _episode(
    identifier: int,
    theta: np.ndarray,
    *,
    seed: int,
    sample_count: int = 110,
) -> IdentificationTrajectory:
    rng = np.random.default_rng(seed)
    u = rng.uniform(-0.055, 0.055, size=sample_count)
    omega = rng.uniform(-0.0018, 0.0018, size=sample_count)
    p = np.zeros(sample_count)
    p[:2] = rng.normal(scale=2.0e-4, size=2)
    for k in range(1, sample_count - 1):
        regressor = np.array(
            [p[k], p[k - 1], u[k], u[k - 1], omega[k], omega[k - 1], 1.0]
        )
        p[k + 1] = float(theta @ regressor + rng.normal(scale=2.0e-5))
    return IdentificationTrajectory(
        trajectory_id=f"{identifier:032x}",
        time_s=np.arange(sample_count, dtype=float) * 0.1,
        u_ibr_pu=u,
        omega_pu=omega,
        p_ibr_pu=p,
    )


def _pipeline_config() -> OfflinePipelineConfig:
    return OfflinePipelineConfig(
        grid_params=GridParams(
            f0_hz=50.0,
            M_s=8.0,
            D_pu=1.0,
            T_t_s=0.5,
            T_g_s=0.2,
            R_pu=0.08,
            control_period_s=0.1,
            integration_step_s=0.05,
        ),
        discovery=ModeDiscoveryConfig(
            ridge_lambda=1.0e-7,
            variance_epsilon=1.0e-12,
            residual_variance_floor=1.0e-12,
            k_min=1,
            k_max=2,
            covariance_type="diag",
            n_init=3,
            random_seed=20260722,
            max_iter=300,
            reg_covar=1.0e-5,
        ),
        multi_step_horizon=6,
        switch_epsilon=0.09,
    )


@pytest.fixture(scope="module")
def completed_pipeline(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("offline-mode-discovery")
    training = tuple(
        [_episode(index + 1, THETA_FIRST, seed=100 + index) for index in range(8)]
        + [
            _episode(index + 101, THETA_SECOND, seed=200 + index)
            for index in range(8)
        ]
    )
    validation = tuple(
        [_episode(index + 201, THETA_FIRST, seed=300 + index) for index in range(4)]
        + [
            _episode(index + 301, THETA_SECOND, seed=400 + index)
            for index in range(4)
        ]
    )
    output = root / "artifacts"
    run = run_label_free_mode_discovery(
        training,
        validation,
        config=_pipeline_config(),
        output_directory=output,
    )
    labels = {
        item.trajectory_id: ("physical-alpha" if index < 8 else "physical-beta")
        for index, item in enumerate(training)
    }
    labels.update(
        {
            item.trajectory_id: (
                "physical-alpha" if index < 4 else "physical-beta"
            )
            for index, item in enumerate(validation)
        }
    )
    metadata = [
        {
            "trajectory_id": item.trajectory_id,
            "mode_name_eval_only": labels[item.trajectory_id],
            "split": split,
        }
        for split, episodes in (("train", training), ("validation", validation))
        for item in episodes
    ]
    private_path = root / "private_metadata.json"
    private_path.write_text(json.dumps(metadata), encoding="utf-8")
    private_evaluation = evaluate_discovery_with_private_metadata(
        output_directory=output,
        private_metadata_path=private_path,
    )
    return run, training, validation, private_path, private_evaluation


def test_label_free_pipeline_writes_complete_auditable_artifacts(
    completed_pipeline,
) -> None:
    run, training, validation, _, private_evaluation = completed_pipeline
    output = run.output_directory
    assert all(
        (output / name).is_file() for name in REQUIRED_MODE_DISCOVERY_ARTIFACTS
    )
    assert all(
        (output / name).stat().st_size > 0
        for name in REQUIRED_MODE_DISCOVERY_ARTIFACTS
    )
    assert set(REQUIRED_LABEL_FREE_ARTIFACTS).issubset(
        REQUIRED_MODE_DISCOVERY_ARTIFACTS
    )

    library = ModeLibrary.load_json(output / "mode_library.json")
    assert library.schema_version == "d5freq.mode_library.v2"
    np.testing.assert_allclose(np.diag(library.transition_matrix), 0.91)
    np.testing.assert_allclose(
        library.transition_matrix - np.diag(np.diag(library.transition_matrix)),
        np.array([[0.0, 0.09], [0.09, 0.0]]),
    )
    assert all(
        set(model.multi_step_power_error_quantiles_pu)
        == set(model.multi_step_frequency_error_quantiles_hz)
        == set(model.multi_step_rocof_error_quantiles_hz_per_s)
        == set(range(1, 7))
        for model in library.models
    )
    assert all(
        model.multi_step_error_quantiles
        is model.multi_step_frequency_error_quantiles_hz
        for model in library.models
    )
    scaler = json.loads((output / "scaler.json").read_text(encoding="utf-8"))
    assert scaler["n_samples_seen"] == len(training)
    features = pd.read_parquet(output / "episode_features.parquet")
    assert (features["dataset_split"] == "train").sum() == len(training)
    assert (features["dataset_split"] == "validation").sum() == len(validation)
    assert set(features.loc[features["dataset_split"] == "train", "trajectory_id"]).isdisjoint(
        features.loc[features["dataset_split"] == "validation", "trajectory_id"]
    )

    metrics = pd.read_csv(output / "mode_model_metrics.csv")
    assert set(metrics["component_id"]) == set(range(library.discovery_metadata.selected_k))
    assert (metrics["validation_episode_count"] > 0).all()
    multistep = pd.read_csv(output / "multi_step_error_quantiles.csv")
    assert set(multistep["lead_step"]) == set(range(1, 7))
    assert set(multistep["component_id"]) == set(metrics["component_id"])
    assert np.isfinite(multistep["frequency_error_rmse_hz"]).all()
    assert np.isfinite(multistep["frequency_abs_error_quantile_95_hz"]).all()
    assert np.isfinite(multistep["rocof_error_rmse_hz_per_s"]).all()
    assert np.isfinite(multistep["rocof_abs_error_quantile_95_hz_per_s"]).all()
    for model in library.models:
        component_rows = multistep.loc[
            multistep["component_id"] == model.component_id
        ].sort_values("lead_step")
        np.testing.assert_allclose(
            list(model.multi_step_power_error_quantiles_pu.values()),
            component_rows["power_abs_error_quantile_95_pu"],
        )
        np.testing.assert_allclose(
            list(model.multi_step_frequency_error_quantiles_hz.values()),
            component_rows["frequency_abs_error_quantile_95_hz"],
        )
        np.testing.assert_allclose(
            list(model.multi_step_rocof_error_quantiles_hz_per_s.values()),
            component_rows["rocof_abs_error_quantile_95_hz_per_s"],
        )
    assert private_evaluation.adjusted_rand_index > 0.9


def test_selected_component_count_is_exactly_the_training_bic_minimum(
    completed_pipeline,
) -> None:
    run, _, _, _, _ = completed_pipeline
    bic = pd.read_csv(run.output_directory / "bic_table.csv")
    successful = bic.loc[bic["bic"].notna()]
    expected = int(
        successful.sort_values(["bic", "component_count"]).iloc[0]["component_count"]
    )
    library = ModeLibrary.load_json(run.output_directory / "mode_library.json")
    assert run.discovery.mixture.selected_k == expected
    assert library.discovery_metadata.selected_k == expected
    assert bic.loc[bic["selected"], "component_count"].tolist() == [expected]


def test_validation_uses_frozen_training_scaler(completed_pipeline) -> None:
    run, training, validation, _, _ = completed_pipeline
    raw_training = np.vstack([fit.raw_feature for fit in run.discovery.episode_fits])
    np.testing.assert_allclose(run.discovery.feature_scaler.mean, raw_training.mean(axis=0))
    assert run.discovery.feature_scaler.n_samples_seen == len(training)
    assert run.validation_assignment.standardized_features.shape[0] == len(validation)
    assert run.discovery.feature_scaler.n_samples_seen != len(training) + len(validation)


def test_training_entry_point_has_no_private_truth_parameter() -> None:
    parameter_names = inspect.signature(run_label_free_mode_discovery).parameters
    assert all("private" not in name and "truth" not in name for name in parameter_names)


def test_identification_orchestrator_source_has_a_strict_information_boundary() -> None:
    source_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "d5freq"
        / "identification"
        / "offline_pipeline.py"
    )
    source = source_path.read_text(encoding="utf-8").lower()
    forbidden = (
        "private",
        "truth",
        "mode_name_eval_only",
        "d5freq.evaluation",
        "diagnostic_metrics",
    )
    assert all(token not in source for token in forbidden)


def test_cli_source_hash_manifest_matches_exact_repository_files() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(str(repository_root / "scripts" / "02_discover_modes.py"))
    relative_paths = namespace["LABEL_FREE_SOURCE_PATHS"]
    hashes = namespace["label_free_source_hashes"](repository_root)
    assert tuple(hashes) == relative_paths
    for relative, digest in hashes.items():
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        assert digest == sha256_file(repository_root / relative)


def test_base_config_preserves_switch_epsilon_for_selected_k_transition() -> None:
    base = load_yaml(Path(__file__).resolve().parents[1] / "configs" / "base.yaml")
    parsed = offline_pipeline_config_from_base_config(base)
    assert parsed.switch_epsilon == pytest.approx(
        float(base["belief"]["switch_epsilon"])
    )
    assert parsed.discovery.reg_covar == pytest.approx(
        float(base["identification"]["gmm_reg_covar"])
    )


def test_empty_validation_component_fails_explicitly(completed_pipeline) -> None:
    run, _, validation, _, _ = completed_pipeline
    assert len(run.discovery.mode_models) == 2
    with pytest.raises(ValueError, match="no episode assigned to component"):
        evaluate_assigned_validation_episodes(
            validation,
            np.zeros(len(validation), dtype=int),
            run.discovery.mode_models,
            sample_time_s=0.1,
            horizon=6,
            validate_trajectory=validate_arx_multistep,
        )


def test_pipeline_persists_label_free_evidence_on_validation_failure(
    completed_pipeline,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from d5freq.identification import offline_pipeline

    _, training, validation, _, _ = completed_pipeline

    def fail_validation(*args, **kwargs):
        raise ValueError("no episode assigned to component 1")

    monkeypatch.setattr(
        offline_pipeline,
        "evaluate_assigned_validation_episodes",
        fail_validation,
    )
    output = tmp_path / "structured-failure"
    with pytest.raises(RuntimeError, match="no alternate component count"):
        run_label_free_mode_discovery(
            training,
            validation,
            config=_pipeline_config(),
            output_directory=output,
        )
    for name in (
        "bic_table.csv",
        "episode_features.parquet",
        "cluster_assignments.csv",
        "scaler.json",
        "gmm.pkl",
        "discovery_failure.json",
    ):
        assert (output / name).is_file()
    failure = json.loads(
        (output / "discovery_failure.json").read_text(encoding="utf-8")
    )
    assert failure["model_library_persisted"] is False
    assert failure["fallback_component_count_used"] is False
    assert not (output / "mode_library.json").exists()


def test_model_library_hash_is_invariant_to_private_label_mutation(
    completed_pipeline,
) -> None:
    run, _, _, private_path, _ = completed_pipeline
    library_path = run.output_directory / "mode_library.json"
    digest_before = sha256_file(library_path)
    metadata = json.loads(private_path.read_text(encoding="utf-8"))
    for index, row in enumerate(metadata):
        row["mode_name_eval_only"] = f"mutated-private-class-{index % 3}"
    private_path.write_text(json.dumps(metadata), encoding="utf-8")

    evaluate_discovery_with_private_metadata(
        output_directory=run.output_directory,
        private_metadata_path=private_path,
    )
    digest_after = sha256_file(library_path)
    assert digest_after == digest_before == run.model_library_sha256


def test_grid_frequency_error_propagation_matches_explicit_recurrence() -> None:
    config = _pipeline_config()
    grid = GridFrequencyModel(config.grid_params)
    power_errors = np.array([[0.01, -0.02, 0.03], [-0.01, 0.005, 0.0]])
    observed = propagate_grid_frequency_errors(power_errors, grid_model=grid)
    A_d, _, E_d, _ = grid.discrete_matrices()
    expected = np.empty_like(power_errors)
    for row in range(power_errors.shape[0]):
        state = np.zeros(5)
        for lead in range(power_errors.shape[1]):
            state = A_d @ state + E_d[:, 0] * power_errors[row, lead]
            expected[row, lead] = grid.params.f0_hz * state[0]
    np.testing.assert_allclose(observed, expected)
