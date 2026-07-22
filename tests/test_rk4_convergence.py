from __future__ import annotations

import math

import numpy as np
import pytest

from d5freq.simulation.integrators import integrate_rk4, rk4_step


def test_rk4_has_fourth_order_convergence() -> None:
    def derivative(_time_s: float, state: np.ndarray) -> np.ndarray:
        return state

    exact = math.e
    coarse = integrate_rk4(
        derivative,
        [1.0],
        start_time_s=0.0,
        duration_s=1.0,
        max_step_s=0.2,
    )[0]
    fine = integrate_rk4(
        derivative,
        [1.0],
        start_time_s=0.0,
        duration_s=1.0,
        max_step_s=0.1,
    )[0]

    assert abs(coarse - exact) / abs(fine - exact) > 12.0


def test_rk4_is_pure_and_validates_derivative_shape() -> None:
    initial = np.array([1.0, -2.0])
    before = initial.copy()
    result = rk4_step(lambda _t, state: -state, 0.0, initial, 0.1)

    np.testing.assert_array_equal(initial, before)
    assert result.shape == initial.shape
    with pytest.raises(ValueError, match="shape"):
        rk4_step(lambda _t, _state: np.zeros(3), 0.0, initial, 0.1)


def test_integrate_rk4_uses_a_short_final_step() -> None:
    result = integrate_rk4(
        lambda _t, _state: np.array([1.0]),
        [0.0],
        start_time_s=2.0,
        duration_s=0.25,
        max_step_s=0.1,
    )
    np.testing.assert_allclose(result, [0.25], atol=1.0e-15)
