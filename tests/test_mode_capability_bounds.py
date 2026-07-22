from __future__ import annotations

import numpy as np
import pytest

from d5freq.identification.mode_discovery import estimate_mode_capability_bounds


def test_power_and_directional_rate_quantiles_match_equation_84() -> None:
    trajectories = [
        np.array([0.0, 1.0, 4.0, 2.0]),
        np.array([10.0, 6.0, 7.0, 2.0]),
    ]
    bounds = estimate_mode_capability_bounds(
        trajectories,
        sample_time_s=0.5,
        lower_power_quantile=0.0,
        upper_power_quantile=1.0,
        directional_rate_quantile=1.0,
    )

    assert bounds.p_output_min_pu == 0.0
    assert bounds.p_output_max_pu == 10.0
    assert bounds.ramp_up_pu_per_s == 6.0
    assert bounds.ramp_down_pu_per_s == 10.0


def test_rate_estimation_never_differences_across_trajectory_boundaries() -> None:
    bounds = estimate_mode_capability_bounds(
        [np.array([0.0, 1.0]), np.array([100.0, 99.0])],
        sample_time_s=1.0,
        lower_power_quantile=0.0,
        upper_power_quantile=1.0,
        directional_rate_quantile=1.0,
    )
    assert bounds.ramp_up_pu_per_s == 1.0
    assert bounds.ramp_down_pu_per_s == 1.0


def test_missing_direction_has_zero_observed_capability() -> None:
    bounds = estimate_mode_capability_bounds(
        [np.array([0.0, 0.1, 0.3, 0.6])],
        sample_time_s=0.1,
        directional_rate_quantile=0.99,
    )
    assert bounds.ramp_up_pu_per_s > 0.0
    assert bounds.ramp_down_pu_per_s == 0.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample_time_s": 0.0},
        {"sample_time_s": 0.1, "lower_power_quantile": 0.9, "upper_power_quantile": 0.1},
        {"sample_time_s": 0.1, "directional_rate_quantile": 1.1},
    ],
)
def test_capability_bound_configuration_is_validated(kwargs: dict[str, float]) -> None:
    with pytest.raises((TypeError, ValueError)):
        estimate_mode_capability_bounds([np.array([0.0, 1.0])], **kwargs)
