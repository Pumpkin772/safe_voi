from __future__ import annotations

import pytest

from d5freq.models.hidden_mode_ibr import (
    IBRModeParams,
    IBRState,
    ibr_derivative,
    ramp_limited_power_derivative,
    step_ibr_rk4,
)


def _params() -> IBRModeParams:
    return IBRModeParams(
        name="ramp-test",
        command_gain=1.0,
        frequency_gain=0.0,
        command_filter_time_s=1.0,
        power_response_time_s=0.01,
        delay_s=0.0,
        p_max_pos_pu=0.5,
        p_max_neg_pu=0.5,
        ramp_up_pu_per_s=0.04,
        ramp_down_pu_per_s=0.06,
        deadband_pu=0.0,
    )


def test_ramp_limiter_clips_up_and_down_independently() -> None:
    assert ramp_limited_power_derivative(1.0, 0.0, 0.5, 0.03, 0.07) == pytest.approx(0.03)
    assert ramp_limited_power_derivative(-1.0, 0.0, 0.5, 0.03, 0.07) == pytest.approx(-0.07)


def test_ramp_limiter_preserves_unconstrained_derivative_inside_limits() -> None:
    assert ramp_limited_power_derivative(0.01, 0.0, 0.5, 0.03, 0.07) == pytest.approx(0.02)
    assert ramp_limited_power_derivative(-0.01, 0.0, 0.5, 0.03, 0.07) == pytest.approx(-0.02)


def test_derivative_applies_asymmetric_mode_ramps() -> None:
    params = _params()
    upward = ibr_derivative(IBRState(q_pu=1.0), 1.0, 0.0, params)
    downward = ibr_derivative(IBRState(q_pu=-1.0), -1.0, 0.0, params)
    assert upward[1] == pytest.approx(params.ramp_up_pu_per_s)
    assert downward[1] == pytest.approx(-params.ramp_down_pu_per_s)


def test_rk4_step_obeys_active_ramp_limits() -> None:
    params = _params()
    upward = step_ibr_rk4(IBRState(q_pu=2.0), 2.0, 0.0, params, 0.1)
    downward = step_ibr_rk4(IBRState(q_pu=-2.0), -2.0, 0.0, params, 0.1)
    assert upward.q_pu == pytest.approx(2.0)
    assert upward.p_ibr_pu == pytest.approx(0.04 * 0.1)
    assert downward.q_pu == pytest.approx(-2.0)
    assert downward.p_ibr_pu == pytest.approx(-0.06 * 0.1)


def test_ramp_limiter_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError, match="positive"):
        ramp_limited_power_derivative(0.0, 0.0, 0.0, 1.0, 1.0)
    with pytest.raises(ValueError, match="non-negative"):
        ramp_limited_power_derivative(0.0, 0.0, 1.0, -1.0, 1.0)
