from __future__ import annotations

import pytest

from d5freq.models.hidden_mode_ibr import (
    IBRModeParams,
    IBRState,
    asymmetric_saturation,
    ibr_derivative,
    step_ibr_rk4,
)


def _params() -> IBRModeParams:
    return IBRModeParams(
        name="asymmetric",
        command_gain=1.0,
        frequency_gain=0.0,
        command_filter_time_s=1.0,
        power_response_time_s=0.5,
        delay_s=0.0,
        p_max_pos_pu=0.02,
        p_max_neg_pu=0.07,
        ramp_up_pu_per_s=100.0,
        ramp_down_pu_per_s=100.0,
        deadband_pu=0.0,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-1.0, -0.07),
        (-0.07, -0.07),
        (-0.03, -0.03),
        (0.0, 0.0),
        (0.01, 0.01),
        (0.02, 0.02),
        (1.0, 0.02),
    ],
)
def test_asymmetric_saturation_matches_equation_14(value: float, expected: float) -> None:
    assert asymmetric_saturation(value, 0.02, 0.07) == pytest.approx(expected)


def test_output_dynamics_uses_saturated_q_not_unsaturated_q() -> None:
    params = _params()
    positive = ibr_derivative(IBRState(q_pu=1.0, p_ibr_pu=0.0), 1.0, 0.0, params)
    negative = ibr_derivative(IBRState(q_pu=-1.0, p_ibr_pu=0.0), -1.0, 0.0, params)
    assert positive[1] == pytest.approx(0.02 / 0.5)
    assert negative[1] == pytest.approx(-0.07 / 0.5)


def test_zero_capacity_clamps_both_directions() -> None:
    assert asymmetric_saturation(3.0, 0.0, 0.0) == 0.0
    assert asymmetric_saturation(-3.0, 0.0, 0.0) == 0.0


def test_derating_changes_target_without_instantly_clipping_physical_power() -> None:
    params = _params()
    initial = IBRState(q_pu=0.08, p_ibr_pu=0.08)
    after = step_ibr_rk4(initial, 0.08, 0.0, params, 0.01)

    assert 0.02 < after.p_ibr_pu < initial.p_ibr_pu


def test_saturation_rejects_negative_capacity() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        asymmetric_saturation(0.0, -0.01, 0.02)
    with pytest.raises(ValueError, match="non-negative"):
        asymmetric_saturation(0.0, 0.01, -0.02)
