from __future__ import annotations

import numpy as np
import pytest

from d5freq.evaluation.diagnostic_metrics import (
    distinguishability_information,
    one_step_prediction_difference,
    pairwise_distinguishability_matrix,
)


def test_equations_38_and_39_are_evaluated_exactly() -> None:
    theta_m = np.array([1.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0])
    theta_n = np.array([0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    phi = np.array(
        [
            [1.0, 2.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            [-2.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        ]
    )
    expected_delta = phi @ (theta_m - theta_n)
    expected_information = np.sum(expected_delta**2) / (0.2 + 0.3)

    np.testing.assert_allclose(
        one_step_prediction_difference(theta_m, theta_n, phi), expected_delta
    )
    assert distinguishability_information(
        theta_m,
        theta_n,
        phi,
        residual_variance_m=0.2,
        residual_variance_n=0.3,
    ) == pytest.approx(expected_information)


def test_pairwise_matrix_is_symmetric_with_zero_diagonal() -> None:
    theta = np.array(
        [
            [0.8, -0.1, 0.2, 0.0, -0.4, 0.0, 0.0],
            [0.6, 0.1, 0.1, 0.0, -0.2, 0.0, 0.0],
            [0.2, 0.3, 0.02, 0.0, -0.1, 0.0, 0.0],
        ]
    )
    phi = np.arange(35, dtype=float).reshape(5, 7) / 10.0
    matrix = pairwise_distinguishability_matrix(theta, [0.1, 0.2, 0.3], phi)

    np.testing.assert_allclose(matrix, matrix.T)
    np.testing.assert_array_equal(np.diag(matrix), 0.0)
    assert np.all(matrix[np.triu_indices(3, k=1)] > 0.0)


def test_zero_total_variance_and_complex_data_are_rejected() -> None:
    theta = np.zeros(7)
    phi = np.ones((2, 7))
    with pytest.raises(ValueError, match="strictly positive"):
        distinguishability_information(
            theta,
            theta,
            phi,
            residual_variance_m=0.0,
            residual_variance_n=0.0,
        )
    with pytest.raises(TypeError, match="real-valued"):
        one_step_prediction_difference(theta.astype(complex) + 1j, theta, phi)
