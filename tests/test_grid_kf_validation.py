from __future__ import annotations

import inspect
import math

import numpy as np
import pytest

from d5freq.estimation import GridKalmanFilter
from d5freq.interfaces import Measurement
from d5freq.models import GridFrequencyModel, GridParams


def _model() -> GridFrequencyModel:
    return GridFrequencyModel(
        GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    )


def test_augmented_observability_excludes_only_integral_constant_offset() -> None:
    model = _model()
    estimator = GridKalmanFilter(model)
    A_d, _, _, _ = model.discrete_matrices()
    C_g = estimator.measurement_matrix
    observability = np.vstack(
        [C_g @ np.linalg.matrix_power(A_d, power) for power in range(5)]
    )

    # xi is an accumulated controller state whose initial value is defined at
    # episode reset; it does not feed back into measured grid dynamics. The
    # remaining physical states, including the load disturbance, are observable.
    assert np.linalg.matrix_rank(observability) == 4
    np.testing.assert_allclose(observability[:, 3], 0.0, atol=1.0e-15)
    assert np.linalg.matrix_rank(observability[:, [0, 1, 2, 4]]) == 4


@pytest.mark.parametrize(
    ("argument", "value", "message"),
    [
        ("process", np.eye(4), "shape"),
        ("process", np.diag([1.0, 1.0, 1.0, 1.0, -1.0]), "semidefinite"),
        ("process", np.eye(5) + np.triu(np.ones((5, 5)), 1), "symmetric"),
        ("measurement", np.eye(3), "shape"),
        ("measurement", np.zeros((2, 2)), "positive definite"),
        ("measurement", np.array([[1.0, math.nan], [math.nan, 1.0]]), "finite"),
        ("initial", np.eye(4), "shape"),
    ],
)
def test_covariances_are_strictly_validated(
    argument: str, value: np.ndarray, message: str
) -> None:
    kwargs: dict[str, object] = {
        "process_noise_covariance": np.eye(5),
        "measurement_noise_covariance": np.eye(2),
        "initial_covariance": np.eye(5),
    }
    key = {
        "process": "process_noise_covariance",
        "measurement": "measurement_noise_covariance",
        "initial": "initial_covariance",
    }[argument]
    kwargs[key] = value
    with pytest.raises(ValueError, match=message):
        GridKalmanFilter(_model(), **kwargs)


def test_state_and_covariance_properties_are_defensive_copies() -> None:
    kf = GridKalmanFilter(_model())
    state = kf.state
    covariance = kf.covariance
    process_noise = kf.process_noise_covariance
    state[0] = 99.0
    covariance[0, 0] = 99.0
    process_noise[0, 0] = 99.0

    assert kf.state[0] == 0.0
    assert kf.covariance[0, 0] != 99.0
    assert kf.process_noise_covariance[0, 0] != 99.0


def test_reset_validates_and_copies_inputs() -> None:
    kf = GridKalmanFilter(_model())
    state = np.arange(5, dtype=float)
    covariance = np.eye(5)
    returned = kf.reset(state, covariance)
    state[:] = -1.0
    covariance[:] = -1.0
    returned[:] = -1.0

    np.testing.assert_array_equal(kf.state, np.arange(5, dtype=float))
    np.testing.assert_array_equal(kf.covariance, np.eye(5))
    with pytest.raises(ValueError, match="shape"):
        kf.reset(np.zeros(4))
    with pytest.raises(ValueError, match="finite"):
        kf.reset(np.array([0.0, 0.0, 0.0, 0.0, math.nan]))


def test_invalid_step_is_rejected_before_state_mutation() -> None:
    kf = GridKalmanFilter(_model())
    original_state = kf.state
    original_covariance = kf.covariance

    with pytest.raises(ValueError, match="finite"):
        kf.step(math.nan, 0.0, 0.0, 0.0)

    np.testing.assert_array_equal(kf.state, original_state)
    np.testing.assert_array_equal(kf.covariance, original_covariance)


def test_measurement_adapter_requires_reset_and_visible_type() -> None:
    kf = GridKalmanFilter(_model())
    measurement = Measurement(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    with pytest.raises(RuntimeError, match="reset_from_measurement"):
        kf.update_from_measurement(measurement)
    with pytest.raises(TypeError, match="Measurement"):
        kf.reset_from_measurement(object())  # type: ignore[arg-type]


def test_covariance_remains_symmetric_positive_semidefinite() -> None:
    kf = GridKalmanFilter(
        _model(),
        process_noise_covariance=np.eye(5) * 1e-12,
        measurement_noise_covariance=np.eye(2) * 1e-14,
        initial_covariance=np.eye(5) * 1e6,
        load_random_walk_std_pu_per_s=1e-3,
    )
    for index in range(200):
        kf.step(
            omega_pu=1e-4 * math.sin(index),
            p_mech_pu=1e-3 * math.cos(index),
            u_sg_prev_pu=0.0,
            p_ibr_prev_pu=0.0,
        )

    covariance = kf.covariance
    np.testing.assert_allclose(covariance, covariance.T, atol=1e-13, rtol=0.0)
    assert np.linalg.eigvalsh(covariance).min() >= -1e-13


def test_runtime_signature_contains_no_truth_or_mode_argument() -> None:
    text = " ".join(
        str(inspect.signature(method))
        for method in (
            GridKalmanFilter.predict,
            GridKalmanFilter.update,
            GridKalmanFilter.step,
            GridKalmanFilter.update_from_measurement,
        )
    ).lower()
    assert "true" not in text
    assert "mode" not in text
