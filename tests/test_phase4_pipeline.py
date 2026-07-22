from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
from numpy.testing import assert_allclose
import pandas as pd

from d5freq.data import IdentificationTrajectory, PrivateTrajectoryMetadata
from d5freq.evaluation.phase4_pipeline import (
    PHASE4_GENERATED_SCENARIOS,
    Phase4Settings,
    _generate_evaluation_episodes,
    _load_modes,
    _portable_path,
    _reproducibility_provenance,
    aggregate_component_beliefs,
    build_majority_component_mapping,
    calibrate_ood_from_trajectories,
    compute_all_component_arx_residuals,
    phase4_source_hashes,
    select_hysteresis_known_only_cv,
)
from d5freq.estimation.ood_detector import OODDetectorConfig
from d5freq.identification.model_library import (
    ARXModeModel,
    BICRecord,
    DiscoveryMetadata,
    FeatureScalerState,
    ModeLibrary,
)
from d5freq.utils.config import load_yaml


ROOT = Path(__file__).resolve().parents[1]


def _library() -> ModeLibrary:
    models = (
        ARXModeModel(
            component_id=0,
            theta=np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            residual_variance=0.04,
            multi_step_power_error_quantiles_pu={1: 0.1},
            multi_step_frequency_error_quantiles_hz={1: 0.1},
            multi_step_rocof_error_quantiles_hz_per_s={1: 0.1},
            p_output_min_pu=-1.0,
            p_output_max_pu=1.0,
            ramp_down_pu_per_s=1.0,
            ramp_up_pu_per_s=1.0,
            training_episode_count=2,
            training_sample_count=8,
        ),
        ARXModeModel(
            component_id=1,
            theta=np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0]),
            residual_variance=0.09,
            multi_step_power_error_quantiles_pu={1: 0.1},
            multi_step_frequency_error_quantiles_hz={1: 0.1},
            multi_step_rocof_error_quantiles_hz_per_s={1: 0.1},
            p_output_min_pu=-1.0,
            p_output_max_pu=1.0,
            ramp_down_pu_per_s=1.0,
            ramp_up_pu_per_s=1.0,
            training_episode_count=2,
            training_sample_count=8,
        ),
    )
    return ModeLibrary(
        models=models,
        transition_matrix=np.array([[0.99, 0.01], [0.01, 0.99]]),
        feature_scaler=FeatureScalerState(
            mean=np.zeros(8),
            scale=np.ones(8),
            variance=np.ones(8),
            n_samples_seen=4,
        ),
        discovery_metadata=DiscoveryMetadata(
            selected_k=2,
            candidate_k_min=1,
            candidate_k_max=2,
            covariance_type="full",
            n_init=2,
            random_seed=1,
            bic_table=(
                BICRecord(1, 2.0, 1.0, True, 2),
                BICRecord(2, 1.0, 0.0, True, 2),
            ),
        ),
    )


def _trajectory(identifier: str, offset: float = 0.0) -> IdentificationTrajectory:
    return IdentificationTrajectory(
        trajectory_id=identifier,
        time_s=np.arange(5, dtype=float) * 0.5,
        u_ibr_pu=np.zeros(5),
        omega_pu=np.zeros(5),
        p_ibr_pu=np.arange(5, dtype=float) + offset,
    )


def _metadata(identifier: str, mode: str) -> PrivateTrajectoryMetadata:
    return PrivateTrajectoryMetadata(
        trajectory_id=identifier,
        mode_name_eval_only=mode,
        trajectory_seed_eval_only=1,
        excitation_pair_id_eval_only=("f" * 31 + identifier[-1]),
        excitation_family_eval_only="prbs",
        split="train",
        excitation_sha256="e" * 64,
    )


def test_phase4_settings_are_resolved_from_base_config() -> None:
    settings = Phase4Settings.from_base_config(load_yaml(ROOT / "configs" / "base.yaml"))

    assert settings.epsilon_switch == 0.002
    assert settings.epsilon_sensitivity == (0.0005, 0.001, 0.002, 0.005, 0.01)
    assert settings.unique_test_excitations == 4
    assert settings.default_ood_config == OODDetectorConfig(
        alpha_on=0.01,
        alpha_off=0.10,
        L_on=3,
        L_off=5,
        variance_floor=1.0e-8,
    )


def test_reproducibility_provenance_captures_git_environment_seeds_and_sources() -> None:
    settings = Phase4Settings.from_base_config(load_yaml(ROOT / "configs" / "base.yaml"))
    provenance = _reproducibility_provenance(ROOT, settings)
    hashes = phase4_source_hashes(ROOT)

    assert len(provenance["git"]["commit"]) == 40
    assert provenance["environment"]["python"]["version_info"][0:2] == [3, 11]
    assert "cvxpy" in provenance["environment"]["packages"]
    assert "installed_cvxpy_solvers" in provenance["environment"]["solvers"]
    assert provenance["randomness"]["master_seed"] == settings.master_seed
    assert set(provenance["randomness"]["generated_scenario_measurement_seeds"]) == {
        item[0] for item in PHASE4_GENERATED_SCENARIOS
    }
    assert hashes == provenance["source_sha256"]
    assert all(len(digest) == 64 for digest in hashes.values())
    assert _portable_path(
        ROOT / "configs" / "base.yaml", ROOT, "configs/base.yaml"
    ) == "configs/base.yaml"


def test_all_component_residuals_use_the_documented_online_indexing() -> None:
    residuals = compute_all_component_arx_residuals(_trajectory("a" * 32), _library())

    assert_allclose(
        residuals,
        np.array(
            [
                [1.0, 0.0],
                [1.0, 1.0],
                [1.0, 2.0],
            ]
        ),
    )


def test_calibration_artifact_covers_all_components_and_preserves_trajectories() -> None:
    trajectories = (_trajectory("a" * 32), _trajectory("b" * 32, 0.1))
    result = calibrate_ood_from_trajectories(
        trajectories,
        _library(),
        measurement_noise_variance_pu2=0.01,
        variance_floor_pu2=1.0e-8,
        dataset_sha256="c" * 64,
        split_manifest_sha256="d" * 64,
        mode_library_sha256="e" * 64,
        source_hash_by_trajectory_id={
            "a" * 32: "1" * 64,
            "b" * 32: "2" * 64,
        },
    )

    assert result.artifact.source_split == "ood_calibration"
    assert result.artifact.source_population == "known_modes_only"
    assert result.artifact.covered_component_ids == (0, 1)
    assert len(result.artifact.calibration_scores) == 6
    assert set(result.scores_by_trajectory) == {"a" * 32, "b" * 32}
    assert {"residual_0_pu", "residual_1_pu", "ood_score"} <= set(
        result.residual_table
    )


def test_hysteresis_selection_is_trajectory_level_and_known_only() -> None:
    selected, table = select_hysteresis_known_only_cv(
        {
            "episode-a": np.array([0.1, 0.2, 0.3, 5.0]),
            "episode-b": np.array([0.1, 0.2, 0.4, 4.0]),
            "episode-c": np.array([0.2, 0.3, 0.5, 3.0]),
        },
        alpha_on_candidates=(0.01, 0.05),
        alpha_off_candidates=(0.1,),
        hold_on_candidates=(2, 3),
        hold_off_candidates=(3,),
        declared_default=OODDetectorConfig(0.01, 0.1, 3, 3, 1.0e-8),
        variance_floor=1.0e-8,
    )

    assert isinstance(selected, OODDetectorConfig)
    assert table["selected"].sum() == 1
    assert set(table["selection_population"]) == {"known_modes_only"}
    assert set(table["known_cv_trajectory_count"]) == {3}


def test_many_to_one_mapping_uses_train_majority_and_aggregates_k_to_four() -> None:
    identifiers = tuple(f"{index:032x}" for index in range(6))
    assignments = pd.DataFrame(
        {
            "trajectory_id": identifiers,
            "dataset_split": ["train"] * 6,
            "component_id": [0, 0, 0, 1, 1, 1],
        }
    )
    metadata = (
        _metadata(identifiers[0], "nominal"),
        _metadata(identifiers[1], "nominal"),
        _metadata(identifiers[2], "sluggish"),
        _metadata(identifiers[3], "derated"),
        _metadata(identifiers[4], "derated"),
        _metadata(identifiers[5], "unavailable"),
    )
    labels = ("nominal", "sluggish", "derated", "unavailable")
    mapping, evidence = build_majority_component_mapping(
        assignments, metadata, component_count=2, class_labels=labels
    )
    aggregate = aggregate_component_beliefs(
        np.array([[0.25, 0.75], [0.8, 0.2]]), mapping, labels
    )

    assert mapping == {0: "nominal", 1: "derated"}
    assert evidence[0]["nominal"] == 2
    assert_allclose(aggregate, [[0.25, 0.0, 0.75, 0.0], [0.8, 0.0, 0.2, 0.0]])


def test_phase4_system_scenario_matrix_covers_all_six_required_cases() -> None:
    names = tuple(item[0] for item in PHASE4_GENERATED_SCENARIOS)

    assert names == (
        "nominal_to_sluggish",
        "nominal_to_unavailable",
        "load_step_no_mode",
        "noise_change_no_mode",
        "ood_asymmetric_limit",
        "ood_time_varying_delay",
    )
    assert {item[1] for item in PHASE4_GENERATED_SCENARIOS} == {0, 1, 2, 3}


def test_all_six_system_scenarios_generate_truth_separated_public_trajectories(
    tmp_path: Path,
) -> None:
    settings = replace(
        Phase4Settings.from_base_config(load_yaml(ROOT / "configs" / "base.yaml")),
        switch_time_s=0.5,
        integration_step_s=0.1,
        load_step_start_s=0.5,
        load_step_end_s=1.0,
    )
    inputs = tuple(
        (
            IdentificationTrajectory(
                trajectory_id=f"{index + 100:032x}",
                time_s=np.array([0.0, 0.5, 1.0, 1.5]),
                u_ibr_pu=np.array([0.0, 0.01 * (index + 1), 0.0, -0.01]),
                omega_pu=np.array([0.0, -0.0001 * index, 0.0002, 0.0]),
                p_ibr_pu=np.zeros(4),
            ),
            f"{index + 1}" * 64,
        )
        for index in range(4)
    )

    episodes = _generate_evaluation_episodes(
        inputs,
        _load_modes(ROOT / "configs" / "modes_known.yaml", ood=False),
        _load_modes(ROOT / "configs" / "modes_ood.yaml", ood=True),
        settings,
        tmp_path / "generated",
    )

    by_scenario = {episode.scenario_eval_only: episode for episode in episodes}
    assert set(by_scenario) == {item[0] for item in PHASE4_GENERATED_SCENARIOS}
    assert len(tuple((tmp_path / "generated").glob("*.parquet"))) == 6
    assert set(
        by_scenario["nominal_to_sluggish"]
        .truth_timeline_eval_only.mode_name_eval_only
    ) == {"nominal", "sluggish"}
    assert set(
        by_scenario["nominal_to_unavailable"]
        .truth_timeline_eval_only.mode_name_eval_only
    ) == {"nominal", "unavailable"}
    assert set(
        by_scenario["ood_asymmetric_limit"]
        .truth_timeline_eval_only.mode_name_eval_only
    ) == {"nominal", "asymmetric_limit"}
    assert set(
        by_scenario["ood_time_varying_delay"]
        .truth_timeline_eval_only.mode_name_eval_only
    ) == {"nominal", "time_varying_delay"}
    assert set(
        by_scenario["load_step_no_mode"]
        .truth_timeline_eval_only.mode_name_eval_only
    ) == {"nominal"}
    assert set(
        by_scenario["noise_change_no_mode"]
        .truth_timeline_eval_only.mode_name_eval_only
    ) == {"nominal"}
