from __future__ import annotations

import math

import numpy as np
import pytest

from d5freq.models.hidden_mode_ibr import (
    IBRModeParams,
    IBRState,
    ibr_derivative,
    step_ibr_rk4,
)


def _params(**overrides: object) -> IBRModeParams:
    values: dict[str, object] = {
        "name": "second-order",
        "command_gain": 1.0,
        "frequency_gain": 4.0,
        "command_filter_time_s": 0.2,
        "power_response_time_s": 0.5,
        "delay_s": 0.0,
        "p_max_pos_pu": 1.0,
        "p_max_neg_pu": 1.0,
        "ramp_up_pu_per_s": 100.0,
        "ramp_down_pu_per_s": 100.0,
        "deadband_pu": 0.005,
    }
    values.update(overrides)
    return IBRModeParams(**values)  # type: ignore[arg-type]


def test_state_array_round_trip_is_ordered_q_then_power() -> None:
    state = IBRState(q_pu=0.12, p_ibr_pu=-0.03)
    array = state.to_array()
    assert array.dtype == np.float64
    np.testing.assert_array_equal(array, np.array([0.12, -0.03]))
    assert IBRState.from_array(array) == state
    array[0] = 99.0
    assert state.q_pu == 0.12


def test_derivative_matches_equations_12_13_and_15() -> None:
    params = _params(
        command_gain=2.0,
        command_filter_time_s=0.1,
        power_response_time_s=0.2,
        p_max_pos_pu=0.05,
        ramp_up_pu_per_s=0.1,
    )
    state = IBRState(q_pu=0.06, p_ibr_pu=0.01)
    derivative = ibr_derivative(state, delayed_command_pu=0.03, omega_pu=0.002, params=params)
    # r = 2*(0.03-0.005) - 4*0.002 = 0.042; dq/dt=(r-q)/0.1.
    assert derivative[0] == pytest.approx(-0.18)
    # q_bar=0.05; raw dp/dt=(0.05-0.01)/0.2=0.2, clipped to +0.1.
    assert derivative[1] == pytest.approx(0.1)


def test_rk4_recovers_unlimited_cascade_step_response() -> None:
    params = _params(frequency_gain=0.0, deadband_pu=0.0)
    command = 0.04
    state = IBRState()
    dt = 0.002
    final_time = 1.0
    for _ in range(round(final_time / dt)):
        state = step_ibr_rk4(state, command, 0.0, params, dt)

    t_q = params.command_filter_time_s
    t_p = params.power_response_time_s
    expected_q = command * (1.0 - math.exp(-final_time / t_q))
    expected_p = command * (
        1.0
        + (
            t_q * math.exp(-final_time / t_q)
            - t_p * math.exp(-final_time / t_p)
        )
        / (t_p - t_q)
    )
    assert state.q_pu == pytest.approx(expected_q, abs=1.0e-11)
    assert state.p_ibr_pu == pytest.approx(expected_p, abs=1.0e-11)


def test_nominal_and_sluggish_modes_have_distinguishable_transients() -> None:
    nominal = _params(
        name="nominal",
        command_filter_time_s=0.10,
        power_response_time_s=0.20,
        command_gain=1.0,
    )
    sluggish = _params(
        name="sluggish",
        command_filter_time_s=0.60,
        power_response_time_s=1.00,
        command_gain=0.80,
    )
    states: dict[str, IBRState] = {"nominal": IBRState(), "sluggish": IBRState()}
    for _ in range(100):
        states["nominal"] = step_ibr_rk4(states["nominal"], 0.04, 0.0, nominal, 0.01)
        states["sluggish"] = step_ibr_rk4(states["sluggish"], 0.04, 0.0, sluggish, 0.01)
    assert states["nominal"].p_ibr_pu > states["sluggish"].p_ibr_pu
    assert abs(states["nominal"].p_ibr_pu - states["sluggish"].p_ibr_pu) > 0.01


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("command_filter_time_s", 0.0, "positive"),
        ("power_response_time_s", -1.0, "positive"),
        ("delay_s", -0.1, "non-negative"),
        ("command_gain", -1.0, "non-negative"),
        ("frequency_gain", math.inf, "finite"),
    ],
)
def test_mode_parameters_are_strictly_validated(field: str, value: float, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _params(**{field: value})


def test_state_and_step_reject_invalid_values() -> None:
    with pytest.raises(ValueError, match="exactly 2"):
        IBRState.from_array([0.0])
    with pytest.raises(ValueError, match="finite"):
        IBRState(q_pu=math.nan)
    with pytest.raises(ValueError, match="positive"):
        step_ibr_rk4(IBRState(), 0.0, 0.0, _params(), 0.0)


@pytest.mark.parametrize("bad_value", [True, "1.0"])
def test_mode_parameters_reject_bool_and_numeric_strings(bad_value: object) -> None:
    with pytest.raises(TypeError, match="real scalar"):
        _params(command_gain=bad_value)
