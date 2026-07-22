from __future__ import annotations

import numpy as np
from numpy.testing import assert_allclose
import pytest

from d5freq.estimation import GRID_MEASUREMENT_MATRIX, GridKalmanFilter
from d5freq.interfaces import Measurement
from d5freq.models import GridFrequencyModel, GridParams, GridStateIndex


def _model() -> GridFrequencyModel:
    return GridFrequencyModel(
        GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    )


def test_predict_and_update_match_equations_33_to_37() -> None:
    model = _model()
    base_Q = np.diag([1e-8, 2e-8, 3e-8, 4e-8, 5e-8])
    R = np.array([[2e-6, 0.3e-6], [0.3e-6, 5e-6]])
    P0 = np.diag([0.1, 0.2, 0.3, 0.4, 0.5])
    x0 = np.array([0.001, 0.02, 0.015, -0.004, 0.03])
    kf = GridKalmanFilter(
        model,
        base_Q,
        R,
        initial_covariance=P0,
        load_random_walk_std_pu_per_s=0.0,
    )
    kf.reset(x0)
    A_d, B_d, E_d, _ = model.discrete_matrices()

    expected_prediction = A_d @ x0 + B_d[:, 0] * 0.01 + E_d[:, 0] * 0.005
    expected_predicted_P = A_d @ P0 @ A_d.T + base_Q
    predicted = kf.predict(0.01, 0.005)

    assert_allclose(predicted, expected_prediction, rtol=1e-13, atol=1e-14)
    assert_allclose(kf.covariance, expected_predicted_P, rtol=1e-12, atol=1e-14)

    y = np.array([0.0008, 0.019])
    C = GRID_MEASUREMENT_MATRIX
    innovation = y - C @ expected_prediction
    innovation_covariance = C @ expected_predicted_P @ C.T + R
    expected_gain = np.linalg.solve(
        innovation_covariance, C @ expected_predicted_P
    ).T
    expected_state = expected_prediction + expected_gain @ innovation
    # Equation (37), equivalent to the implementation's Joseph form.
    expected_covariance = (np.eye(5) - expected_gain @ C) @ expected_predicted_P

    updated = kf.update(*y)

    assert_allclose(updated, expected_state, rtol=1e-12, atol=1e-14)
    assert_allclose(kf.kalman_gain, expected_gain, rtol=1e-12, atol=1e-14)
    assert_allclose(kf.innovation, innovation, rtol=1e-13, atol=1e-14)
    assert_allclose(
        kf.innovation_covariance,
        innovation_covariance,
        rtol=1e-13,
        atol=1e-14,
    )
    assert_allclose(kf.covariance, expected_covariance, rtol=1e-11, atol=1e-13)


def test_load_random_walk_noise_is_mapped_through_exact_Gd() -> None:
    model = _model()
    sigma_pu_per_s = 0.003
    kf = GridKalmanFilter(
        model,
        process_noise_covariance=np.zeros((5, 5)),
        measurement_noise_covariance=np.eye(2),
        load_random_walk_std_pu_per_s=sigma_pu_per_s,
    )
    _, _, _, G_d = model.discrete_matrices()
    expected = sigma_pu_per_s**2 * (G_d @ G_d.T)

    assert_allclose(kf.load_random_walk_covariance, expected, atol=0.0, rtol=0.0)
    assert_allclose(kf.process_noise_covariance, expected, rtol=1e-13, atol=1e-18)
    # A deterministic known load slope is also propagated through G_d.
    predicted = kf.predict(0.0, 0.0, load_derivative_pu_per_s=0.01)
    assert_allclose(predicted, G_d[:, 0] * 0.01, rtol=1e-13, atol=1e-15)


def test_step_matches_separate_predict_and_update() -> None:
    model = _model()
    kwargs = {
        "process_noise_covariance": np.eye(5) * 1e-8,
        "measurement_noise_covariance": np.eye(2) * 1e-6,
        "initial_covariance": np.eye(5) * 0.1,
        "load_random_walk_std_pu_per_s": 1e-3,
    }
    combined = GridKalmanFilter(model, **kwargs)
    separate = GridKalmanFilter(model, **kwargs)

    expected_prediction = separate.predict(0.02, 0.01)
    assert expected_prediction.shape == (5,)
    expected = separate.update(-0.001, 0.003)
    actual = combined.step(-0.001, 0.003, 0.02, 0.01)

    assert_allclose(actual, expected)
    assert_allclose(combined.covariance, separate.covariance)


def test_filter_estimates_a_constant_unmeasured_load() -> None:
    model = _model()
    kf = GridKalmanFilter(
        model,
        process_noise_covariance=np.diag([1e-12, 1e-10, 1e-10, 1e-12, 0.0]),
        measurement_noise_covariance=np.eye(2) * 1e-10,
        initial_covariance=np.diag([1e-4, 1e-3, 1e-3, 1e-3, 0.1]),
        load_random_walk_std_pu_per_s=2e-4,
    )
    true_state = model.zero_state(load_disturbance_pu=0.04)
    A_d, B_d, E_d, _ = model.discrete_matrices()

    for _ in range(80):
        true_state = A_d @ true_state + B_d[:, 0] * 0.0 + E_d[:, 0] * 0.0
        kf.step(
            omega_pu=float(true_state[GridStateIndex.OMEGA_PU]),
            p_mech_pu=float(true_state[GridStateIndex.P_MECH_PU]),
            u_sg_prev_pu=0.0,
            p_ibr_prev_pu=0.0,
        )

    assert kf.load_disturbance_estimate_pu == pytest.approx(0.04, abs=2e-4)
    assert_allclose(kf.state[:3], true_state[:3], atol=2e-5)


def test_controller_measurement_adapter_uses_previous_ibr_power() -> None:
    model = _model()
    kwargs = {
        "process_noise_covariance": np.eye(5) * 1e-8,
        "measurement_noise_covariance": np.eye(2) * 1e-6,
        "load_random_walk_std_pu_per_s": 0.0,
    }
    adapted = GridKalmanFilter(model, **kwargs)
    reference = GridKalmanFilter(model, **kwargs)
    initial = Measurement(0.0, 0.001, 0.002, 0.007, 0.0, 0.0)
    current = Measurement(0.5, 0.0005, 0.003, 0.02, 0.01, 0.0)

    adapted.reset_from_measurement(initial)
    reference.reset_from_measurement(initial)
    expected = reference.step(0.0005, 0.003, 0.01, 0.007)
    actual = adapted.update_from_measurement(current)

    assert_allclose(actual, expected)
    assert "mode" not in str(GridKalmanFilter.step.__annotations__).lower()
