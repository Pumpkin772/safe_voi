from __future__ import annotations

import numpy as np

from direction5freq.voi_positive_region import (
    NestedValueInputs,
    StudySplit,
    VectorObservationTube,
    causal_posterior,
    evaluate_nested_value,
    generate_scenarios,
    registered_probe_library,
    registered_control_aligned_library,
    trajectory_metrics,
)
from direction5freq.voi_positive_region.sequential_evidence import (
    equal_prior_binary_error,
    windows_for_error,
)
from direction5freq.voi_positive_region.scenario_registry import SEED_RANGES


def test_seed_firewalls_are_disjoint_and_controller_view_hides_truth() -> None:
    ranges = [set(value) for value in SEED_RANGES.values()]
    for index, left in enumerate(ranges):
        assert all(left.isdisjoint(right) for right in ranges[index + 1:])
    scenario = generate_scenarios(StudySplit.DEVELOPMENT, count=1)[0]
    public = vars(scenario.controller_context())
    assert all("true" not in name for name in public)
    assert "load_event_time_s" not in public
    assert "capability_transition_time_s" not in public
    assert public["public_event_time_window_s"] == (210.0, 390.0)


def test_capability_and_load_times_use_independent_reproducible_streams() -> None:
    first = generate_scenarios(StudySplit.DEVELOPMENT, count=12)
    second = generate_scenarios(StudySplit.DEVELOPMENT, count=12)
    assert first == second
    capability_times = np.asarray([item.capability_transition_time_s for item in first])
    load_times = np.asarray([item.load_event_time_s for item in first])
    assert not np.allclose(capability_times - capability_times.mean(), load_times - load_times.mean())


def test_probe_library_is_physical_time_normalized() -> None:
    for period in (2.0, 4.0):
        probes = registered_probe_library(period)
        assert probes
        for probe in probes:
            sequence = np.asarray(probe.sequence_pu)
            assert np.isclose(period * sequence.sum(), 0.0, atol=1e-12)
            assert np.isclose(len(sequence) * period, probe.physical_duration_s)
    assert all(
        probe.physical_duration_s != 4.0
        for probe in registered_probe_library(4.0)
    )
    aligned = registered_control_aligned_library(4.0)
    assert aligned
    assert all(probe.mode == "control_aligned_surplus" for probe in aligned)
    assert all(np.all(np.asarray(probe.sequence_pu) >= 0.0) for probe in aligned)


def test_vector_observation_retains_every_consistent_candidate() -> None:
    tubes = {
        "slow": VectorObservationTube(
            "slow", np.zeros((3, 2)), np.full((3, 2), 0.02)
        ),
        "fast": VectorObservationTube(
            "fast", np.full((3, 2), 0.03), np.full((3, 2), 0.05)
        ),
    }
    observed = np.full((3, 2), 0.04)
    assert causal_posterior(tubes, observed) == frozenset({"fast"})


def test_nested_value_selects_only_robustly_safe_positive_probe() -> None:
    data = NestedValueInputs(
        contract_cost=np.asarray(((10.0, 8.0), (12.0, 10.0))),
        perfect_information_cost=np.asarray(((7.0, 6.0), (8.0, 7.0))),
        probe_total_cost=np.asarray((
            ((8.0, 7.0), (9.0, 8.0)),
            ((6.0, 5.0), (7.0, 6.0)),
        )),
        event_probability=np.asarray((0.6, 0.4)),
        probe_safe_for_hypothesis=np.asarray(((True, True), (True, False))),
        probe_ids=("safe_positive", "unsafe_better"),
    )
    result = evaluate_nested_value(data)
    assert result.perfect_information_value > 0.0
    assert result.selected_probe_id == "safe_positive"
    assert result.selected_net_value > 0.0
    assert result.region == "POSITIVE_VALUE"


def test_nested_value_abstains_when_safe_probe_has_no_net_value() -> None:
    data = NestedValueInputs(
        contract_cost=np.asarray(((2.0,), (3.0,))),
        perfect_information_cost=np.asarray(((1.0,), (2.0,))),
        probe_total_cost=np.asarray((((3.0,), (4.0,)),)),
        event_probability=np.asarray((1.0,)),
        probe_safe_for_hypothesis=np.asarray(((True, True),)),
        probe_ids=("costly",),
    )
    result = evaluate_nested_value(data)
    assert result.selected_probe_id is None
    assert result.selected_net_value == 0.0
    assert result.region == "ZERO_VALUE"


def test_physical_metric_excludes_optimizer_command_regularizer() -> None:
    states = np.zeros((7, 2))
    sg = np.asarray(((0.01, -0.01), (0.0, 0.0)))
    bess = -sg
    metrics = trajectory_metrics(states, sg, bess, period_s=2.0)
    assert metrics.grid_service_cost == 0.0
    assert metrics.sg_command_mileage_pu > 0.0
    assert metrics.bess_command_mileage_pu > 0.0


def test_independent_observation_windows_accumulate_information() -> None:
    one_window_error = equal_prior_binary_error(1.472183339877956, 1)
    required = windows_for_error(1.472183339877956, target_error=0.01)
    assert one_window_error > 0.20
    assert required == 10
    assert equal_prior_binary_error(1.472183339877956, required) <= 0.01
