from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np

from d5freq.evaluation.exact_nonlinear_oracle import (
    ExactNonlinearOracleController,
    ExactOracleBounds,
    ExactOracleContext,
    ExactOraclePlannerConfig,
    ExactOracleWeights,
    rollout_exact_current_mode_eval_only,
)
from d5freq.interfaces import ControlAction
from d5freq.interfaces import Measurement
from d5freq.controllers.lqi_fallback import LQIFallbackController
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.simulation.disturbances import LoadDisturbanceSpec
from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator, Scenario
from d5freq.simulation.mode_schedules import PiecewiseConstantModeSchedule


REPO = Path(__file__).resolve().parents[1]


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


def _mode() -> IBRModeParams:
    return IBRModeParams(
        name="nominal",
        command_gain=1.0,
        frequency_gain=4.0,
        command_filter_time_s=0.10,
        power_response_time_s=0.20,
        delay_s=0.10,
        p_max_pos_pu=0.08,
        p_max_neg_pu=0.08,
        ramp_up_pu_per_s=0.05,
        ramp_down_pu_per_s=0.05,
        deadband_pu=0.0005,
    )


def _scenario(*, duration_s: float = 2.0, base_load_pu: float = 0.0) -> Scenario:
    return Scenario(
        mode_schedule=PiecewiseConstantModeSchedule("nominal"),
        duration_s=duration_s,
        disturbance=LoadDisturbanceSpec(base_pu=base_load_pu),
        name="phase_b1_test",
    )


def _bounds() -> ExactOracleBounds:
    return ExactOracleBounds(
        sg_min_pu=-0.12,
        sg_max_pu=0.12,
        sg_ramp_pu_per_s=0.02,
    )


def test_b5_is_not_an_ordinary_frequency_controller() -> None:
    assert "act" not in ExactNonlinearOracleController.__dict__
    assert "act_evaluation_only" in ExactNonlinearOracleController.__dict__
    source = inspect.getsource(ExactNonlinearOracleController)
    assert "LQIFallback" not in source
    assert "fallback" not in source.lower()


def test_controller_and_estimation_packages_do_not_import_b5_truth_context() -> None:
    forbidden = (
        "ExactOracleContext",
        "exact_nonlinear_oracle",
        "true_mode_eval_only",
        "mode_params_eval_only",
        "truth_provider",
        "true_ibr_parameters",
    )
    for package in (REPO / "src/d5freq/controllers", REPO / "src/d5freq/estimation"):
        for path in package.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert not any(token in text for token in forbidden), path


def test_ordinary_runtime_controller_operates_with_truth_free_measurement_only() -> None:
    assert set(Measurement.__dataclass_fields__) == {
        "time_s",
        "omega_pu",
        "p_mech_pu",
        "p_ibr_pu",
        "u_sg_prev_pu",
        "u_ibr_prev_pu",
    }
    controller = LQIFallbackController(_grid())
    measurement = Measurement(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    controller.reset(measurement)
    action = controller.act(measurement)
    assert isinstance(action, ControlAction)


def test_exact_rollout_matches_physical_simulator_for_one_control_interval() -> None:
    grid = _grid()
    mode = _mode()
    scenario = _scenario(duration_s=1.0, base_load_pu=0.02)
    simulator = HiddenModeFrequencySimulator(grid, {mode.name: mode})
    simulator.reset(7, scenario)
    initial = np.concatenate(
        (
            simulator._grid_state.copy(),  # evaluator-only test of exact state parity
            simulator._ibr_state.to_array(),
        )
    )
    action = ControlAction(u_sg_pu=0.01, u_ibr_pu=0.02)
    rollout = rollout_exact_current_mode_eval_only(
        grid_model=grid,
        params_eval_only=mode,
        start_time_s=0.0,
        initial_state=initial,
        command_history=simulator._command_history,
        candidate_u_sg_pu=np.array([action.u_sg_pu]),
        candidate_u_ibr_pu=np.array([action.u_ibr_pu]),
        horizon_s=0.5,
        integration_step_s=0.02,
        bounds=_bounds(),
        weights=ExactOracleWeights(),
        previous_u_sg_pu=0.0,
        previous_u_ibr_pu=0.0,
    )
    simulator.step(action)
    expected = np.concatenate(
        (simulator._grid_state.copy(), simulator._ibr_state.to_array())
    )
    np.testing.assert_allclose(rollout.terminal_state[0], expected, rtol=0.0, atol=2e-14)


def test_b5_mirror_and_selected_first_actions_obey_hard_constraints() -> None:
    grid = _grid()
    mode = _mode()
    scenario = _scenario()
    seed = 301
    context = ExactOracleContext(
        grid_model=grid,
        mode_params_eval_only={mode.name: mode},
        scenario_eval_only=scenario,
        seed=seed,
        sg_level="A",
        bounds=_bounds(),
        planner=ExactOraclePlannerConfig(horizon_s=0.5),
    )
    controller = ExactNonlinearOracleController(context)
    simulator = HiddenModeFrequencySimulator(grid, {mode.name: mode})
    measurement = simulator.reset(seed, scenario)
    controller.reset(measurement)
    previous = measurement
    for _ in range(3):
        action = controller.act_evaluation_only(
            previous,
            true_mode_eval_only="nominal",
        )
        assert -0.12 <= action.u_sg_pu <= 0.12
        assert -0.08 <= action.u_ibr_pu <= 0.08
        assert abs(action.u_sg_pu - previous.u_sg_prev_pu) <= 0.01 + 1e-12
        assert abs(action.u_ibr_pu - previous.u_ibr_prev_pu) <= 0.02 + 1e-12
        previous, _ = simulator.step(action)
    assert len(controller.step_records) == 3
    assert max(row.mirror_measurement_max_abs_error for row in controller.step_records) <= 1e-11
