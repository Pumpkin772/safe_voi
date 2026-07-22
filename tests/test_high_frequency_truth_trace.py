from __future__ import annotations

from dataclasses import fields

import numpy as np
import pytest

from d5freq.interfaces import ControlAction, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.simulation.disturbances import LoadDisturbanceSpec, LoadEvent
from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator, Scenario
from d5freq.simulation.mode_schedules import PiecewiseConstantModeSchedule


def _grid() -> GridFrequencyModel:
    return GridFrequencyModel(
        GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02)
    )


def _mode(name: str, command_gain: float = 1.0) -> IBRModeParams:
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
        deadband_pu=0.0,
    )


def _event_scenario() -> Scenario:
    return Scenario(
        mode_schedule=PiecewiseConstantModeSchedule.from_pairs(
            "nominal", [(0.055, "sluggish")]
        ),
        duration_s=0.5,
        disturbance=LoadDisturbanceSpec(events=(LoadEvent(0.073, 0.06),)),
        name="event_boundary_test",
    )


def test_truth_trace_contains_every_rk4_and_off_grid_event_endpoint() -> None:
    grid = _grid()
    simulator = HiddenModeFrequencySimulator(
        grid,
        {"nominal": _mode("nominal"), "sluggish": _mode("sluggish", 0.8)},
    )
    simulator.reset(12, _event_scenario())
    measurement, evaluation = simulator.step(ControlAction(0.0, 0.03))

    points = evaluation["true_trace_points_eval_only"]
    intervals = evaluation["true_trace_intervals_eval_only"]
    times = np.asarray([point["time_s"] for point in points], dtype=float)
    assert times[0] == 0.0
    assert times[-1] == pytest.approx(0.5)
    assert np.any(np.isclose(times, 0.055, atol=1.0e-15, rtol=0.0))
    assert np.any(np.isclose(times, 0.073, atol=1.0e-15, rtol=0.0))
    assert np.all(np.diff(times) > 0.0)
    assert np.max(np.diff(times)) <= 0.02 + 1.0e-14
    assert len(points) == len(intervals) + 1
    assert sum(
        interval["end_time_s"] - interval["start_time_s"] for interval in intervals
    ) == pytest.approx(0.5, abs=1.0e-14)
    assert points[-1]["omega_true_pu"] == pytest.approx(
        evaluation["omega_true_pu"], abs=0.0
    )
    assert points[-1]["p_mech_true_pu"] == pytest.approx(
        evaluation["p_mech_true_pu"], abs=0.0
    )
    assert points[-1]["p_ibr_true_pu"] == pytest.approx(
        evaluation["p_ibr_true_pu"], abs=0.0
    )
    for point in points:
        expected_rocof = grid.params.f0_hz * (
            -grid.params.D_pu * point["omega_true_pu"]
            + point["p_mech_true_pu"]
            + point["p_ibr_true_pu"]
            - point["load_disturbance_pu"]
        ) / grid.params.M_s
        assert point["rocof_true_hz_per_s"] == pytest.approx(
            expected_rocof, rel=0.0, abs=1.0e-15
        )
    event_point = next(
        point for point in points if point["time_s"] == pytest.approx(0.073)
    )
    assert event_point["load_disturbance_pu"] == pytest.approx(0.06)
    # The event sample uses the right-continuous load, rather than a numerical
    # gradient that would smear the discontinuity across adjacent samples.
    assert event_point["rocof_true_hz_per_s"] < -0.3
    assert measurement.time_s == pytest.approx(0.5)


def test_mode_interval_marks_left_integration_mode_and_right_continuous_end() -> None:
    simulator = HiddenModeFrequencySimulator(
        _grid(),
        {"nominal": _mode("nominal"), "sluggish": _mode("sluggish", 0.8)},
    )
    simulator.reset(1, _event_scenario())
    _, evaluation = simulator.step(ControlAction(0.0, 0.0))
    intervals = evaluation["true_trace_intervals_eval_only"]
    switch_interval = next(
        row for row in intervals if row["end_time_s"] == pytest.approx(0.055)
    )
    assert switch_interval["true_mode_start_eval_only"] == "nominal"
    assert switch_interval["true_mode_end_eval_only"] == "sluggish"
    point = next(
        row
        for row in evaluation["true_trace_points_eval_only"]
        if row["time_s"] == pytest.approx(0.055)
    )
    assert point["true_mode_eval_only"] == "sluggish"


def test_high_frequency_trace_supports_nonuniform_trapezoidal_integration() -> None:
    simulator = HiddenModeFrequencySimulator(
        _grid(),
        {"nominal": _mode("nominal"), "sluggish": _mode("sluggish", 0.8)},
    )
    simulator.reset(2, _event_scenario())
    _, evaluation = simulator.step(ControlAction(0.0, 0.0))
    points = evaluation["true_trace_points_eval_only"]
    time_s = np.asarray([row["time_s"] for row in points], dtype=float)
    frequency_hz = 50.0 * np.asarray(
        [row["omega_true_pu"] for row in points], dtype=float
    )

    iae_hz_s = float(np.trapezoid(np.abs(frequency_hz), time_s))
    ise_hz2_s = float(np.trapezoid(frequency_hz**2, time_s))
    assert iae_hz_s > 0.0
    assert ise_hz2_s > 0.0
    assert np.isfinite(iae_hz_s)
    assert np.isfinite(ise_hz2_s)


def test_trace_is_bitwise_reproducible_and_control_boundaries_are_duplicated() -> None:
    scenario = Scenario(
        PiecewiseConstantModeSchedule("nominal"),
        duration_s=1.0,
        disturbance=LoadDisturbanceSpec(
            sample_period_s=0.5,
            white_noise_std_pu=1.0e-3,
            random_walk_step_std_pu=7.071067811865475e-5,
        ),
        omega_measurement_std_pu=1.0e-4,
        power_measurement_std_pu=3.0e-3,
    )
    all_runs: list[list[tuple[dict[str, object], ...]]] = []
    for _ in range(2):
        simulator = HiddenModeFrequencySimulator(_grid(), {"nominal": _mode("nominal")})
        simulator.reset(99, scenario)
        run: list[tuple[dict[str, object], ...]] = []
        for action in (ControlAction(0.01, 0.02), ControlAction(-0.01, 0.01)):
            _, evaluation = simulator.step(action)
            run.append(evaluation["true_trace_points_eval_only"])
        all_runs.append(run)

    assert all_runs[0] == all_runs[1]
    assert all_runs[0][0][-1] == all_runs[0][1][0]


def test_truth_trace_remains_outside_measurement_and_controller_visible_api() -> None:
    simulator = HiddenModeFrequencySimulator(_grid(), {"nominal": _mode("nominal")})
    measurement = simulator.reset(
        0, Scenario(PiecewiseConstantModeSchedule("nominal"), duration_s=0.5)
    )
    next_measurement, evaluation = simulator.step(ControlAction(0.0, 0.0))

    measurement_fields = {field.name for field in fields(Measurement)}
    assert not any("mode" in name or "truth" in name for name in measurement_fields)
    assert not hasattr(measurement, "true_trace_points_eval_only")
    assert not hasattr(next_measurement, "true_mode_eval_only")
    assert "true_trace_points_eval_only" in evaluation
    assert "true_trace_intervals_eval_only" in evaluation
