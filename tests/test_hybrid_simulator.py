from __future__ import annotations

import numpy as np
import pytest

from d5freq.interfaces import ControlAction
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.simulation.disturbances import LoadDisturbanceSpec, LoadEvent
from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator, Scenario
from d5freq.simulation.mode_schedules import PiecewiseConstantModeSchedule


def _grid() -> GridFrequencyModel:
    return GridFrequencyModel(
        GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.1, 0.01)
    )


def _mode(name: str, *, command_gain: float = 1.0) -> IBRModeParams:
    return IBRModeParams(
        name=name,
        command_gain=command_gain,
        frequency_gain=4.0,
        command_filter_time_s=0.1,
        power_response_time_s=0.2,
        delay_s=0.0,
        p_max_pos_pu=0.08,
        p_max_neg_pu=0.08,
        ramp_up_pu_per_s=0.05,
        ramp_down_pu_per_s=0.05,
        deadband_pu=0.0005,
    )


def test_zero_state_and_zero_action_remain_at_equilibrium() -> None:
    simulator = HiddenModeFrequencySimulator(_grid(), {"nominal": _mode("nominal")})
    scenario = Scenario(
        PiecewiseConstantModeSchedule("nominal"), duration_s=0.3
    )
    initial = simulator.reset(1, scenario)
    measurement, evaluation = simulator.step(ControlAction(0.0, 0.0))

    assert initial.omega_pu == 0.0
    assert measurement.omega_pu == pytest.approx(0.0, abs=1.0e-15)
    assert measurement.p_mech_pu == pytest.approx(0.0, abs=1.0e-15)
    assert measurement.p_ibr_pu == pytest.approx(0.0, abs=1.0e-15)
    assert evaluation["true_mode_eval_only"] == "nominal"


def test_load_step_reduces_frequency_and_ibr_command_is_coupled() -> None:
    simulator = HiddenModeFrequencySimulator(_grid(), {"nominal": _mode("nominal")})
    scenario = Scenario(
        PiecewiseConstantModeSchedule("nominal"),
        duration_s=0.4,
        disturbance=LoadDisturbanceSpec(events=(LoadEvent(0.05, 0.06),)),
    )
    simulator.reset(2, scenario)
    first, _ = simulator.step(ControlAction(0.0, 0.0))
    assert first.omega_pu < 0.0

    second, evaluation = simulator.step(ControlAction(0.0, 0.05))
    assert second.p_ibr_pu > 0.0
    assert evaluation["load_disturbance_pu"] == pytest.approx(0.06)


def test_reset_seed_reproduces_load_and_measurement_noise() -> None:
    scenario = Scenario(
        PiecewiseConstantModeSchedule("nominal"),
        duration_s=0.2,
        disturbance=LoadDisturbanceSpec(
            sample_period_s=0.05,
            white_noise_std_pu=0.001,
        ),
        omega_measurement_std_pu=1.0e-4,
        power_measurement_std_pu=2.0e-4,
    )
    action = ControlAction(0.0, 0.0)
    simulators = [
        HiddenModeFrequencySimulator(_grid(), {"nominal": _mode("nominal")})
        for _ in range(3)
    ]
    traces: list[np.ndarray] = []
    for simulator, seed in zip(simulators, (5, 5, 6), strict=True):
        initial = simulator.reset(seed, scenario)
        next_measurement, _ = simulator.step(action)
        traces.append(
            np.array(
                [
                    initial.omega_pu,
                    initial.p_mech_pu,
                    next_measurement.omega_pu,
                    next_measurement.p_ibr_pu,
                ]
            )
        )
    np.testing.assert_array_equal(traces[0], traces[1])
    assert not np.array_equal(traces[0], traces[2])


def test_mode_switch_inside_control_period_preserves_state_and_changes_truth() -> None:
    modes = {"nominal": _mode("nominal"), "weak": _mode("weak", command_gain=0.05)}
    simulator = HiddenModeFrequencySimulator(_grid(), modes)
    scenario = Scenario(
        PiecewiseConstantModeSchedule.from_pairs("nominal", [(0.05, "weak")]),
        duration_s=0.1,
    )
    simulator.reset(0, scenario)
    measurement, evaluation = simulator.step(ControlAction(0.0, 0.04))
    assert measurement.time_s == pytest.approx(0.1)
    assert np.isfinite(measurement.p_ibr_pu)
    assert evaluation["true_mode_eval_only"] == "weak"
    assert evaluation["done"] is True


def test_right_continuous_events_do_not_leak_through_rk4_endpoint() -> None:
    modes = {"nominal": _mode("nominal"), "weak": _mode("weak", command_gain=0.0)}
    baseline = HiddenModeFrequencySimulator(_grid(), modes)
    switched = HiddenModeFrequencySimulator(_grid(), modes)
    loaded = HiddenModeFrequencySimulator(_grid(), modes)
    baseline.reset(
        3, Scenario(PiecewiseConstantModeSchedule("nominal"), duration_s=0.1)
    )
    switched.reset(
        3,
        Scenario(
            PiecewiseConstantModeSchedule.from_pairs("nominal", [(0.1, "weak")]),
            duration_s=0.1,
        ),
    )
    loaded.reset(
        3,
        Scenario(
            PiecewiseConstantModeSchedule("nominal"),
            duration_s=0.1,
            disturbance=LoadDisturbanceSpec(events=(LoadEvent(0.1, 0.06),)),
        ),
    )
    action = ControlAction(0.0, 0.04)
    baseline_measurement, _ = baseline.step(action)
    switched_measurement, switched_eval = switched.step(action)
    loaded_measurement, loaded_eval = loaded.step(action)

    assert switched_measurement == baseline_measurement
    assert switched_eval["true_mode_eval_only"] == "weak"
    assert loaded_measurement == baseline_measurement
    assert loaded_eval["load_disturbance_pu"] == pytest.approx(0.06)


def test_delayed_command_does_not_leak_into_pre_delay_rk4_interval() -> None:
    delayed = IBRModeParams(
        name="delayed",
        command_gain=1.0,
        frequency_gain=0.0,
        command_filter_time_s=0.1,
        power_response_time_s=0.2,
        delay_s=0.1,
        p_max_pos_pu=0.08,
        p_max_neg_pu=0.08,
        ramp_up_pu_per_s=0.05,
        ramp_down_pu_per_s=0.05,
        deadband_pu=0.0,
    )
    simulator = HiddenModeFrequencySimulator(_grid(), {"delayed": delayed})
    simulator.reset(
        0,
        Scenario(PiecewiseConstantModeSchedule("delayed"), duration_s=0.2),
    )

    at_delay, _ = simulator.step(ControlAction(0.0, 0.04))
    after_delay, _ = simulator.step(ControlAction(0.0, 0.04))

    assert at_delay.p_ibr_pu == pytest.approx(0.0, abs=1.0e-15)
    assert after_delay.p_ibr_pu > 0.0
