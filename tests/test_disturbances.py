from __future__ import annotations

import numpy as np
import pytest

from d5freq.simulation.disturbances import (
    LoadDisturbance,
    LoadDisturbanceSpec,
    LoadEvent,
    SampledLoadNoise,
)


def test_step_and_pulse_load_events_have_unambiguous_boundaries() -> None:
    disturbance = LoadDisturbance(
        base_pu=0.01,
        events=(
            LoadEvent(1.0, 0.05),
            LoadEvent(2.0, -0.02, end_time_s=3.0),
        ),
    )

    assert disturbance.value_at(0.999) == pytest.approx(0.01)
    assert disturbance.value_at(1.0) == pytest.approx(0.06)
    assert disturbance.value_at(2.0) == pytest.approx(0.04)
    assert disturbance.value_at(3.0) == pytest.approx(0.06)
    assert disturbance.transition_times_between(0.0, 3.0) == (1.0, 2.0, 3.0)


def test_sampled_noise_is_seeded_zoh_and_query_order_independent() -> None:
    first = SampledLoadNoise.from_seed(
        seed=23,
        duration_s=2.0,
        sample_period_s=0.5,
        white_std_pu=0.01,
        random_walk_step_std_pu=0.002,
    )
    second = SampledLoadNoise.from_seed(
        seed=23,
        duration_s=2.0,
        sample_period_s=0.5,
        white_std_pu=0.01,
        random_walk_step_std_pu=0.002,
    )
    different = SampledLoadNoise.from_seed(
        seed=24,
        duration_s=2.0,
        sample_period_s=0.5,
        white_std_pu=0.01,
        random_walk_step_std_pu=0.002,
    )

    np.testing.assert_array_equal(first.samples_pu, second.samples_pu)
    assert not np.array_equal(first.samples_pu, different.samples_pu)
    assert first.value_at(0.1) == first.value_at(0.49)
    expected = [first.value_at(time) for time in (0.1, 0.6, 1.1)]
    queried_out_of_order = [first.value_at(time) for time in (1.1, 0.1, 0.6)]
    assert queried_out_of_order == [expected[2], expected[0], expected[1]]


def test_disturbance_spec_realization_is_reproducible() -> None:
    spec = LoadDisturbanceSpec(
        events=(LoadEvent(1.0, 0.04),),
        sample_period_s=0.2,
        white_noise_std_pu=0.001,
    )
    first = spec.realize(seed=9, duration_s=2.0)
    second = spec.realize(seed=9, duration_s=2.0)
    np.testing.assert_array_equal(first.noise.samples_pu, second.noise.samples_pu)
