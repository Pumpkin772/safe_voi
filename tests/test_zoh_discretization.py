from __future__ import annotations

import numpy as np
from numpy.testing import assert_allclose
import pytest
from scipy.signal import cont2discrete

from d5freq.models import GridFrequencyModel, GridParams, exact_zoh


def _model() -> GridFrequencyModel:
    return GridFrequencyModel(
        GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    )


def test_augmented_exponential_matches_scipy_cont2discrete() -> None:
    model = _model()
    A_c, B_c, E_c, _ = model.continuous_matrices()
    A_d, B_d, E_d = exact_zoh(
        A_c, B_c, E_c, sample_time_s=model.params.control_period_s
    )

    combined = np.hstack((B_c, E_c))
    reference_A, reference_BE, _, _, _ = cont2discrete(
        (A_c, combined, np.eye(5), np.zeros((5, 2))),
        dt=model.params.control_period_s,
        method="zoh",
    )

    assert_allclose(A_d, reference_A, rtol=1e-13, atol=1e-14)
    assert_allclose(np.hstack((B_d, E_d)), reference_BE, rtol=1e-13, atol=1e-14)


def test_discrete_matrices_propagate_a_constant_equilibrium_exactly() -> None:
    model = _model()
    state = model.initial_state(
        p_mech_pu=0.03,
        p_valve_pu=0.03,
        xi_pu_s=0.7,
        load_disturbance_pu=0.05,
    )
    A_d, B_d, E_d, G_d = model.discrete_matrices()

    next_state = (
        A_d @ state
        + B_d[:, 0] * 0.03
        + E_d[:, 0] * 0.02
        + G_d[:, 0] * 0.0
    )

    assert_allclose(next_state, state, rtol=1e-13, atol=1e-14)


def test_exact_zoh_supports_multiple_input_widths() -> None:
    A_c = np.array([[-2.0, 0.0], [0.0, -3.0]])
    B_first = np.eye(2)
    B_second = np.array([[1.0], [2.0]])

    A_d, first_d, second_d = exact_zoh(
        A_c, B_first, B_second, sample_time_s=0.1
    )

    assert A_d.shape == (2, 2)
    assert first_d.shape == (2, 2)
    assert second_d.shape == (2, 1)
    assert_allclose(A_d, np.diag(np.exp([-0.2, -0.3])))


@pytest.mark.parametrize(
    ("A_c", "inputs", "sample_time_s", "message"),
    [
        (np.zeros((2, 3)), (), 0.1, "square"),
        (np.zeros((2, 2)), (np.zeros((3, 1)),), 0.1, "2 rows"),
        (np.zeros((2, 2)), (), 0.0, "strictly positive"),
        (np.array([[np.nan]]), (), 0.1, "finite"),
    ],
)
def test_exact_zoh_rejects_invalid_dimensions_or_values(
    A_c: np.ndarray,
    inputs: tuple[np.ndarray, ...],
    sample_time_s: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        exact_zoh(A_c, *inputs, sample_time_s=sample_time_s)
