from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from d5freq.evaluation.diagnostic_metrics import evaluate_clustering_with_private_labels
from d5freq.identification.model_library import (
    ARXModeModel,
    BICRecord,
    DiscoveryMetadata,
    FeatureScalerState,
    ModeLibrary,
    discovery_metadata_from_selection,
    sticky_transition_matrix,
)
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.optimization.joint_prediction import assemble_joint_arx_prediction
from d5freq.identification.mode_discovery import select_gmm_by_bic


def test_private_label_alignment_is_evaluation_only_and_permutation_invariant() -> None:
    components = np.array([2, 2, 0, 0, 1, 1])
    private_labels = np.array(["alpha", "alpha", "gamma", "gamma", "beta", "beta"])
    result = evaluate_clustering_with_private_labels(components, private_labels)

    assert result.adjusted_rand_index == pytest.approx(1.0)
    assert result.normalized_mutual_information == pytest.approx(1.0)
    assert result.macro_f1 == pytest.approx(1.0)
    assert result.component_to_reference_label == {0: "gamma", 1: "beta", 2: "alpha"}
    assert result.unmatched_component_ids == ()
    assert result.aligned_confusion_matrix[:, -1].sum() == 0


def test_rectangular_alignment_penalizes_unmatched_components() -> None:
    components = np.array([0, 1, 2, 2])
    private_labels = np.array(["a", "a", "b", "b"])
    result = evaluate_clustering_with_private_labels(components, private_labels)
    assert len(result.unmatched_component_ids) == 1
    assert result.aligned_confusion_matrix[:, -1].sum() > 0
    assert 0.0 < result.macro_f1 < 1.0


def test_assignment_implementation_is_absent_from_identification_package() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "d5freq" / "identification"
    combined = "\n".join(path.read_text(encoding="utf-8") for path in source_root.glob("*.py"))
    forbidden_symbols = (
        "linear_sum_assignment",
        "adjusted_rand_score",
        "normalized_mutual_info_score",
        "f1_score",
    )
    assert all(symbol not in combined for symbol in forbidden_symbols)


def _library() -> ModeLibrary:
    scaler = FeatureScalerState(
        mean=np.zeros(8),
        scale=np.ones(8),
        variance=np.ones(8),
        n_samples_seen=20,
    )
    metadata = DiscoveryMetadata(
        selected_k=2,
        candidate_k_min=1,
        candidate_k_max=2,
        covariance_type="full",
        n_init=10,
        random_seed=42,
        bic_table=(
            BICRecord(1, 120.0, 30.0, True, 4),
            BICRecord(2, 90.0, 0.0, True, 5),
        ),
    )
    models = tuple(
        ARXModeModel(
            component_id=index,
            theta=np.array([0.7, -0.1, 0.2, 0.02, -0.4, 0.05, 0.001 * index]),
            residual_variance=1.0e-4 * (index + 1),
            multi_step_power_error_quantiles_pu={1: 0.001, 2: 0.002},
            multi_step_frequency_error_quantiles_hz={1: 0.01, 2: 0.02},
            multi_step_rocof_error_quantiles_hz_per_s={1: 0.1, 2: 0.2},
            p_output_min_pu=-0.05,
            p_output_max_pu=0.04,
            ramp_down_pu_per_s=0.02,
            ramp_up_pu_per_s=0.03,
            training_episode_count=10,
            training_sample_count=500,
        )
        for index in range(2)
    )
    return ModeLibrary(
        models=models,
        transition_matrix=sticky_transition_matrix(2),
        feature_scaler=scaler,
        discovery_metadata=metadata,
    )


def _grid() -> GridFrequencyModel:
    return GridFrequencyModel(
        GridParams(
            f0_hz=50.0,
            M_s=8.0,
            D_pu=1.0,
            T_t_s=0.5,
            T_g_s=0.2,
            R_pu=0.05,
            control_period_s=0.1,
            integration_step_s=0.01,
        )
    )


def test_strict_library_round_trip_is_joint_predictor_compatible(tmp_path: Path) -> None:
    original = _library()
    destination = tmp_path / "mode_library.json"
    original.save_json(destination)
    loaded = ModeLibrary.load_json(destination)

    assert loaded.to_dict() == original.to_dict()
    for model in loaded.models:
        assert model.B_b.shape == (5, 1)
        assert model.F_b.shape == (5, 1)
        joint = assemble_joint_arx_prediction(_grid(), model.A_b, model.B_b, model.F_b)
        assert joint.A.shape == (10, 10)
        assert joint.B.shape == (10, 2)


def test_library_owns_arrays_and_quantile_mapping_is_immutable() -> None:
    theta = np.arange(7, dtype=float)
    power_quantiles = {1: 0.02}
    frequency_quantiles = {1: 0.2}
    rocof_quantiles = {1: 2.0}
    model = ARXModeModel(
        component_id=0,
        theta=theta,
        residual_variance=0.1,
        multi_step_power_error_quantiles_pu=power_quantiles,
        multi_step_frequency_error_quantiles_hz=frequency_quantiles,
        multi_step_rocof_error_quantiles_hz_per_s=rocof_quantiles,
        p_output_min_pu=-1.0,
        p_output_max_pu=1.0,
        ramp_down_pu_per_s=1.0,
        ramp_up_pu_per_s=2.0,
        training_episode_count=2,
        training_sample_count=20,
    )
    theta[0] = 999.0
    power_quantiles[1] = 999.0
    frequency_quantiles[1] = 999.0
    rocof_quantiles[1] = 999.0
    assert model.theta[0] == 0.0
    assert model.multi_step_error_quantiles[1] == 0.2
    assert model.multi_step_power_error_quantiles_pu[1] == 0.02
    assert model.multi_step_frequency_error_quantiles_hz[1] == 0.2
    assert model.multi_step_rocof_error_quantiles_hz_per_s[1] == 2.0
    with pytest.raises(ValueError):
        model.theta[0] = 1.0
    with pytest.raises(TypeError):
        model.multi_step_error_quantiles[1] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        model.multi_step_power_error_quantiles_pu[1] = 1.0  # type: ignore[index]


def test_library_schema_rejects_unknown_or_mapping_fields() -> None:
    payload = _library().to_dict()
    unknown = copy.deepcopy(payload)
    unknown["component_name_mapping"] = {"0": "private-name"}
    with pytest.raises(ValueError, match="extra"):
        ModeLibrary.from_dict(unknown)

    nested_unknown = copy.deepcopy(payload)
    nested_unknown["models"][0]["display_name"] = "private-name"  # type: ignore[index]
    with pytest.raises(ValueError, match="extra"):
        ModeLibrary.from_dict(nested_unknown)


def test_selection_metadata_conversion_preserves_complete_bic_audit() -> None:
    rng = np.random.default_rng(55)
    features = np.vstack(
        (rng.normal(-2.0, 0.1, size=(20, 8)), rng.normal(2.0, 0.1, size=(20, 8)))
    )
    selection = select_gmm_by_bic(
        features,
        k_min=1,
        k_max=3,
        covariance_type="diag",
        n_init=2,
        random_seed=17,
    )
    metadata = discovery_metadata_from_selection(selection, random_seed=17)
    assert metadata.selected_k == selection.selected_k
    assert metadata.candidate_k_min == 1
    assert metadata.candidate_k_max == 3
    assert len(metadata.bic_table) == 3
    assert [record.bic for record in metadata.bic_table] == [
        score.bic for score in selection.candidate_scores
    ]
