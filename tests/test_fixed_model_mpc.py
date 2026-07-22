from __future__ import annotations

import inspect

from d5freq.controllers.fixed_model_mpc import FixedNominalMPCController
from d5freq.estimation.grid_kalman_filter import GridKalmanFilter
from d5freq.interfaces import Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.optimization.linear_mpc import LinearMPC, MPCBounds, linearize_grid_ibr
from d5freq.simulation.disturbances import LoadDisturbanceSpec, LoadEvent
from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator, Scenario
from d5freq.simulation.mode_schedules import PiecewiseConstantModeSchedule


def _controller() -> FixedNominalMPCController:
    grid = GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    nominal = IBRModeParams(
        "nominal", 1.0, 4.0, 0.1, 0.2, 0.1, 0.08, 0.08, 0.05, 0.05, 0.0005
    )
    mpc = LinearMPC(
        linearize_grid_ibr(grid, nominal),
        horizon_steps=6,
        bounds=MPCBounds(ramp_pu_per_s=(0.02, 0.04)),
        solver_priority=("CLARABEL",),
    )
    return FixedNominalMPCController(mpc)


def test_fixed_controller_is_controller_visible_and_returns_feasible_action() -> None:
    controller = _controller()
    measurement = Measurement(0.0, -0.002, 0.0, 0.0, 0.0, 0.0)
    controller.reset(measurement)
    action = controller.act(measurement)

    assert action.solver_status in {"optimal", "optimal_inaccurate"}
    assert action.controller_state == "FIXED_NOMINAL_MPC"
    assert -0.01 - 1.0e-7 <= action.u_sg_pu <= 0.01 + 1.0e-7
    assert -0.02 - 1.0e-7 <= action.u_ibr_pu <= 0.02 + 1.0e-7
    assert action.u_sg_pu + action.u_ibr_pu > 0.0


def test_fixed_controller_api_has_no_truth_argument() -> None:
    signature = inspect.signature(FixedNominalMPCController.act)
    assert tuple(signature.parameters) == ("self", "measurement")
    assert "true" not in str(signature).lower()


def test_fixed_mpc_with_grid_estimator_rejects_steady_load_offset() -> None:
    grid_params = GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    grid_model = GridFrequencyModel(grid_params)
    nominal = IBRModeParams(
        "nominal", 1.0, 4.0, 0.1, 0.2, 0.1, 0.08, 0.08, 0.05, 0.05, 0.0005
    )
    simulator = HiddenModeFrequencySimulator(grid_model, {"nominal": nominal})
    scenario = Scenario(
        PiecewiseConstantModeSchedule("nominal"),
        duration_s=90.0,
        disturbance=LoadDisturbanceSpec(events=(LoadEvent(5.0, 0.04),)),
    )
    estimator = GridKalmanFilter(
        grid_model,
        load_random_walk_std_pu_per_s=1.0e-4,
    )
    controller = FixedNominalMPCController(
        LinearMPC(
            linearize_grid_ibr(grid_params, nominal),
            horizon_steps=20,
            bounds=MPCBounds(ramp_pu_per_s=(0.02, 0.04)),
            solver_priority=("CLARABEL",),
        ),
        grid_state_estimator=estimator,
    )
    measurement = simulator.reset(17, scenario)
    controller.reset(measurement)
    frequency_tail_hz: list[float] = []
    done = False
    while not done:
        action = controller.act(measurement)
        assert action.solver_status in {"optimal", "optimal_inaccurate"}
        measurement, evaluation = simulator.step(action)
        done = bool(evaluation["done"])
        if measurement.time_s >= 80.0:
            frequency_tail_hz.append(grid_params.f0_hz * measurement.omega_pu)

    assert max(abs(value) for value in frequency_tail_hz) < 0.002
    assert abs(estimator.load_disturbance_estimate_pu - 0.04) < 5.0e-4
