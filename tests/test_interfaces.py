from __future__ import annotations

from dataclasses import fields
import inspect

import pytest

from d5freq.interfaces import ControlAction, FrequencyController, Measurement


def test_controller_visible_types_contain_no_truth_field() -> None:
    names = {field.name for field in fields(Measurement)} | {
        field.name for field in fields(ControlAction)
    }
    assert all("true" not in name.lower() for name in names)
    assert all("mode" not in name.lower() for name in names)
    assert "true_mode" not in str(inspect.signature(FrequencyController.act))


def test_measurement_and_action_validate_finite_values() -> None:
    measurement = Measurement(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert measurement.time_s == 0.0
    with pytest.raises(ValueError, match="finite"):
        Measurement(0.0, float("nan"), 0.0, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="non-negative"):
        ControlAction(0.0, 0.0, solve_time_s=-1.0)

