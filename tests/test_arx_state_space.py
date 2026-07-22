from __future__ import annotations

import numpy as np
import pytest

from d5freq.identification.arx import (
    arx_state_from_history,
    arx_to_state_space,
    predict_arx_next,
)


def test_arx_state_space_matches_equations_21_through_25() -> None:
    theta = np.array([1.2, -0.3, 0.2, 0.1, -0.05, 0.01, 0.004])

    A_b, B_b, F_b, C_b = arx_to_state_space(theta)

    np.testing.assert_array_equal(
        A_b,
        np.array(
            [
                [1.2, -0.3, 0.1, 0.01, 0.004],
                [1.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 1.0],
            ]
        ),
    )
    np.testing.assert_array_equal(B_b[:, 0], np.array([0.2, 0.0, 1.0, 0.0, 0.0]))
    np.testing.assert_array_equal(F_b[:, 0], np.array([-0.05, 0.0, 0.0, 1.0, 0.0]))
    np.testing.assert_array_equal(C_b, np.array([[1.0, 0.0, 0.0, 0.0, 0.0]]))


def test_state_update_matches_scalar_arx_and_updates_all_lags() -> None:
    theta = np.array([0.8, -0.2, 0.3, 0.07, -0.4, 0.13, 0.005])
    state = arx_state_from_history(
        p_k=0.04,
        p_k_minus_1=-0.01,
        u_k_minus_1=0.02,
        omega_k_minus_1=-0.003,
    )
    u_k = 0.06
    omega_k = 0.002
    A_b, B_b, F_b, C_b = arx_to_state_space(theta)

    next_state = A_b @ state + B_b[:, 0] * u_k + F_b[:, 0] * omega_k
    expected_power = predict_arx_next(
        theta,
        p_k=0.04,
        p_k_minus_1=-0.01,
        u_k=u_k,
        u_k_minus_1=0.02,
        omega_k=omega_k,
        omega_k_minus_1=-0.003,
    )

    np.testing.assert_allclose(
        next_state,
        np.array([expected_power, 0.04, u_k, omega_k, 1.0]),
        rtol=0.0,
        atol=2e-16,
    )
    assert float((C_b @ next_state)[0]) == pytest.approx(expected_power)


def test_state_space_rollout_matches_repeated_scalar_arx() -> None:
    theta = np.array([0.7, -0.12, 0.24, -0.04, -0.3, 0.09, -0.002])
    future_u = np.array([0.02, 0.04, -0.01, 0.03])
    future_omega = np.array([-0.001, -0.002, 0.003, 0.001])
    state = arx_state_from_history(
        p_k=0.01,
        p_k_minus_1=-0.02,
        u_k_minus_1=0.0,
        omega_k_minus_1=0.002,
    )
    A_b, B_b, F_b, _ = arx_to_state_space(theta)

    expected_state = state.copy()
    for u_k, omega_k in zip(future_u, future_omega, strict=True):
        scalar_next = predict_arx_next(
            theta,
            p_k=float(expected_state[0]),
            p_k_minus_1=float(expected_state[1]),
            u_k=float(u_k),
            u_k_minus_1=float(expected_state[2]),
            omega_k=float(omega_k),
            omega_k_minus_1=float(expected_state[3]),
        )
        expected_state = np.array(
            [scalar_next, expected_state[0], u_k, omega_k, 1.0]
        )
        state = A_b @ state + B_b[:, 0] * u_k + F_b[:, 0] * omega_k
        np.testing.assert_allclose(state, expected_state, rtol=0.0, atol=2e-16)


def test_conversion_returns_fresh_caller_owned_matrices() -> None:
    theta = np.arange(7, dtype=float)
    matrices_a = arx_to_state_space(theta)
    matrices_b = arx_to_state_space(theta)
    matrices_a[0][0, 0] = -999.0

    assert matrices_b[0][0, 0] == theta[0]
    assert theta[0] == 0.0
    assert all(left is not right for left, right in zip(matrices_a, matrices_b, strict=True))


@pytest.mark.parametrize(
    "theta",
    [np.ones(6), np.ones(8), np.array([0.0] * 6 + [np.inf]), np.ones((7, 1))],
)
def test_conversion_rejects_invalid_theta(theta: np.ndarray) -> None:
    with pytest.raises(ValueError, match="theta"):
        arx_to_state_space(theta)


def test_state_history_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="p_k must be finite"):
        arx_state_from_history(
            p_k=np.nan,
            p_k_minus_1=0.0,
            u_k_minus_1=0.0,
            omega_k_minus_1=0.0,
        )
