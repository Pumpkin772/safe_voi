from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest

from d5freq.identification.mode_discovery import (
    ARXFitterAPI,
    FEATURE_DIMENSION,
    FeatureStandardizer,
    assign_episodes_with_frozen_discovery,
    build_raw_feature,
    fit_local_episode_models,
    select_gmm_by_bic,
)


def test_feature_is_theta_plus_log_variance_with_exact_dimension() -> None:
    theta = np.arange(7, dtype=float)
    feature = build_raw_feature(theta, 0.25, variance_epsilon=1.0e-6)

    assert feature.shape == (FEATURE_DIMENSION,)
    np.testing.assert_array_equal(feature[:7], theta)
    assert feature[7] == pytest.approx(np.log(0.25 + 1.0e-6))
    assert not feature.flags.writeable


def test_standardizer_matches_training_only_sklearn_statistics() -> None:
    training = np.array(
        [
            [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, -4.0],
            [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, -2.0],
            [4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 0.0],
        ]
    )
    held_out = np.array([[100.0] * FEATURE_DIMENSION])

    scaler = FeatureStandardizer.fit(training)
    transformed_train = scaler.transform(training)
    before = scaler.to_dict()
    transformed_held_out = scaler.transform(held_out)

    np.testing.assert_allclose(transformed_train.mean(axis=0), 0.0, atol=1.0e-14)
    np.testing.assert_allclose(transformed_train.var(axis=0), 1.0, atol=1.0e-14)
    np.testing.assert_allclose(scaler.mean, training.mean(axis=0))
    np.testing.assert_allclose(
        transformed_held_out,
        (held_out - training.mean(axis=0)) / training.std(axis=0, ddof=0),
    )
    assert scaler.to_dict() == before
    assert scaler.n_samples_seen == training.shape[0]


def test_constant_training_column_uses_standard_scaler_unit_scale() -> None:
    training = np.column_stack(
        (
            np.arange(4.0)[:, None].repeat(7, axis=1),
            np.ones(4),
        )
    )
    scaler = FeatureStandardizer.fit(training)
    assert scaler.variance[-1] == 0.0
    assert scaler.scale[-1] == 1.0
    np.testing.assert_array_equal(scaler.transform(training)[:, -1], 0.0)


@pytest.mark.parametrize(
    "features,exception",
    [
        (np.zeros((3, 7)), ValueError),
        (np.zeros((3, 8), dtype=complex) + 1j, TypeError),
        (np.full((3, 8), np.nan), ValueError),
    ],
)
def test_standardizer_rejects_non_eight_dimensional_or_nonreal_features(
    features: np.ndarray, exception: type[Exception]
) -> None:
    with pytest.raises(exception):
        FeatureStandardizer.fit(features)


@dataclass(frozen=True)
class _Episode:
    trajectory_id: str
    p_ibr_pu: np.ndarray
    u_ibr_pu: np.ndarray
    omega_pu: np.ndarray


def _dummy_api() -> ARXFitterAPI:
    def build(p: np.ndarray, u: np.ndarray, omega: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rows = len(p) - 2
        phi = np.column_stack((p[1:-1], p[:-2], u[1:-1], u[:-2], omega[1:-1], omega[:-2], np.ones(rows)))
        return phi, p[2:]

    def fit(p: np.ndarray, u: np.ndarray, omega: np.ndarray, *, ridge_lambda: float) -> SimpleNamespace:
        phi, target = build(p, u, omega)
        theta = np.linalg.solve(phi.T @ phi + ridge_lambda * np.eye(7), phi.T @ target)
        residuals = target - phi @ theta
        return SimpleNamespace(
            theta=theta,
            residuals=residuals,
            residual_variance=float(residuals @ residuals / max(1, len(target) - 7)),
            condition_number=float(np.linalg.cond(phi)),
            n_regression_rows=len(target),
        )

    def fit_regression(phi: np.ndarray, target: np.ndarray, *, ridge_lambda: float) -> SimpleNamespace:
        theta = np.linalg.solve(phi.T @ phi + ridge_lambda * np.eye(7), phi.T @ target)
        residuals = target - phi @ theta
        return SimpleNamespace(
            theta=theta,
            residuals=residuals,
            residual_variance=float(residuals @ residuals / max(1, len(target) - 7)),
            condition_number=float(np.linalg.cond(phi)),
            n_regression_rows=len(target),
        )

    return ARXFitterAPI(build, fit, fit_regression)


def test_held_out_assignment_reuses_frozen_scaler_and_mixture() -> None:
    rng = np.random.default_rng(314)
    episodes = []
    for index in range(12):
        u = rng.normal(size=20)
        omega = rng.normal(size=20)
        p = (0.3 if index < 6 else -0.3) * u + 0.05 * rng.normal(size=20)
        episodes.append(_Episode(f"opaque-{index}", p, u, omega))
    api = _dummy_api()
    fits = fit_local_episode_models(episodes, arx=api, ridge_lambda=1.0e-3)
    raw = np.vstack([fit.raw_feature for fit in fits])
    scaler = FeatureStandardizer.fit(raw)
    standardized = scaler.transform(raw)
    selection = select_gmm_by_bic(
        standardized,
        k_min=1,
        k_max=2,
        covariance_type="diag",
        n_init=3,
        random_seed=7,
    )
    mean_before = scaler.mean.copy()
    mixture_mean_before = selection.model.means_.copy()

    assigned = assign_episodes_with_frozen_discovery(
        episodes[:3],
        arx=api,
        feature_scaler=scaler,
        mixture=selection.model,
        ridge_lambda=1.0e-3,
    )

    assert assigned.standardized_features.shape == (3, FEATURE_DIMENSION)
    np.testing.assert_allclose(assigned.component_probabilities.sum(axis=1), 1.0)
    np.testing.assert_array_equal(scaler.mean, mean_before)
    np.testing.assert_array_equal(selection.model.means_, mixture_mean_before)
