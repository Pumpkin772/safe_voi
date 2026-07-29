from __future__ import annotations

import numpy as np
import pytest

from d5freq.models.grid_frequency import GridParams
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.optimization.linear_mpc import (
    LinearMPC,
    LinearPredictionModel,
    MPCBounds,
    MPCWeights,
    linearize_grid_ibr,
)


# CVXPY 1.9.2 computes only the output shape of ``cp.sum`` by reducing an
# uninitialized ``np.empty`` placeholder.  Depending on prior allocator state,
# that placeholder can contain max-float values and emit an irrelevant overflow
# warning before any optimization value exists.  Keep every other warning fatal.
pytestmark = pytest.mark.filterwarnings(
    "ignore:overflow encountered in reduce:RuntimeWarning"
)


def _optimizer() -> LinearMPC:
    grid = GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    ibr = IBRModeParams(
        "nominal", 1.0, 4.0, 0.1, 0.2, 0.1, 0.08, 0.08, 0.05, 0.05, 0.0005
    )
    return LinearMPC(
        linearize_grid_ibr(grid, ibr),
        horizon_steps=8,
        weights=MPCWeights(),
        bounds=MPCBounds(
            u_min_pu=(-0.04, -0.03),
            u_max_pu=(0.04, 0.03),
            ramp_pu_per_s=(0.01, 0.02),
        ),
        solver_priority=("CLARABEL",),
    )


def test_mpc_uses_one_shared_sequence_and_satisfies_dynamics() -> None:
    optimizer = _optimizer()
    initial = np.zeros(7)
    initial[4] = 0.04
    result = optimizer.solve(initial, np.zeros(2))

    assert result.success
    assert result.control_sequence is not None
    assert result.state_sequence is not None
    assert result.control_sequence.shape == (2, optimizer.horizon_steps)
    for index in range(optimizer.horizon_steps):
        expected = (
            optimizer.model.A @ result.state_sequence[:, index]
            + optimizer.model.B @ result.control_sequence[:, index]
        )
        np.testing.assert_allclose(
            result.state_sequence[:, index + 1], expected, atol=2.0e-8
        )


def test_input_and_rate_constraints_hold_across_horizon() -> None:
    optimizer = _optimizer()
    initial = np.zeros(7)
    initial[0] = -0.002
    previous = np.array([0.003, -0.004])
    result = optimizer.solve(initial, previous)

    assert result.success and result.control_sequence is not None
    controls = result.control_sequence
    assert np.all(controls >= optimizer.bounds.lower[:, None] - 2.0e-7)
    assert np.all(controls <= optimizer.bounds.upper[:, None] + 2.0e-7)
    changes = np.diff(np.column_stack((previous, controls)), axis=1)
    maximum = optimizer.bounds.ramp[:, None] * optimizer.model.sample_time_s
    assert np.all(np.abs(changes) <= maximum + 2.0e-7)
    powers = result.state_sequence[6]
    assert np.all(powers[1:] >= optimizer.model.p_ibr_min_pu - 2.0e-7)
    assert np.all(powers[1:] <= optimizer.model.p_ibr_max_pu + 2.0e-7)
    power_changes = np.diff(powers)
    assert np.all(
        power_changes
        <= optimizer.model.p_ibr_ramp_up_pu_per_s
        * optimizer.model.sample_time_s
        + 2.0e-7
    )
    assert np.all(
        power_changes
        >= -optimizer.model.p_ibr_ramp_down_pu_per_s
        * optimizer.model.sample_time_s
        - 2.0e-7
    )


def test_linearization_has_expected_seven_state_two_input_shape() -> None:
    optimizer = _optimizer()
    assert optimizer.model.A.shape == (7, 7)
    assert optimizer.model.B.shape == (7, 2)
    assert optimizer.model.B[5, 1] > 0.0
    assert optimizer.model.B[0, 0] != 0.0


def test_new_lower_capacity_mode_uses_reachable_initial_power_envelope() -> None:
    grid = GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    derated = IBRModeParams(
        "derated", 1.0, 4.0, 0.15, 0.3, 0.15, 0.035, 0.035, 0.015, 0.015, 0.0005
    )
    optimizer = LinearMPC(
        linearize_grid_ibr(grid, derated),
        horizon_steps=5,
        bounds=MPCBounds(ramp_pu_per_s=(0.02, 0.04)),
        solver_priority=("CLARABEL",),
    )
    initial = np.zeros(7)
    initial[5:] = 0.08
    result = optimizer.solve(initial, np.array([0.0, 0.08]))

    assert result.success and result.state_sequence is not None
    assert result.max_power_slack_pu is not None
    upper_envelope = np.maximum(
        0.035,
        0.08 - np.arange(1, 6) * 0.015 * grid.control_period_s,
    )
    assert np.all(
        result.state_sequence[6, 1:]
        <= upper_envelope + result.max_power_slack_pu + 2.0e-7
    )
    transient_changes = np.diff(result.state_sequence[6])
    assert np.all(
        transient_changes
        <= 0.015 * grid.control_period_s + result.max_power_slack_pu + 2.0e-7
    )
    assert np.all(
        transient_changes
        >= -0.015 * grid.control_period_s - result.max_power_slack_pu - 2.0e-7
    )


def test_zero_capacity_unavailable_model_is_a_valid_fixed_power_constraint() -> None:
    grid = GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    unavailable = IBRModeParams(
        "unavailable", 0.0, 0.0, 0.4, 0.8, 0.4, 0.0, 0.0, 0.008, 0.008, 0.002
    )
    optimizer = LinearMPC(
        linearize_grid_ibr(grid, unavailable),
        horizon_steps=3,
        solver_priority=("CLARABEL",),
    )
    result = optimizer.solve(np.zeros(7), np.zeros(2))

    assert result.success and result.state_sequence is not None
    np.testing.assert_allclose(result.state_sequence[6], 0.0, atol=1.0e-9)


def test_horizon_one_matches_independent_unconstrained_kkt_solution() -> None:
    A = np.eye(7)
    B = np.zeros((7, 2))
    input_to_frequency = np.array([0.2, -0.1])
    B[0] = input_to_frequency
    model = LinearPredictionModel(A, B, sample_time_s=1.0, f0_hz=1.0)
    weights = MPCWeights(
        q_freq=0.0,
        q_integral=0.0,
        q_rocof=2.0,
        r_sg=3.0,
        r_ibr=4.0,
        s_delta_sg=5.0,
        s_delta_ibr=6.0,
        q_terminal_freq=7.0,
        q_terminal_integral=0.0,
    )
    optimizer = LinearMPC(
        model,
        horizon_steps=1,
        weights=weights,
        bounds=MPCBounds(
            u_min_pu=(-100.0, -100.0),
            u_max_pu=(100.0, 100.0),
            ramp_pu_per_s=(100.0, 100.0),
        ),
        solver_priority=("CLARABEL",),
    )
    initial = np.zeros(7)
    initial[0] = 0.3
    previous = np.array([0.1, -0.2])

    result = optimizer.solve(initial, previous)
    assert result.success
    curvature = (
        (weights.q_rocof + weights.q_terminal_freq)
        * np.outer(input_to_frequency, input_to_frequency)
        + np.diag(weights.input_weights + weights.delta_weights)
    )
    right_hand_side = (
        weights.delta_weights * previous
        - weights.q_terminal_freq * initial[0] * input_to_frequency
    )
    expected = np.linalg.solve(curvature, right_hand_side)
    np.testing.assert_allclose(result.first_action, expected, rtol=2.0e-7, atol=2.0e-8)
