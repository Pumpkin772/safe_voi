from __future__ import annotations

import numpy as np
import pytest
from scipy.linalg import solve_discrete_are

from d5freq.controllers.lqi_fallback import (
    LQIFallbackConfig,
    LQIFallbackController,
    design_lqi_gain,
    reduced_discrete_grid_matrices,
)
from d5freq.interfaces import Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.simulation.disturbances import LoadDisturbanceSpec
from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator, Scenario
from d5freq.simulation.mode_schedules import PiecewiseConstantModeSchedule


def _grid() -> GridFrequencyModel:
    return GridFrequencyModel(
        GridParams(
            f0_hz=50.0,
            M_s=8.0,
            D_pu=1.0,
            T_t_s=0.5,
            T_g_s=0.2,
            R_pu=0.08,
            control_period_s=0.5,
            integration_step_s=0.02,
        )
    )


def _measurement(
    *,
    time_s: float = 0.0,
    u_sg_prev_pu: float = 0.0,
    u_ibr_prev_pu: float = 0.0,
) -> Measurement:
    return Measurement(
        time_s=time_s,
        omega_pu=0.0,
        p_mech_pu=0.0,
        p_ibr_pu=0.0,
        u_sg_prev_pu=u_sg_prev_pu,
        u_ibr_prev_pu=u_ibr_prev_pu,
    )


class FixedEstimator:
    def __init__(self, state: np.ndarray) -> None:
        self.state = np.asarray(state, dtype=float)
        self.reset_calls = 0
        self.update_calls = 0

    def reset_from_measurement(self, measurement: Measurement) -> np.ndarray:
        self.reset_calls += 1
        return self.state.copy()

    def update_from_measurement(self, measurement: Measurement) -> np.ndarray:
        self.update_calls += 1
        return self.state.copy()


def test_dare_gain_matches_equation_75_and_is_schur_stable() -> None:
    grid = _grid()
    config = LQIFallbackConfig()
    A_reduced, B_reduced = reduced_discrete_grid_matrices(grid)
    Q = np.diag(config.q_weights)
    R = np.array([[config.r_sg]])
    P = solve_discrete_are(A_reduced, B_reduced, Q, R)
    expected_gain = np.linalg.solve(
        R + B_reduced.T @ P @ B_reduced,
        B_reduced.T @ P @ A_reduced,
    )

    gain = design_lqi_gain(grid, config.q_weights, config.r_sg)
    np.testing.assert_allclose(gain, expected_gain, rtol=1.0e-12, atol=1.0e-12)
    assert gain.shape == (1, 4)
    closed_loop_poles = np.linalg.eigvals(A_reduced - B_reduced @ gain)
    assert np.max(np.abs(closed_loop_poles)) < 1.0


def test_dare_excludes_uncontrollable_load_state() -> None:
    grid = _grid()
    A_reduced, B_reduced = reduced_discrete_grid_matrices(grid)
    controller = LQIFallbackController(grid)
    assert A_reduced.shape == (4, 4)
    assert B_reduced.shape == (4, 1)
    np.testing.assert_array_equal(controller.reduced_state_matrix, A_reduced)
    np.testing.assert_array_equal(controller.reduced_input_matrix, B_reduced)
    assert controller.riccati_solution.shape == (4, 4)
    assert np.min(np.linalg.eigvalsh(controller.riccati_solution)) > 0.0


def test_equilibrium_translation_uses_disturbance_estimate() -> None:
    disturbance = 0.04
    estimate = np.array([0.0, disturbance, disturbance, 0.0, disturbance])
    estimator = FixedEstimator(estimate)
    controller = LQIFallbackController(_grid(), estimator=estimator)
    measurement = _measurement(
        u_sg_prev_pu=disturbance,
        u_ibr_prev_pu=0.03,
    )
    controller.reset(measurement)
    action = controller.act(measurement)

    assert controller.unconstrained_sg_command(estimate) == pytest.approx(disturbance)
    assert action.u_sg_pu == pytest.approx(disturbance)
    assert action.u_ibr_pu == pytest.approx(0.01)
    assert estimator.reset_calls == 1
    # reset(initial) followed by act(initial) must not predict one period early.
    assert estimator.update_calls == 0

    controller.act(_measurement(time_s=0.5, u_sg_prev_pu=action.u_sg_pu))
    assert estimator.update_calls == 1


def test_mid_episode_fallback_reuses_external_estimate_without_reset() -> None:
    estimator = FixedEstimator(np.zeros(5))
    controller = LQIFallbackController(_grid(), estimator=estimator)
    controller.reset(_measurement())

    # A composite controller must keep one continuously propagated estimate;
    # resetting here would erase the unmeasured integral-state history.
    external_estimate = np.array([-0.001, 0.03, 0.025, 0.004, 0.03])
    action = controller.action_from_estimate(
        _measurement(time_s=8.0, u_sg_prev_pu=0.02),
        external_estimate,
    )

    assert action.controller_state == "LQI_FALLBACK"
    assert estimator.reset_calls == 1
    assert estimator.update_calls == 0


@pytest.mark.parametrize(
    ("omega_pu", "previous", "expected"),
    [
        (-0.1, 0.0, 0.01),
        (0.1, 0.0, -0.01),
        (-0.1, 0.119, 0.12),
        (0.1, -0.119, -0.12),
    ],
)
def test_sg_action_obeys_amplitude_and_rate_limits(
    omega_pu: float,
    previous: float,
    expected: float,
) -> None:
    controller = LQIFallbackController(_grid())
    estimate = np.array([omega_pu, 0.0, 0.0, 0.0, 0.0])
    action = controller.action_from_estimate(
        _measurement(u_sg_prev_pu=previous), estimate
    )
    assert action.u_sg_pu == pytest.approx(expected)
    assert -0.12 <= action.u_sg_pu <= 0.12
    assert abs(action.u_sg_pu - previous) <= 0.02 * 0.5 + 1.0e-12


def test_lqi_fallback_recovers_frequency_with_ibr_unavailable() -> None:
    grid = _grid()
    unavailable = IBRModeParams(
        name="unavailable",
        command_gain=0.0,
        frequency_gain=0.0,
        command_filter_time_s=0.4,
        power_response_time_s=0.8,
        delay_s=0.4,
        p_max_pos_pu=0.0,
        p_max_neg_pu=0.0,
        ramp_up_pu_per_s=0.0,
        ramp_down_pu_per_s=0.0,
        deadband_pu=0.0,
    )
    simulator = HiddenModeFrequencySimulator(grid, {"unavailable": unavailable})
    scenario = Scenario(
        mode_schedule=PiecewiseConstantModeSchedule("unavailable"),
        duration_s=60.0,
        disturbance=LoadDisturbanceSpec(base_pu=0.04),
        name="lqi_recovery",
    )
    measurement = simulator.reset(7, scenario)
    controller = LQIFallbackController(grid)
    controller.reset(measurement)

    commands: list[float] = []
    done = False
    while not done:
        action = controller.act(measurement)
        commands.append(action.u_sg_pu)
        measurement, evaluation = simulator.step(action)
        done = bool(evaluation["done"])

    assert abs(measurement.omega_pu * grid.params.f0_hz) < 0.01
    assert measurement.p_mech_pu == pytest.approx(0.04, abs=2.0e-3)
    assert max(commands) <= 0.12
    assert min(commands) >= -0.12
    assert max(abs(right - left) for left, right in zip([0.0, *commands], commands)) <= (
        0.02 * grid.params.control_period_s + 1.0e-12
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("r_sg", 0.0, "positive"),
        ("u_sg_ramp_pu_per_s", -0.1, "non-negative"),
        ("ibr_withdraw_rate_pu_per_s", -0.1, "non-negative"),
    ],
)
def test_lqi_config_rejects_invalid_values(
    field: str, value: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        LQIFallbackConfig(**{field: value})
