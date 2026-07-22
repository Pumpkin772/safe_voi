from __future__ import annotations

from dataclasses import asdict
import inspect

from d5freq.interfaces import ControlAction, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator, Scenario
from d5freq.simulation.mode_schedules import PiecewiseConstantModeSchedule


def _simulator() -> HiddenModeFrequencySimulator:
    grid = GridFrequencyModel(
        GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.1, 0.01)
    )
    mode = IBRModeParams(
        "opaque_a", 1.0, 4.0, 0.1, 0.2, 0.0, 0.08, 0.08, 0.05, 0.05, 0.0
    )
    return HiddenModeFrequencySimulator(grid, {"opaque_a": mode})


def test_true_mode_exists_only_in_separate_evaluation_record() -> None:
    simulator = _simulator()
    measurement = simulator.reset(
        0, Scenario(PiecewiseConstantModeSchedule("opaque_a"), duration_s=0.1)
    )
    next_measurement, evaluation = simulator.step(ControlAction(0.0, 0.0))

    for visible in (measurement, next_measurement):
        assert isinstance(visible, Measurement)
        visible_names = {name.lower() for name in asdict(visible)}
        assert all("mode" not in name and "true" not in name for name in visible_names)
    assert evaluation["true_mode_eval_only"] == "opaque_a"
    assert all(
        "mode" not in parameter.lower()
        for parameter in inspect.signature(HiddenModeFrequencySimulator.step).parameters
    )
