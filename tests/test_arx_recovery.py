from __future__ import annotations

import numpy as np
import pytest

from d5freq.identification.arx import (
    ARX_PARAMETER_COUNT,
    build_arx_regression,
    fit_arx_ridge,
    fit_arx_ridge_from_regression,
    predict_arx_one_step_series,
)


def _simulate_arx(
    theta: np.ndarray,
    u: np.ndarray,
    omega: np.ndarray,
    *,
    p0: float = 0.01,
    p1: float = -0.02,
) -> np.ndarray:
    p = np.empty(u.size, dtype=float)
    p[0], p[1] = p0, p1
    for k in range(1, u.size - 1):
        p[k + 1] = theta @ np.array(
            [p[k], p[k - 1], u[k], u[k - 1], omega[k], omega[k - 1], 1.0]
        )
    return p


def test_regression_uses_phi_k_to_predict_p_k_plus_one() -> None:
    p = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
    u = np.array([20.0, 21.0, 22.0, 23.0, 24.0])
    omega = np.array([30.0, 31.0, 32.0, 33.0, 34.0])

    phi, targets = build_arx_regression(p, u, omega)

    np.testing.assert_array_equal(
        phi,
        np.array(
            [
                [11.0, 10.0, 21.0, 20.0, 31.0, 30.0, 1.0],
                [12.0, 11.0, 22.0, 21.0, 32.0, 31.0, 1.0],
                [13.0, 12.0, 23.0, 22.0, 33.0, 32.0, 1.0],
            ]
        ),
    )
    np.testing.assert_array_equal(targets, np.array([12.0, 13.0, 14.0]))


def test_noise_free_persistently_exciting_arx_recovers_all_parameters() -> None:
    rng = np.random.default_rng(20260722)
    theta = np.array([0.82, -0.19, 0.31, -0.07, -0.24, 0.11, 0.006])
    u = rng.normal(scale=0.06, size=800)
    omega = rng.normal(scale=0.003, size=800)
    p = _simulate_arx(theta, u, omega)

    result = fit_arx_ridge(p, u, omega, ridge_lambda=0.0)

    np.testing.assert_allclose(result.theta, theta, rtol=2e-10, atol=2e-11)
    np.testing.assert_allclose(
        predict_arx_one_step_series(result.theta, p, u, omega),
        p[2:],
        rtol=2e-10,
        atol=2e-11,
    )
    assert result.n_regression_rows == p.size - 2
    assert result.residual_degrees_of_freedom == p.size - 7
    assert result.residual_variance < 1e-24


def test_ridge_matches_equation_77_including_penalized_constant() -> None:
    rng = np.random.default_rng(77)
    phi = rng.normal(size=(35, ARX_PARAMETER_COUNT))
    phi[:, -1] = 1.0
    targets = rng.normal(size=35)
    ridge_lambda = 0.7
    phi_before = phi.copy()
    targets_before = targets.copy()

    result = fit_arx_ridge_from_regression(
        phi,
        targets,
        ridge_lambda=ridge_lambda,
    )
    expected = np.linalg.solve(
        phi.T @ phi + ridge_lambda * np.eye(ARX_PARAMETER_COUNT),
        phi.T @ targets,
    )

    np.testing.assert_allclose(result.theta, expected, rtol=2e-14, atol=2e-14)
    np.testing.assert_array_equal(phi, phi_before)
    np.testing.assert_array_equal(targets, targets_before)


def test_residual_variance_uses_n_regression_rows_minus_seven() -> None:
    rng = np.random.default_rng(78)
    phi = rng.normal(size=(23, ARX_PARAMETER_COUNT))
    phi[:, -1] = 1.0
    targets = rng.normal(size=23)

    result = fit_arx_ridge_from_regression(phi, targets, ridge_lambda=0.15)
    expected_residuals = targets - phi @ result.theta

    assert result.residual_degrees_of_freedom == 23 - 7
    assert result.residual_variance == pytest.approx(
        float(expected_residuals @ expected_residuals) / (23 - 7),
        rel=1e-14,
    )
    np.testing.assert_allclose(result.residuals, expected_residuals)


def test_trajectory_fit_uses_literal_equation_78_raw_sample_count() -> None:
    rng = np.random.default_rng(781)
    theta = np.array([0.7, -0.1, 0.2, 0.03, -0.2, 0.04, 0.001])
    u = rng.normal(scale=0.03, size=40)
    omega = rng.normal(scale=0.002, size=40)
    p = _simulate_arx(theta, u, omega)
    p = p + rng.normal(scale=1.0e-4, size=p.size)

    result = fit_arx_ridge(p, u, omega, ridge_lambda=1.0e-5)
    expected_residuals = p[2:] - build_arx_regression(p, u, omega)[0] @ result.theta

    assert result.n_regression_rows == p.size - 2
    assert result.residual_degrees_of_freedom == p.size - 7
    assert result.residual_variance == pytest.approx(
        float(expected_residuals @ expected_residuals) / (p.size - 7)
    )


def test_fit_result_owns_immutable_arrays() -> None:
    rng = np.random.default_rng(9)
    phi = rng.normal(size=(20, ARX_PARAMETER_COUNT))
    targets = rng.normal(size=20)
    result = fit_arx_ridge_from_regression(phi, targets, ridge_lambda=0.1)
    phi[:] = 0.0
    targets[:] = 0.0

    assert np.any(result.theta != 0.0)
    assert np.any(result.residuals != 0.0)
    with pytest.raises(ValueError, match="read-only"):
        result.theta[0] = 100.0
    with pytest.raises(ValueError, match="read-only"):
        result.residuals[0] = 100.0


@pytest.mark.parametrize(
    ("p", "u", "omega", "message"),
    [
        ([0.0, 1.0], [0.0, 1.0], [0.0, 1.0], "at least three"),
        ([0.0, 1.0, 2.0], [0.0, 1.0], [0.0, 1.0, 2.0], "equal length"),
        ([0.0, np.nan, 2.0], [0.0, 1.0, 2.0], [0.0, 1.0, 2.0], "finite"),
    ],
)
def test_regression_rejects_invalid_trajectories(
    p: list[float],
    u: list[float],
    omega: list[float],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_arx_regression(p, u, omega)


def test_fit_requires_positive_residual_degrees_of_freedom() -> None:
    with pytest.raises(ValueError, match="at least eight regression rows"):
        fit_arx_ridge_from_regression(
            np.ones((ARX_PARAMETER_COUNT, ARX_PARAMETER_COUNT)),
            np.ones(ARX_PARAMETER_COUNT),
            ridge_lambda=0.1,
        )


def test_arx_inputs_reject_complex_values_without_casting_warning() -> None:
    complex_series = np.ones(10, dtype=np.complex128)
    with pytest.raises(ValueError, match="real-valued"):
        build_arx_regression(complex_series, np.ones(10), np.ones(10))
    with pytest.raises(ValueError, match="real-valued"):
        fit_arx_ridge_from_regression(
            np.ones((10, ARX_PARAMETER_COUNT), dtype=np.complex128),
            np.ones(10),
            ridge_lambda=0.1,
        )


@pytest.mark.parametrize("ridge_lambda", [-1.0, np.nan, np.inf])
def test_fit_rejects_invalid_ridge_lambda(ridge_lambda: float) -> None:
    with pytest.raises(ValueError, match="ridge_lambda"):
        fit_arx_ridge_from_regression(
            np.eye(8, ARX_PARAMETER_COUNT),
            np.ones(8),
            ridge_lambda=ridge_lambda,
        )
