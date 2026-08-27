from __future__ import annotations

import numpy as np

from direction5freq.voi_positive_region import (
    NestedValueInputs,
    ControlAlignedSequentialProbe,
    DynamicCapabilityCandidate,
    DynamicCapabilityEstimator,
    DynamicEvidenceConfig,
    BinaryPriorValueBoundary,
    OpportunityValuePoint,
    OutcomeValueComponents,
    StudySplit,
    VectorObservationTube,
    causal_posterior,
    evaluate_nested_value,
    generate_scenarios,
    registered_probe_library,
    registered_control_aligned_library,
    trajectory_metrics,
    select_opportunity,
    development_factorial,
)
from direction5freq.voi_positive_region.sequential_evidence import (
    effective_windows_ar1,
    equal_prior_binary_error,
    stacked_equal_prior_error,
    stacked_mahalanobis_separation,
    windows_for_error,
    windows_for_error_ar1,
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
    assert all(item.true_power_pu >= 0.045 for item in first)
    assert all(item.true_ramp_pu_per_s >= 0.025 for item in first)
    assert all(item.true_delay_s <= 1.5 for item in first)
    assert all(item.episode_duration_s == 720.0 for item in first)


def test_resource_price_boundary_keeps_physical_tradeoff_explicit() -> None:
    low = OutcomeValueComponents(-0.1, 0.02, -0.2)
    high = OutcomeValueComponents(0.5, 0.04, -0.4)
    mixed = low.mix(high, 0.5)
    assert np.isclose(mixed.grid_service_s, 0.2)
    assert np.isclose(mixed.priced_value(
        sg_mileage_price_s_per_pu=1.0,
        bess_throughput_price=0.1,
    ), 0.2)
    assert np.isclose(mixed.break_even_bess_throughput_price(
        sg_mileage_price_s_per_pu=1.0,
    ), 0.23 / 0.3)


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
    assert len(result.probe_net_value_by_hypothesis["safe_positive"]) == 2


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


def test_control_aligned_probe_keeps_sg_action_and_uses_current_state_only() -> None:
    policy = ControlAlignedSequentialProbe()
    contract = np.asarray((0.04, 0.041, 0.02, 0.01))
    result = policy.overlay(
        contract,
        time_s=100.0,
        frequency_deviation_hz=np.asarray((0.03, -0.01)),
        ace_pu=np.asarray((0.04, -0.01)),
        measured_soc=np.asarray((0.5, 0.5)),
    )
    assert np.array_equal(result[[0, 2]], contract[[0, 2]])
    assert np.isclose(result[1] - contract[1], 0.003)
    assert policy.windows_started == 1


def test_delivery_certificate_is_causal_and_expires() -> None:
    policy = ControlAlignedSequentialProbe()
    policy.overlay(
        np.asarray((0.04, 0.041, 0.02, 0.01)),
        time_s=90.0,
        frequency_deviation_hz=np.zeros(2),
        ace_pu=np.zeros(2),
        measured_soc=np.full(2, 0.5),
    )
    assert not policy.observe_delivery(
        100.0,
        issued_bess_command=np.asarray((0.049, 0.0)),
        actual_bess_poi_power=np.asarray((0.050, 0.0)),
    )
    assert policy.observe_delivery(
        104.0,
        issued_bess_command=np.asarray((0.049, 0.0)),
        actual_bess_poi_power=np.asarray((0.050, 0.0)),
    )
    assert policy.power_certified(210.0)
    assert not policy.power_certified(210.1)


def test_contract_floor_delivery_does_not_create_power_certificate() -> None:
    policy = ControlAlignedSequentialProbe()
    contract = np.asarray((0.03, 0.049, 0.02, 0.01))
    for index in range(20):
        assert not policy.observe_delivery(
            float(index * 4),
            issued_bess_command=contract[[1, 3]],
            actual_bess_poi_power=np.asarray((0.045, 0.0)),
        )


def test_low_delivery_stops_second_information_window_causally() -> None:
    policy = ControlAlignedSequentialProbe()
    contract = np.asarray((0.03, 0.045, 0.02, 0.01))
    first = policy.overlay(
        contract, 100.0, np.zeros(2), np.zeros(2), np.full(2, 0.5)
    )
    policy.observe_delivery(104.0, first[[1, 3]], np.asarray((0.045, 0.0)))
    second = policy.overlay(
        contract, 104.0, np.zeros(2), np.zeros(2), np.full(2, 0.5)
    )
    policy.observe_delivery(108.0, second[[1, 3]], np.asarray((0.045, 0.0)))
    for index in range(6):
        policy.overlay(
            contract,
            108.0 + 4.0 * index,
            np.zeros(2),
            np.zeros(2),
            np.full(2, 0.5),
        )
    assert policy.futility_stopped
    assert policy.windows_started == 1


def _feed_dynamic_window(
    estimator: DynamicCapabilityEstimator,
    truth: DynamicCapabilityCandidate,
) -> None:
    from direction5freq.voi_positive_region import simulate_candidate_response

    config = estimator.config
    times = np.arange(0.0, 15.0 + 1e-9, config.sample_period_s)
    issued = np.full_like(times, 0.045)
    issued[(times >= 3.0) & (times < 11.0)] = 0.050
    frequency = np.zeros_like(times)
    actual = simulate_candidate_response(
        times, issued, frequency, 0.0, truth, config
    )
    for time_s, command, power in zip(times, issued, actual, strict=True):
        estimator.observe(
            float(time_s),
            np.asarray((command, 0.0)),
            np.asarray((power, 0.0)),
            np.zeros(2),
        )


def test_dynamic_vector_evidence_certifies_high_power_without_truth_input() -> None:
    low = DynamicCapabilityCandidate("low", 0.045, 0.039, 1.5)
    high = DynamicCapabilityCandidate("high", 0.068, 0.039, 1.5)
    estimator = DynamicCapabilityEstimator(
        (low, high),
        DynamicEvidenceConfig(maximum_windows=2, information_validity_s=240.0),
    )
    _feed_dynamic_window(estimator, high)
    assert estimator.power_certificate_time_s is not None
    assert estimator.retained_candidate_ids == ("high",)
    assert estimator.window_results[0].raw_samples > 40
    assert estimator.window_results[0].scored_samples > 30


def test_dynamic_vector_evidence_retains_contract_power_for_low_truth() -> None:
    low = DynamicCapabilityCandidate("low", 0.045, 0.039, 1.5)
    high = DynamicCapabilityCandidate("high", 0.068, 0.039, 1.5)
    estimator = DynamicCapabilityEstimator((low, high))
    _feed_dynamic_window(estimator, low)
    assert estimator.power_certificate_time_s is None
    assert estimator.retained_candidate_ids == ("low",)
    assert not estimator.high_capability_still_possible


def test_second_window_can_increase_amplitude_after_causal_evidence() -> None:
    from direction5freq.voi_positive_region import ControlAlignedConfig

    policy = ControlAlignedSequentialProbe(ControlAlignedConfig(
        second_window_amplitude_pu=0.004,
    ))
    contract = np.asarray((0.03, 0.045, 0.02, 0.01))
    first = policy.overlay(contract, 100.0, np.zeros(2), np.zeros(2), np.full(2, 0.5))
    policy.observe_delivery(104.0, first[[1, 3]], np.asarray((0.046, 0.0)))
    second = policy.overlay(contract, 104.0, np.zeros(2), np.zeros(2), np.full(2, 0.5))
    policy.observe_delivery(108.0, second[[1, 3]], np.asarray((0.046, 0.0)))
    candidate = contract
    for index in range(5):
        candidate = policy.overlay(
            contract, 108.0 + 4.0 * index,
            np.zeros(2), np.zeros(2), np.full(2, 0.5),
        )
    assert policy.windows_started == 2
    assert np.isclose(candidate[1] - contract[1], 0.004)


def test_binary_prior_boundary_reports_break_even_probability() -> None:
    boundary = BinaryPriorValueBoundary(
        low_capability_net_value=-0.01,
        high_capability_net_value=0.04,
    )
    assert np.isclose(boundary.break_even_probability(), 0.2)
    assert boundary.net_value(0.8) > 0.0
    assert boundary.worst_value_over_prior_interval(0.3, 0.8) > 0.0


def test_ar1_correlation_reduces_effective_evidence() -> None:
    assert np.isclose(effective_windows_ar1(10, 0.2), 10 * 0.8 / 1.2)
    assert windows_for_error_ar1(1.472183339877956, 0.2) == 15
    assert windows_for_error_ar1(1.472183339877956, 0.4) == 24


def test_stacked_covariance_reproduces_independent_information_gain() -> None:
    low = np.zeros(4)
    high = np.ones(4)
    covariance = np.eye(4)
    assert np.isclose(stacked_mahalanobis_separation(low, high, covariance), 2.0)
    assert np.isclose(stacked_equal_prior_error(low, high, covariance), 0.1586552539)


def test_information_value_expires_from_first_evidence_window() -> None:
    point = OpportunityValuePoint(
        amplitude_pu=0.003,
        evidence_window_s=24.0,
        windows_to_certify=10,
        information_validity_s=300.0,
        low_acquisition_control_value=-0.002,
        high_acquisition_control_value=0.05,
        low_information_value_per_s=0.0,
        high_information_value_per_s=0.001,
        physical_safe=True,
    )
    assert point.certification_time_s == 240.0
    assert point.useful_information_time_s == 60.0
    assert point.high_total_value == 0.11
    assert point.prior_boundary.break_even_probability() is not None


def test_opportunity_selection_uses_worst_prior_in_interval() -> None:
    candidate = OpportunityValuePoint(
        amplitude_pu=0.003,
        evidence_window_s=12.0,
        windows_to_certify=8,
        information_validity_s=240.0,
        low_acquisition_control_value=-0.001,
        high_acquisition_control_value=0.03,
        low_information_value_per_s=0.0,
        high_information_value_per_s=0.001,
        physical_safe=True,
    )
    selected = select_opportunity(
        [candidate],
        prior_lower=0.3,
        prior_upper=0.8,
        low_capability_downside_limit=0.01,
    )
    assert selected is candidate


def test_development_factorial_has_eight_unique_cells() -> None:
    cells = development_factorial()
    assert len(cells) == 8
    assert len({cell.cell_id for cell in cells}) == 8
