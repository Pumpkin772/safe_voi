from __future__ import annotations

import inspect
import math

import numpy as np
import pytest

from d5freq.controllers.base import (
    FallbackTrigger,
    clip_with_rate_limit,
    fallback_required,
    withdraw_toward_zero,
)
from d5freq.controllers.lqi_fallback import LQIFallbackController
from d5freq.interfaces import FrequencyController, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams


def _grid() -> GridFrequencyModel:
    return GridFrequencyModel(GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.5, 0.02))


@pytest.mark.parametrize(
    "overrides",
    [
        {"ood_active": True},
        {"solver_failed": True},
        {"frequency_slack_hz": 0.021},
        {"timed_out": True},
    ],
)
def test_each_equation_70_condition_triggers_fallback(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "ood_active": False,
        "solver_failed": False,
        "frequency_slack_hz": 0.0,
        "max_acceptable_slack_hz": 0.02,
        "timed_out": False,
    }
    values.update(overrides)
    assert fallback_required(**values) is True  # type: ignore[arg-type]


def test_fallback_slack_threshold_is_strict_and_reasons_are_auditable() -> None:
    at_threshold = FallbackTrigger(
        frequency_slack_hz=0.02,
        max_acceptable_slack_hz=0.02,
    )
    assert at_threshold.active is False
    assert at_threshold.indicator == 0
    assert at_threshold.reasons == ()

    active = FallbackTrigger(
        ood_active=True,
        solver_failed=True,
        frequency_slack_hz=0.03,
        max_acceptable_slack_hz=0.02,
        timed_out=True,
    )
    assert active.indicator == 1
    assert active.reasons == ("ood", "solver_fail", "frequency_slack", "timeout")


def test_equation_71_withdraws_positive_and_negative_commands_without_overshoot() -> None:
    assert withdraw_toward_zero(0.05, 0.04, 0.5) == pytest.approx(0.03)
    assert withdraw_toward_zero(-0.05, 0.04, 0.5) == pytest.approx(-0.03)
    assert withdraw_toward_zero(0.01, 0.04, 0.5) == 0.0
    assert withdraw_toward_zero(-0.01, 0.04, 0.5) == 0.0
    assert withdraw_toward_zero(0.0, 0.04, 0.5) == 0.0


def test_joint_amplitude_and_rate_clipping() -> None:
    assert clip_with_rate_limit(1.0, 0.0, -0.12, 0.12, 0.02, 0.5) == pytest.approx(0.01)
    assert clip_with_rate_limit(-1.0, 0.0, -0.12, 0.12, 0.02, 0.5) == pytest.approx(-0.01)
    assert clip_with_rate_limit(1.0, 0.119, -0.12, 0.12, 0.02, 0.5) == pytest.approx(0.12)
    with pytest.raises(ValueError, match="previous_value"):
        clip_with_rate_limit(0.0, 0.2, -0.12, 0.12, 0.02, 0.5)


def test_controller_implements_uniform_runtime_api_without_truth_argument() -> None:
    controller = LQIFallbackController(_grid())
    assert isinstance(controller, FrequencyController)
    for method_name in ("reset", "act", "action_from_estimate"):
        signature = str(inspect.signature(getattr(LQIFallbackController, method_name))).lower()
        assert "true" not in signature
        assert "mode" not in signature


def test_controller_requires_reset_and_rejects_bad_estimator_state() -> None:
    measurement = Measurement(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    controller = LQIFallbackController(_grid())
    with pytest.raises(RuntimeError, match="reset"):
        controller.act(measurement)

    class BadEstimator:
        def reset_from_measurement(self, measurement: Measurement) -> np.ndarray:
            return np.zeros(4)

        def update_from_measurement(self, measurement: Measurement) -> np.ndarray:
            return np.zeros(4)

    bad_controller = LQIFallbackController(_grid(), estimator=BadEstimator())
    with pytest.raises(ValueError, match=r"shape \(5,\)"):
        bad_controller.reset(measurement)


def test_fallback_helpers_reject_nonfinite_or_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="finite"):
        FallbackTrigger(frequency_slack_hz=math.nan)
    with pytest.raises(TypeError, match="boolean"):
        FallbackTrigger(ood_active=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative"):
        withdraw_toward_zero(0.1, -0.1, 0.5)
