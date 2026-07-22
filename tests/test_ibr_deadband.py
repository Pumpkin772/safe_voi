from __future__ import annotations

import math

import pytest

from d5freq.models.hidden_mode_ibr import IBRModeParams, IBRState, deadband, ibr_derivative


def _params(**overrides: float) -> IBRModeParams:
    values: dict[str, object] = {
        "name": "deadband-test",
        "command_gain": 2.0,
        "frequency_gain": 0.0,
        "command_filter_time_s": 0.5,
        "power_response_time_s": 1.0,
        "delay_s": 0.0,
        "p_max_pos_pu": 1.0,
        "p_max_neg_pu": 1.0,
        "ramp_up_pu_per_s": 10.0,
        "ramp_down_pu_per_s": 10.0,
        "deadband_pu": 0.01,
    }
    values.update(overrides)
    return IBRModeParams(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (0.0, 0.0),
        (0.005, 0.0),
        (-0.005, 0.0),
        (0.01, 0.0),
        (-0.01, 0.0),
        (0.03, 0.02),
        (-0.03, -0.02),
    ],
)
def test_deadband_matches_equation_11(command: float, expected: float) -> None:
    assert deadband(command, 0.01) == pytest.approx(expected)


def test_deadband_is_continuous_at_both_edges() -> None:
    epsilon = 1.0e-10
    assert deadband(0.01 + epsilon, 0.01) == pytest.approx(epsilon)
    assert deadband(-0.01 - epsilon, 0.01) == pytest.approx(-epsilon)


def test_deadband_is_applied_before_command_gain() -> None:
    params = _params()
    inside = ibr_derivative(IBRState(), 0.009, 0.0, params)
    outside = ibr_derivative(IBRState(), 0.03, 0.0, params)
    assert inside[0] == 0.0
    # r = 2 * (0.03 - 0.01), then dq/dt = r / 0.5.
    assert outside[0] == pytest.approx(0.08)


@pytest.mark.parametrize(
    ("value", "width", "message"),
    [
        (math.nan, 0.0, "finite"),
        (0.0, math.inf, "finite"),
        (0.0, -0.1, "non-negative"),
    ],
)
def test_deadband_rejects_invalid_inputs(value: float, width: float, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        deadband(value, width)
