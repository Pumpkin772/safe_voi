from __future__ import annotations

import numpy as np
import pytest

from d5freq.identification.arx import (
    open_loop_arx_rollout,
    validate_arx_multistep,
)


def _manual_rollout(
    theta: np.ndarray,
    p_k_minus_1: float,
    p_k: float,
    u_k_minus_1: float,
    omega_k_minus_1: float,
    future_u: np.ndarray,
    future_omega: np.ndarray,
) -> np.ndarray:
    output: list[float] = []
    p_previous, p_current = p_k_minus_1, p_k
    u_previous, omega_previous = u_k_minus_1, omega_k_minus_1
    for u_current, omega_current in zip(future_u, future_omega, strict=True):
        regressor = np.array(
            [
                p_current,
                p_previous,
                u_current,
                u_previous,
                omega_current,
                omega_previous,
                1.0,
            ]
        )
        p_next = float(theta @ regressor)
        output.append(p_next)
        p_previous, p_current = p_current, p_next
        u_previous, omega_previous = float(u_current), float(omega_current)
    return np.asarray(output)


def test_open_loop_rollout_uses_predicted_power_and_future_exogenous_inputs() -> None:
    theta = np.array([0.75, -0.16, 0.28, 0.05, -0.32, 0.12, 0.003])
    future_u = np.array([0.02, -0.04, 0.01, 0.06])
    future_omega = np.array([-0.002, 0.001, 0.003, -0.001])

    actual = open_loop_arx_rollout(
        theta,
        p_k=0.04,
        p_k_minus_1=-0.01,
        u_k_minus_1=0.015,
        omega_k_minus_1=0.002,
        future_u_ibr_pu=future_u,
        future_omega_pu=future_omega,
    )
    expected = _manual_rollout(
        theta,
        -0.01,
        0.04,
        0.015,
        0.002,
        future_u,
        future_omega,
    )

    np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-16)


def test_validation_does_not_teacher_force_future_observed_power() -> None:
    theta = np.array([0.9, -0.2, 0.3, -0.1, 0.25, 0.05, 0.002])
    p = np.array([0.01, 0.02, 20.0, -30.0, 40.0, -50.0, 60.0])
    u = np.array([0.0, 0.01, 0.02, -0.01, 0.03, 0.04, -0.02])
    omega = np.array([0.0, -0.001, 0.002, 0.003, -0.002, 0.001, 0.0])
    horizon = 4

    validation = validate_arx_multistep(theta, p, u, omega, horizon=horizon)
    expected_first_origin = _manual_rollout(
        theta,
        p[0],
        p[1],
        u[0],
        omega[0],
        u[1 : 1 + horizon],
        omega[1 : 1 + horizon],
    )

    np.testing.assert_allclose(
        validation.predictions[0],
        expected_first_origin,
        rtol=0.0,
        atol=1e-14,
    )
    assert abs(validation.predictions[0, 1]) < 1.0
    assert p[2] == 20.0


def test_validation_rolls_all_valid_origins_and_computes_lead_metrics() -> None:
    theta = np.zeros(7)
    p = np.array([0.0, 0.0, 1.0, 2.0, 3.0, 4.0])
    u = np.zeros_like(p)
    omega = np.zeros_like(p)

    result = validate_arx_multistep(theta, p, u, omega, horizon=2)
    expected_errors = np.array([[1.0, 2.0], [2.0, 3.0], [3.0, 4.0]])

    assert result.n_origins == 3
    assert result.horizon == 2
    np.testing.assert_array_equal(result.predictions, np.zeros((3, 2)))
    np.testing.assert_array_equal(result.errors, expected_errors)
    np.testing.assert_allclose(
        result.rmse_by_lead,
        np.sqrt(np.mean(expected_errors**2, axis=0)),
    )
    np.testing.assert_allclose(
        result.mae_by_lead,
        np.mean(np.abs(expected_errors), axis=0),
    )
    np.testing.assert_allclose(
        result.abs_error_quantile_95_by_lead,
        np.quantile(np.abs(expected_errors), 0.95, axis=0),
    )


def test_noise_free_model_has_zero_multistep_error() -> None:
    rng = np.random.default_rng(26)
    theta = np.array([0.74, -0.18, 0.23, 0.06, -0.2, 0.08, -0.001])
    u = rng.normal(scale=0.04, size=100)
    omega = rng.normal(scale=0.002, size=100)
    p = np.empty(100)
    p[:2] = [0.01, -0.01]
    for k in range(1, 99):
        p[k + 1] = theta @ np.array(
            [p[k], p[k - 1], u[k], u[k - 1], omega[k], omega[k - 1], 1.0]
        )

    result = validate_arx_multistep(theta, p, u, omega, horizon=12)

    np.testing.assert_allclose(result.errors, 0.0, rtol=0.0, atol=2e-16)
    np.testing.assert_allclose(result.rmse_by_lead, 0.0, rtol=0.0, atol=2e-16)


@pytest.mark.parametrize("horizon", [0, -1])
def test_validation_rejects_non_positive_horizon(horizon: int) -> None:
    with pytest.raises(ValueError, match="horizon must be strictly positive"):
        validate_arx_multistep(
            np.zeros(7),
            np.zeros(5),
            np.zeros(5),
            np.zeros(5),
            horizon=horizon,
        )


def test_validation_rejects_horizon_longer_than_trajectory() -> None:
    with pytest.raises(ValueError, match=r"horizon \+ 2"):
        validate_arx_multistep(
            np.zeros(7),
            np.zeros(5),
            np.zeros(5),
            np.zeros(5),
            horizon=4,
        )


def test_rollout_rejects_misaligned_exogenous_sequences() -> None:
    with pytest.raises(ValueError, match="equal length"):
        open_loop_arx_rollout(
            np.zeros(7),
            p_k=0.0,
            p_k_minus_1=0.0,
            u_k_minus_1=0.0,
            omega_k_minus_1=0.0,
            future_u_ibr_pu=np.zeros(3),
            future_omega_pu=np.zeros(2),
        )
