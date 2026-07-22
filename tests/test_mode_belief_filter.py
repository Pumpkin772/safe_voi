from __future__ import annotations

import inspect

import numpy as np
from numpy.testing import assert_allclose
import pytest

from d5freq.estimation.mode_belief_filter import (
    ModeBeliefFilter,
    build_online_arx_regressor,
    build_sticky_transition_matrix,
    predict_mode_belief,
    update_mode_belief,
)
from d5freq.identification.arx import predict_arx_next
from d5freq.identification.model_library import (
    ARXModeModel,
    BICRecord,
    DiscoveryMetadata,
    FeatureScalerState,
    ModeLibrary,
)


def _library(
    thetas: np.ndarray,
    residual_variances: np.ndarray,
    transition_matrix: np.ndarray | None = None,
) -> ModeLibrary:
    component_count = int(thetas.shape[0])
    models = tuple(
        ARXModeModel(
            component_id=index,
            theta=theta,
            residual_variance=float(residual_variances[index]),
            multi_step_power_error_quantiles_pu={},
            multi_step_frequency_error_quantiles_hz={},
            multi_step_rocof_error_quantiles_hz_per_s={},
            p_output_min_pu=-0.1,
            p_output_max_pu=0.1,
            ramp_down_pu_per_s=0.1,
            ramp_up_pu_per_s=0.1,
            training_episode_count=4,
            training_sample_count=100,
        )
        for index, theta in enumerate(thetas)
    )
    metadata = DiscoveryMetadata(
        selected_k=component_count,
        candidate_k_min=component_count,
        candidate_k_max=component_count,
        covariance_type="full",
        n_init=2,
        random_seed=0,
        bic_table=(
            BICRecord(
                component_count=component_count,
                bic=0.0,
                delta_bic=0.0,
                converged=True,
                iterations=1,
            ),
        ),
    )
    return ModeLibrary(
        models=models,
        transition_matrix=(
            build_sticky_transition_matrix(component_count, 0.01)
            if transition_matrix is None
            else transition_matrix
        ),
        feature_scaler=FeatureScalerState(
            mean=np.zeros(8),
            scale=np.ones(8),
            variance=np.ones(8),
            n_samples_seen=10,
        ),
        discovery_metadata=metadata,
    )


def test_sticky_transition_matches_equation_40_and_k1_is_safe() -> None:
    transition = build_sticky_transition_matrix(4, epsilon_switch=0.02)

    assert_allclose(np.diag(transition), 0.94, atol=0.0, rtol=0.0)
    assert_allclose(
        transition - np.diag(np.diag(transition)),
        np.full((4, 4), 0.02) - np.eye(4) * 0.02,
        atol=0.0,
        rtol=0.0,
    )
    assert_allclose(transition.sum(axis=1), 1.0, atol=1e-15, rtol=0.0)
    assert_allclose(build_sticky_transition_matrix(1, 0.5), [[1.0]])


def test_equation_41_uses_previous_rows_and_next_mode_columns() -> None:
    transition = np.array(
        [
            [0.8, 0.2, 0.0],
            [0.1, 0.7, 0.2],
            [0.3, 0.0, 0.7],
        ]
    )
    previous = np.array([0.6, 0.3, 0.1])

    predicted = predict_mode_belief(
        previous,
        transition,
        belief_floor=1e-15,
    )

    assert_allclose(predicted, transition.T @ previous, rtol=1e-14, atol=1e-15)
    assert predicted.sum() == pytest.approx(1.0)
    assert np.all(predicted >= 0.0)


def test_online_regressor_preserves_the_existing_arx_parameter_order() -> None:
    regressor = build_online_arx_regressor(
        p_ibr_k_minus_1_pu=1.0,
        p_ibr_k_minus_2_pu=2.0,
        u_ibr_k_minus_1_pu=3.0,
        u_ibr_k_minus_2_pu=4.0,
        omega_k_minus_1_pu=5.0,
        omega_k_minus_2_pu=6.0,
    )
    theta = np.arange(1.0, 8.0)
    expected = predict_arx_next(
        theta,
        p_k=1.0,
        p_k_minus_1=2.0,
        u_k=3.0,
        u_k_minus_1=4.0,
        omega_k=5.0,
        omega_k_minus_1=6.0,
    )

    assert_allclose(regressor, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 1.0])
    assert float(theta @ regressor) == expected


def test_log_domain_update_matches_direct_domain_at_moderate_scale() -> None:
    prior = np.array([0.2, 0.5, 0.3])
    predictions = np.array([0.08, 0.10, 0.14])
    observed = 0.11
    variances = np.array([0.005, 0.01, 0.02])

    result = update_mode_belief(
        prior,
        observed_p_ibr_pu=observed,
        mode_predictions_pu=predictions,
        innovation_variances_pu2=variances,
        belief_floor=1e-15,
    )

    residuals = observed - predictions
    likelihoods = np.exp(-(residuals**2) / (2.0 * variances)) / np.sqrt(
        2.0 * np.pi * variances
    )
    denominator = float(likelihoods @ prior)
    expected = likelihoods * prior / denominator
    assert_allclose(result.residuals_pu, residuals, rtol=0.0, atol=0.0)
    assert_allclose(
        result.normalized_innovation_squared,
        residuals**2 / variances,
        rtol=1e-14,
        atol=1e-16,
    )
    assert_allclose(result.mode_belief, expected, rtol=1e-14, atol=1e-15)
    assert result.log_normalization_constant == pytest.approx(np.log(denominator))


def test_equal_residuals_and_variances_preserve_the_predicted_belief() -> None:
    prior = np.array([0.15, 0.35, 0.50])
    result = update_mode_belief(
        prior,
        observed_p_ibr_pu=0.3,
        mode_predictions_pu=np.zeros(3),
        innovation_variances_pu2=np.full(3, 0.02),
    )

    assert_allclose(result.mode_belief, prior, rtol=1e-14, atol=1e-15)
    assert_allclose(result.nis, np.full(3, 0.3**2 / 0.02))
    assert 0.0 <= result.normalized_entropy <= 1.0
    assert result.belief_entropy == result.normalized_entropy
    assert result.raw_belief_entropy == result.entropy


def test_tiny_likelihoods_never_create_nan_or_an_all_zero_belief() -> None:
    result = update_mode_belief(
        [0.5, 0.5],
        observed_p_ibr_pu=1.0e200,
        mode_predictions_pu=[0.0, 1.0],
        innovation_variances_pu2=[1.0e-300, 1.0e-300],
        variance_floor_pu2=1.0e-300,
        belief_floor=1.0e-100,
    )

    for vector in (
        result.mode_belief,
        result.residuals_pu,
        result.innovation_variances_pu2,
        result.normalized_innovation_squared,
        result.log_likelihoods,
    ):
        assert np.all(np.isfinite(vector))
    assert np.isfinite(result.log_normalization_constant)
    assert np.all(result.mode_belief > 0.0)
    assert result.mode_belief.sum() == pytest.approx(1.0)


def test_variance_and_belief_floors_keep_update_well_defined() -> None:
    result = update_mode_belief(
        [1.0, 0.0],
        observed_p_ibr_pu=0.0,
        mode_predictions_pu=[0.0, 10.0],
        innovation_variances_pu2=[0.0, 0.0],
        belief_floor=1.0e-8,
        variance_floor_pu2=1.0e-6,
    )

    assert_allclose(result.innovation_variances_pu2, [1e-6, 1e-6])
    assert np.all(result.predicted_belief > 0.0)
    assert np.all(result.mode_belief > 0.0)
    assert result.mode_belief.sum() == pytest.approx(1.0)


def test_stateful_step_and_separate_predict_update_are_identical() -> None:
    thetas = np.zeros((2, 7))
    thetas[1, 6] = 1.0
    library = _library(thetas, np.full(2, 0.01))
    combined = ModeBeliefFilter(library, measurement_noise_variance_pu2=0.002)
    separate = ModeBeliefFilter(library, measurement_noise_variance_pu2=0.002)

    expected_predictions = separate.predict_mode_outputs(
        p_ibr_k_minus_1_pu=0.0,
        p_ibr_k_minus_2_pu=0.0,
        u_ibr_k_minus_1_pu=0.0,
        u_ibr_k_minus_2_pu=0.0,
        omega_k_minus_1_pu=0.0,
        omega_k_minus_2_pu=0.0,
    )
    separate.predict()
    expected = separate.update(
        p_ibr_k_pu=0.95,
        mode_predictions_pu=expected_predictions,
    )
    actual = combined.step(
        p_ibr_k_pu=0.95,
        p_ibr_k_minus_1_pu=0.0,
        p_ibr_k_minus_2_pu=0.0,
        u_ibr_k_minus_1_pu=0.0,
        u_ibr_k_minus_2_pu=0.0,
        omega_k_minus_1_pu=0.0,
        omega_k_minus_2_pu=0.0,
    )

    assert_allclose(actual.mode_predictions_pu, [0.0, 1.0])
    assert_allclose(actual.mode_belief, expected.mode_belief)
    assert actual.map_mode == 1
    assert_allclose(combined.mode_belief, separate.mode_belief)
    assert combined.last_update is actual


def test_single_component_filter_has_zero_normalized_entropy() -> None:
    library = _library(np.zeros((1, 7)), np.array([0.01]))
    belief_filter = ModeBeliefFilter(library)

    result = belief_filter.step(
        p_ibr_k_pu=0.2,
        p_ibr_k_minus_1_pu=0.0,
        p_ibr_k_minus_2_pu=0.0,
        u_ibr_k_minus_1_pu=0.0,
        u_ibr_k_minus_2_pu=0.0,
        omega_k_minus_1_pu=0.0,
        omega_k_minus_2_pu=0.0,
    )

    assert_allclose(result.mode_belief, [1.0])
    assert result.map_mode == 0
    assert result.entropy == pytest.approx(0.0)
    assert result.normalized_entropy == 0.0


def test_runtime_api_contains_no_true_mode_argument() -> None:
    for method in (
        ModeBeliefFilter.predict,
        ModeBeliefFilter.predict_mode_outputs,
        ModeBeliefFilter.update,
        ModeBeliefFilter.step,
    ):
        assert "true" not in str(inspect.signature(method)).lower()


@pytest.mark.parametrize(
    ("call", "error"),
    [
        (
            lambda: build_sticky_transition_matrix(3, 0.6),
            ValueError,
        ),
        (
            lambda: predict_mode_belief(
                [0.5, 0.5], np.eye(3), belief_floor=1e-12
            ),
            ValueError,
        ),
        (
            lambda: predict_mode_belief(
                [0.5, np.nan], np.eye(2), belief_floor=1e-12
            ),
            ValueError,
        ),
        (
            lambda: update_mode_belief(
                [0.5, 0.5],
                observed_p_ibr_pu=np.inf,
                mode_predictions_pu=[0.0, 0.0],
                innovation_variances_pu2=[1.0, 1.0],
            ),
            ValueError,
        ),
        (
            lambda: update_mode_belief(
                [0.5, 0.5],
                observed_p_ibr_pu=0.0,
                mode_predictions_pu=[0.0],
                innovation_variances_pu2=[1.0, 1.0],
            ),
            ValueError,
        ),
    ],
)
def test_invalid_shapes_ranges_and_nonfinite_inputs_are_rejected(
    call: object,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        call()  # type: ignore[operator]


def test_update_requires_an_explicit_prior_prediction() -> None:
    library = _library(np.zeros((2, 7)), np.ones(2))
    belief_filter = ModeBeliefFilter(library)
    with pytest.raises(RuntimeError, match="predict"):
        belief_filter.update(
            p_ibr_k_pu=0.0,
            mode_predictions_pu=np.zeros(2),
        )


def test_result_arrays_and_filter_properties_are_defensive() -> None:
    library = _library(np.zeros((2, 7)), np.ones(2))
    belief_filter = ModeBeliefFilter(library)
    result = belief_filter.step(
        p_ibr_k_pu=0.0,
        p_ibr_k_minus_1_pu=0.0,
        p_ibr_k_minus_2_pu=0.0,
        u_ibr_k_minus_1_pu=0.0,
        u_ibr_k_minus_2_pu=0.0,
        omega_k_minus_1_pu=0.0,
        omega_k_minus_2_pu=0.0,
    )

    with pytest.raises(ValueError):
        result.mode_belief[0] = 0.0
    external = belief_filter.mode_belief
    external[0] = 0.0
    assert belief_filter.mode_belief.sum() == pytest.approx(1.0)
