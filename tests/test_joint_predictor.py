from __future__ import annotations

import numpy as np
import pytest

from d5freq.models import GridFrequencyModel, GridParams
from d5freq.optimization.joint_prediction import (
    JOINT_FREQUENCY_OUTPUT,
    JOINT_INTEGRAL_OUTPUT,
    JointARXPredictionModel,
    assemble_joint_arx_prediction,
)


def _grid() -> GridFrequencyModel:
    return GridFrequencyModel(
        GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    )


def _arx_matrices() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    theta = np.array([0.8, -0.1, 0.25, 0.05, -0.3, -0.1, 0.002])
    A_b = np.array(
        [
            [theta[0], theta[1], theta[3], theta[5], theta[6]],
            [1.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 1.0],
        ]
    )
    B_b = np.array([[theta[2]], [0.0], [1.0], [0.0], [0.0]])
    F_b = np.array([[theta[4]], [0.0], [0.0], [1.0], [0.0]])
    return A_b, B_b, F_b


def test_joint_block_model_matches_separate_grid_and_arx_steps() -> None:
    grid = _grid()
    A_b, B_b, F_b = _arx_matrices()
    model = assemble_joint_arx_prediction(grid, A_b, B_b, F_b)
    grid_state = np.array([-0.001, 0.02, 0.018, 0.004, 0.03])
    arx_state = np.array([0.012, 0.01, 0.008, -0.0008, 1.0])
    state = np.concatenate((grid_state, arx_state))
    control = np.array([0.025, 0.015])

    grid_A, grid_B, grid_E, _ = grid.discrete_matrices()
    expected_grid = (
        grid_A @ grid_state
        + grid_B[:, 0] * control[0]
        + grid_E[:, 0] * arx_state[0]
    )
    expected_arx = (
        A_b @ arx_state
        + B_b[:, 0] * control[1]
        + F_b[:, 0] * grid_state[0]
    )

    np.testing.assert_allclose(
        model.step(state, control),
        np.concatenate((expected_grid, expected_arx)),
        rtol=1.0e-13,
        atol=1.0e-14,
    )
    assert model.A.shape == (10, 10)
    assert model.B.shape == (10, 2)


def test_joint_selection_matrices_match_frequency_and_integral_states() -> None:
    A_b, B_b, F_b = _arx_matrices()
    model = assemble_joint_arx_prediction(_grid(), A_b, B_b, F_b)
    state = np.arange(10, dtype=float)

    assert float((model.C_frequency @ state).item()) == state[0]
    assert float((model.C_integral @ state).item()) == state[3]
    np.testing.assert_array_equal(model.C_frequency, JOINT_FREQUENCY_OUTPUT)
    np.testing.assert_array_equal(model.C_integral, JOINT_INTEGRAL_OUTPUT)


def test_joint_model_validates_shapes_and_returns_defensive_matrices() -> None:
    A_b, B_b, F_b = _arx_matrices()
    model = assemble_joint_arx_prediction(_grid(), A_b, B_b, F_b)
    A_copy = model.A.copy()
    A_copy[0, 0] = 99.0
    assert model.A[0, 0] != 99.0

    with pytest.raises(ValueError, match="shape"):
        assemble_joint_arx_prediction(_grid(), np.eye(4), B_b, F_b)
    with pytest.raises(ValueError, match="shape"):
        JointARXPredictionModel(np.eye(10), np.zeros((10, 3)))
    with pytest.raises(ValueError, match="shape"):
        model.step(np.zeros(9), np.zeros(2))
