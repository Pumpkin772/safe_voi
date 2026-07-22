from __future__ import annotations

import pytest

from d5freq.simulation.mode_schedules import (
    ModeSwitch,
    PiecewiseConstantModeSchedule,
)


def test_piecewise_constant_schedule_switches_at_exact_boundary() -> None:
    schedule = PiecewiseConstantModeSchedule.from_pairs(
        "nominal", [(2.0, "sluggish"), (5.0, "derated")]
    )

    assert schedule.mode_at(0.0) == "nominal"
    assert schedule.mode_at(1.999) == "nominal"
    assert schedule.mode_at(2.0) == "sluggish"
    assert schedule.mode_at(4.999) == "sluggish"
    assert schedule.mode_at(5.0) == "derated"
    assert schedule.modes == ("nominal", "sluggish", "derated")
    assert schedule.switch_times_between(1.0, 5.0) == (2.0, 5.0)


def test_schedule_rejects_duplicate_or_unsorted_switches() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        PiecewiseConstantModeSchedule(
            "nominal", (ModeSwitch(2.0, "sluggish"), ModeSwitch(2.0, "derated"))
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        PiecewiseConstantModeSchedule(
            "nominal", (ModeSwitch(3.0, "sluggish"), ModeSwitch(2.0, "derated"))
        )
