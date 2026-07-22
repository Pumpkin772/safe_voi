from __future__ import annotations

import math

import pytest

from d5freq.models.hidden_mode_ibr import (
    CommandHistory,
    IBRModeParams,
    SinusoidalDelayProfile,
    resolve_delay_s,
)


def _params(delay_s: float = 0.25, delay_profile: object | None = None) -> IBRModeParams:
    return IBRModeParams(
        name="delay-test",
        command_gain=1.0,
        frequency_gain=0.0,
        command_filter_time_s=0.1,
        power_response_time_s=0.2,
        delay_s=delay_s,
        p_max_pos_pu=1.0,
        p_max_neg_pu=1.0,
        ramp_up_pu_per_s=1.0,
        ramp_down_pu_per_s=1.0,
        deadband_pu=0.0,
        delay_profile=delay_profile,
    )


def test_command_history_uses_right_continuous_zero_order_hold() -> None:
    history = CommandHistory(initial_value_pu=-0.5)
    history.record(0.0, 1.0)
    history.record(1.0, 2.0)
    history.record(2.0, 3.0)

    assert history.delayed_value(0.0, 0.1) == -0.5
    assert history.delayed_value(1.49, 0.5) == 1.0
    assert history.delayed_value(1.5, 0.5) == 2.0
    assert history.delayed_value(2.25, 0.25) == 3.0


def test_duplicate_latest_timestamp_is_replaced_deterministically() -> None:
    history = CommandHistory()
    history.record(0.0, 1.0)
    history.record(0.0, 2.0)
    assert len(history) == 1
    assert history.times_s == (0.0,)
    assert history.values_pu == (2.0,)
    assert history.delayed_value(0.0, 0.0) == 2.0


def test_history_rejects_out_of_order_or_invalid_samples() -> None:
    history = CommandHistory()
    history.record(1.0, 0.1)
    with pytest.raises(ValueError, match="nondecreasing"):
        history.record(0.9, 0.2)
    with pytest.raises(ValueError, match="non-negative"):
        history.delayed_value(1.0, -0.1)
    with pytest.raises(ValueError, match="finite"):
        history.record(2.0, math.nan)


def test_fixed_delay_transition_times_are_reported_exactly() -> None:
    history = CommandHistory()
    history.record(0.0, 0.01)
    history.record(0.5, 0.02)
    assert history.delayed_transition_times_between(0.0, 1.0, 0.15) == (
        0.15,
        0.65,
    )
    assert history.delayed_transition_times_between(0.15, 0.65, 0.15) == (0.65,)
    with pytest.raises(ValueError, match="must not precede"):
        history.delayed_transition_times_between(1.0, 0.0, 0.15)


def test_fixed_delay_resolution() -> None:
    params = _params(delay_s=0.25)
    assert resolve_delay_s(params, 0.0) == 0.25
    assert resolve_delay_s(params, 100.0) == 0.25


def test_sinusoidal_ood_delay_is_bounded_and_repeatable() -> None:
    profile = SinusoidalDelayProfile(min_delay_s=0.1, max_delay_s=1.1, period_s=30.0)
    params = _params(delay_profile=profile)
    assert resolve_delay_s(params, 0.0) == pytest.approx(0.1)
    assert resolve_delay_s(params, 15.0) == pytest.approx(1.1)
    assert resolve_delay_s(params, 30.0) == pytest.approx(0.1)
    samples = [resolve_delay_s(params, time) for time in range(61)]
    assert min(samples) >= 0.1
    assert max(samples) <= 1.1
    assert samples[:31] == pytest.approx(samples[30:61])


def test_yaml_delay_profile_mapping_is_normalized() -> None:
    params = _params(
        delay_profile={
            "kind": "sinusoidal",
            "min_delay_s": 0.1,
            "max_delay_s": 1.1,
            "period_s": 30.0,
        }
    )
    assert isinstance(params.delay_profile, SinusoidalDelayProfile)
    assert resolve_delay_s(params, 15.0) == pytest.approx(1.1)


def test_time_varying_delay_drives_history_query_without_mutation() -> None:
    history = CommandHistory()
    history.record(0.0, 0.0)
    history.record(1.0, 1.0)
    history.record(2.0, 2.0)
    params = _params(delay_profile=lambda time_s: 0.5 * time_s)
    before = (history.times_s, history.values_pu)
    delay = resolve_delay_s(params, 2.0)
    assert history.delayed_value(2.0, delay) == 1.0
    assert (history.times_s, history.values_pu) == before


def test_resolved_delay_must_be_finite_and_nonnegative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        resolve_delay_s(_params(delay_profile=lambda _time: -0.1), 1.0)
    with pytest.raises(ValueError, match="finite"):
        resolve_delay_s(_params(delay_profile=lambda _time: math.nan), 1.0)
