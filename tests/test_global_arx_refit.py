from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from d5freq.identification.arx import (
    build_arx_regression,
    fit_arx_ridge,
    fit_arx_ridge_from_regression,
    validate_arx_multistep,
)
from d5freq.identification.mode_discovery import (
    ARXFitterAPI,
    ModeDiscoveryConfig,
    discover_unlabeled_modes,
    evaluate_assigned_validation_episodes,
    fit_local_episode_models,
    refit_global_cluster_models,
)


@dataclass(frozen=True)
class _Episode:
    trajectory_id: str
    p_ibr_pu: np.ndarray
    u_ibr_pu: np.ndarray
    omega_pu: np.ndarray


def _simulate_episode(
    trajectory_id: str,
    theta: np.ndarray,
    *,
    length: int,
    seed: int,
) -> _Episode:
    rng = np.random.default_rng(seed)
    u = rng.uniform(-0.08, 0.08, size=length)
    omega = rng.uniform(-0.002, 0.002, size=length)
    p = np.zeros(length)
    p[:2] = rng.normal(scale=0.002, size=2)
    for k in range(1, length - 1):
        phi = np.array([p[k], p[k - 1], u[k], u[k - 1], omega[k], omega[k - 1], 1.0])
        p[k + 1] = theta @ phi + rng.normal(scale=2.0e-4)
    return _Episode(trajectory_id, p, u, omega)


def _api() -> ARXFitterAPI:
    return ARXFitterAPI(
        build_regression=build_arx_regression,
        fit_trajectory=fit_arx_ridge,
        fit_from_regression=fit_arx_ridge_from_regression,
    )


def test_global_refit_pools_cluster_samples_and_retains_component_ids() -> None:
    theta_0 = np.array([0.7, -0.1, 0.2, 0.03, -0.5, 0.1, 0.0])
    theta_1 = np.array([0.35, 0.15, 0.05, 0.01, -0.2, 0.04, 0.001])
    episodes = [
        _simulate_episode("opaque-a", theta_0, length=45, seed=1),
        _simulate_episode("opaque-b", theta_0, length=70, seed=2),
        _simulate_episode("opaque-c", theta_1, length=50, seed=3),
        _simulate_episode("opaque-d", theta_1, length=80, seed=4),
    ]
    ridge_lambda = 1.0e-5
    fits = fit_local_episode_models(episodes, arx=_api(), ridge_lambda=ridge_lambda)
    assignments = np.array([0, 0, 1, 1])

    models = refit_global_cluster_models(
        episodes,
        fits,
        assignments,
        arx=_api(),
        ridge_lambda=ridge_lambda,
        sample_time_s=0.1,
    )

    assert [model.component_id for model in models] == [0, 1]
    for component_id, indices in ((0, (0, 1)), (1, (2, 3))):
        pooled_phi = np.vstack([fits[index].regression_matrix for index in indices])
        pooled_y = np.concatenate([fits[index].target for index in indices])
        expected = fit_arx_ridge_from_regression(
            pooled_phi, pooled_y, ridge_lambda=ridge_lambda
        )
        np.testing.assert_allclose(models[component_id].theta, expected.theta)
        assert models[component_id].residual_variance == pytest.approx(
            np.var(pooled_y - pooled_phi @ expected.theta, ddof=0)
        )
        assert models[component_id].training_episode_count == 2
        assert models[component_id].training_sample_count == pooled_phi.shape[0]


def test_global_refit_is_not_an_average_of_local_coefficients() -> None:
    theta = np.array([0.6, -0.08, 0.18, 0.02, -0.4, 0.08, 0.0])
    episodes = [
        _simulate_episode("short", theta, length=20, seed=10),
        _simulate_episode("long", theta, length=160, seed=11),
    ]
    fits = fit_local_episode_models(episodes, arx=_api(), ridge_lambda=1.0e-4)
    model = refit_global_cluster_models(
        episodes,
        fits,
        np.zeros(2, dtype=int),
        arx=_api(),
        ridge_lambda=1.0e-4,
        sample_time_s=0.1,
    )[0]

    local_average = np.mean([fit.theta for fit in fits], axis=0)
    pooled_phi = np.vstack([fit.regression_matrix for fit in fits])
    pooled_y = np.concatenate([fit.target for fit in fits])
    pooled = fit_arx_ridge_from_regression(pooled_phi, pooled_y, ridge_lambda=1.0e-4)
    np.testing.assert_allclose(model.theta, pooled.theta)
    assert np.linalg.norm(model.theta - local_average) > 1.0e-5


def test_rank_deficiency_is_reported_as_infinite_condition_number() -> None:
    p = np.zeros(20)
    episode = _Episode("opaque-zero", p, p.copy(), p.copy())
    fits = fit_local_episode_models(
        [episode],
        arx=_api(),
        ridge_lambda=1.0e-3,
    )
    assert np.isinf(fits[0].condition_number)


def test_refit_rejects_renumbered_or_gapped_components() -> None:
    theta = np.array([0.6, -0.1, 0.2, 0.0, -0.3, 0.0, 0.0])
    episodes = [
        _simulate_episode("a", theta, length=30, seed=1),
        _simulate_episode("b", theta, length=30, seed=2),
    ]
    fits = fit_local_episode_models(episodes, arx=_api(), ridge_lambda=1.0e-4)
    with pytest.raises(ValueError, match="contiguous"):
        refit_global_cluster_models(
            episodes,
            fits,
            np.array([0, 2]),
            arx=_api(),
            ridge_lambda=1.0e-4,
            sample_time_s=0.1,
        )


def test_per_component_held_out_multistep_metrics_are_aggregated() -> None:
    theta_0 = np.array([0.7, -0.1, 0.2, 0.03, -0.5, 0.1, 0.0])
    theta_1 = np.array([0.35, 0.15, 0.05, 0.01, -0.2, 0.04, 0.001])
    training = [
        _simulate_episode("train-a", theta_0, length=65, seed=21),
        _simulate_episode("train-b", theta_1, length=65, seed=22),
    ]
    fits = fit_local_episode_models(training, arx=_api(), ridge_lambda=1.0e-5)
    models = refit_global_cluster_models(
        training,
        fits,
        np.array([0, 1]),
        arx=_api(),
        ridge_lambda=1.0e-5,
        sample_time_s=0.1,
    )
    validation = [
        _simulate_episode("valid-a", theta_0, length=40, seed=31),
        _simulate_episode("valid-b", theta_1, length=45, seed=32),
    ]

    metrics = evaluate_assigned_validation_episodes(
        validation,
        np.array([0, 1]),
        models,
        sample_time_s=0.1,
        horizon=5,
        validate_trajectory=validate_arx_multistep,
    )

    assert [metric.component_id for metric in metrics] == [0, 1]
    for metric in metrics:
        assert metric.validation_episode_count == 1
        assert metric.prediction_origin_count > 0
        assert metric.rmse_by_lead.shape == (5,)
        assert metric.mae_by_lead.shape == (5,)
        assert metric.abs_error_quantile_95_by_lead.shape == (5,)
        assert set(metric.error_quantiles_for_library) == {1, 2, 3, 4, 5}
        assert 0.0 <= metric.power_bound_coverage <= 1.0
        assert 0.0 <= metric.directional_rate_bound_coverage <= 1.0


def test_complete_unlabeled_pipeline_discovers_and_refits_two_components() -> None:
    theta_0 = np.array([0.75, -0.15, 0.25, 0.04, -0.6, 0.1, 0.0])
    theta_1 = np.array([0.2, 0.25, 0.03, -0.01, -0.1, -0.03, 0.002])
    episodes = [
        _simulate_episode(f"opaque-{index:03d}", theta, length=90, seed=100 + index)
        for index, theta in enumerate([theta_0] * 15 + [theta_1] * 15)
    ]
    result = discover_unlabeled_modes(
        episodes,
        sample_time_s=0.1,
        arx=_api(),
        config=ModeDiscoveryConfig(
            ridge_lambda=1.0e-5,
            k_min=1,
            k_max=3,
            covariance_type="diag",
            n_init=4,
            random_seed=88,
        ),
    )

    assert result.standardized_features.shape == (30, 8)
    assert result.mixture.selected_k == 2
    assert [model.component_id for model in result.mode_models] == [0, 1]
    assert sum(model.training_episode_count for model in result.mode_models) == 30
