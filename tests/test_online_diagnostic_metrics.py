from __future__ import annotations

import json

import numpy as np
import pytest

from d5freq.evaluation.online_diagnostic_metrics import (
    evaluate_classification,
    evaluate_false_alarms,
    evaluate_mode_probabilities,
    evaluate_ood_detection,
    evaluate_switch_detection,
)


def test_multiclass_probability_metrics_match_direct_definitions() -> None:
    truth = np.array([0, 1, 2, 1])
    probabilities = np.array(
        [
            [0.8, 0.1, 0.1],
            [0.2, 0.7, 0.1],
            [0.1, 0.2, 0.7],
            [0.1, 0.6, 0.3],
        ]
    )

    metrics = evaluate_mode_probabilities(
        truth,
        probabilities,
        reliability_bin_count=5,
    )

    one_hot = np.eye(3)[truth]
    assert metrics.accuracy == 1.0
    assert metrics.macro_f1 == 1.0
    assert metrics.brier_score == pytest.approx(
        np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))
    )
    assert metrics.negative_log_likelihood == pytest.approx(
        -np.mean(np.log(probabilities[np.arange(4), truth]))
    )
    assert metrics.expected_calibration_error == pytest.approx(
        np.mean(1.0 - np.max(probabilities, axis=1))
    )
    assert len(metrics.reliability_bins) == 5
    assert sum(item.count for item in metrics.reliability_bins) == 4


def test_probability_metrics_support_named_nonconsecutive_classes() -> None:
    metrics = evaluate_mode_probabilities(
        ["nominal", "slow", "nominal"],
        [[0.7, 0.3], [0.4, 0.6], [0.2, 0.8]],
        class_labels=["nominal", "slow"],
        reliability_bin_count=2,
    )

    assert metrics.accuracy == pytest.approx(2.0 / 3.0)
    assert metrics.class_labels == ("nominal", "slow")
    assert json.loads(json.dumps(metrics.to_dict()))["evaluation_only"] is True


def test_nll_probability_floor_keeps_zero_truth_probability_finite() -> None:
    metrics = evaluate_mode_probabilities(
        [0, 1],
        [[0.0, 1.0], [0.5, 0.5]],
        minimum_probability=1e-9,
    )

    assert metrics.negative_log_likelihood == pytest.approx(
        -(np.log(1e-9) + np.log(0.5)) / 2.0
    )
    assert np.isfinite(metrics.negative_log_likelihood)


def test_hard_classification_reports_accuracy_and_macro_f1() -> None:
    metrics = evaluate_classification(
        [10, 10, 20, 20],
        [10, 20, 20, 20],
        class_labels=[10, 20],
    )

    assert metrics.accuracy == 0.75
    assert metrics.macro_f1 == pytest.approx((2.0 / 3.0 + 0.8) / 2.0)
    assert metrics.sample_count == 4


@pytest.mark.parametrize(
    ("probabilities", "match"),
    [
        ([[0.5, 0.6]], "sum to one"),
        ([[-0.1, 1.1]], "lie in"),
        ([[np.nan, np.nan]], "finite"),
        ([0.5, 0.5], "shape"),
    ],
)
def test_probability_metrics_reject_invalid_probability_arrays(
    probabilities: object,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        evaluate_mode_probabilities([0], probabilities)


def test_probability_metrics_reject_unknown_truth_and_bad_options() -> None:
    with pytest.raises(ValueError, match="absent"):
        evaluate_mode_probabilities([4], [[0.5, 0.5]], class_labels=[0, 1])
    with pytest.raises(ValueError, match="unique"):
        evaluate_mode_probabilities([0], [[0.5, 0.5]], class_labels=[0, 0])
    with pytest.raises(ValueError, match="strictly positive"):
        evaluate_mode_probabilities([0], [[0.5, 0.5]], reliability_bin_count=0)
    with pytest.raises(ValueError, match=r"\(0, 1\]"):
        evaluate_mode_probabilities([0], [[0.5, 0.5]], minimum_probability=0.0)


def test_switch_detection_retains_detected_and_censored_events() -> None:
    truth = [0, 0, 1, 1, 1, 0, 0]
    probabilities = np.array(
        [
            [0.9, 0.1],
            [0.9, 0.1],
            [0.2, 0.8],
            [0.1, 0.9],
            [0.1, 0.9],
            [0.4, 0.6],
            [0.5, 0.5],
        ]
    )

    metrics = evaluate_switch_detection(
        truth,
        probabilities,
        sample_time_s=0.1,
        belief_threshold=0.8,
        consecutive_steps=2,
    )

    assert metrics.event_count == 2
    assert metrics.detected_count == 1
    assert metrics.censored_count == 1
    assert metrics.detection_rate == 0.5
    first, second = metrics.events
    assert first.switch_index == 2
    assert first.detection_index == 3
    assert first.delay_s == pytest.approx(0.1)
    assert not first.censored
    assert second.switch_index == 5
    assert second.detection_index is None
    assert second.delay_s is None
    assert second.censored
    assert second.censoring_time_s == pytest.approx(0.1)


def test_switch_detection_run_must_be_consecutive_and_end_before_next_switch() -> None:
    metrics = evaluate_switch_detection(
        [0, 1, 1, 1, 0],
        [
            [0.9, 0.1],
            [0.1, 0.9],
            [0.8, 0.2],
            [0.1, 0.9],
            [0.9, 0.1],
        ],
        sample_time_s=1.0,
        belief_threshold=0.8,
        consecutive_steps=2,
    )

    assert metrics.event_count == 2
    assert all(event.censored for event in metrics.events)


def test_episode_boundaries_are_not_mode_switches() -> None:
    metrics = evaluate_switch_detection(
        [0, 0, 1, 1],
        [[0.9, 0.1], [0.9, 0.1], [0.1, 0.9], [0.1, 0.9]],
        sample_time_s=0.1,
        belief_threshold=0.8,
        consecutive_steps=1,
        episode_ids=["a", "a", "b", "b"],
    )

    assert metrics.event_count == 0
    assert metrics.detection_rate is None
    assert metrics.mean_detected_delay_s is None


def test_switch_event_times_use_actual_episode_local_timestamps() -> None:
    metrics = evaluate_switch_detection(
        [0, 0, 1, 1, 0, 0, 1, 1],
        [
            [0.9, 0.1],
            [0.9, 0.1],
            [0.2, 0.8],
            [0.1, 0.9],
            [0.9, 0.1],
            [0.9, 0.1],
            [0.2, 0.8],
            [0.1, 0.9],
        ],
        sample_time_s=0.5,
        belief_threshold=0.8,
        consecutive_steps=2,
        episode_ids=["a"] * 4 + ["b"] * 4,
        time_s=[1.0, 1.5, 2.0, 2.5, 1.0, 1.5, 2.0, 2.5],
    )

    assert [event.switch_time_s for event in metrics.events] == [2.0, 2.0]
    assert [event.detection_time_s for event in metrics.events] == [2.5, 2.5]
    assert [event.delay_s for event in metrics.events] == [0.5, 0.5]


def test_switch_detection_rejects_invalid_or_discontiguous_inputs() -> None:
    probabilities = [[0.9, 0.1], [0.1, 0.9], [0.9, 0.1]]
    with pytest.raises(ValueError, match="contiguous"):
        evaluate_switch_detection(
            [0, 1, 0],
            probabilities,
            sample_time_s=0.1,
            belief_threshold=0.8,
            consecutive_steps=1,
            episode_ids=["a", "b", "a"],
        )
    with pytest.raises(ValueError, match=r"\(0, 1\]"):
        evaluate_switch_detection(
            [0, 1, 0],
            probabilities,
            sample_time_s=0.1,
            belief_threshold=0.0,
            consecutive_steps=1,
        )
    with pytest.raises(TypeError, match="integer"):
        evaluate_switch_detection(
            [0, 1, 0],
            probabilities,
            sample_time_s=0.1,
            belief_threshold=0.8,
            consecutive_steps=True,
        )


def test_false_alarm_metrics_count_maximal_wrong_runs_and_rates() -> None:
    truth = [0] * 8 + [1] * 8
    prediction = [0, 1, 1, 1, 0, 0, 0, 0] + [1] * 8

    metrics = evaluate_false_alarms(
        truth,
        prediction,
        sample_time_s=0.5,
        persistence_limit_steps=2,
        episode_ids=["a"] * 8 + ["b"] * 8,
        load_step_windows=[(2, 4), (9, 11)],
    )

    assert metrics.event_count == 1
    assert metrics.false_alarms_per_hour == pytest.approx(450.0)
    assert metrics.evaluated_episode_count == 2
    assert metrics.episode_false_alarm_rate == 0.5
    assert metrics.load_step_window_count == 2
    assert metrics.load_step_windows_with_false_alarm == 1
    assert metrics.load_step_window_false_alarm_rate == 0.5
    event = metrics.events[0]
    assert event.run_start_index == 1
    assert event.trigger_index == 3
    assert event.run_end_index == 3
    assert event.wrong_run_length_steps == 3


def test_wrong_run_equal_to_lfa_is_not_a_false_alarm() -> None:
    metrics = evaluate_false_alarms(
        [0, 0, 0, 0],
        [1, 1, 0, 0],
        sample_time_s=0.1,
        persistence_limit_steps=2,
    )

    assert metrics.event_count == 0
    assert metrics.false_alarms_per_hour == 0.0
    assert metrics.episode_false_alarm_rate == 0.0


def test_false_alarm_evaluation_excludes_switched_episodes() -> None:
    metrics = evaluate_false_alarms(
        [0, 0, 1, 1, 2, 2, 2],
        [1, 1, 0, 0, 1, 1, 1],
        sample_time_s=1.0,
        persistence_limit_steps=1,
        episode_ids=["switch"] * 4 + ["steady"] * 3,
    )

    assert metrics.excluded_switched_episode_count == 1
    assert metrics.evaluated_episode_count == 1
    assert metrics.exposure_time_s == 3.0
    assert metrics.event_count == 1


def test_load_step_window_must_be_inside_one_eligible_episode() -> None:
    with pytest.raises(ValueError, match="episode boundary"):
        evaluate_false_alarms(
            [0, 0, 1, 1],
            [0, 0, 1, 1],
            sample_time_s=1.0,
            persistence_limit_steps=1,
            episode_ids=["a", "a", "b", "b"],
            load_step_windows=[(1, 2)],
        )
    with pytest.raises(ValueError, match="sample range"):
        evaluate_false_alarms(
            [0, 0],
            [0, 0],
            sample_time_s=1.0,
            persistence_limit_steps=1,
            load_step_windows=[(0, 2)],
        )


def test_false_alarm_inputs_are_validated() -> None:
    with pytest.raises(ValueError, match="equal lengths"):
        evaluate_false_alarms(
            [0, 0],
            [0],
            sample_time_s=1.0,
            persistence_limit_steps=1,
        )
    with pytest.raises(ValueError, match="non-negative"):
        evaluate_false_alarms(
            [0],
            [0],
            sample_time_s=1.0,
            persistence_limit_steps=-1,
        )


def test_ood_metrics_report_ranking_and_censored_detection_delays() -> None:
    truth = np.array([0, 0, 1, 1, 1, 0, 1, 1, 0], dtype=np.int64)
    scores = np.array([0.1, 0.2, 0.9, 0.8, 0.7, 0.3, 0.95, 0.85, 0.0])
    active = np.array([0, 0, 0, 1, 1, 0, 0, 0, 0], dtype=np.int64)

    metrics = evaluate_ood_detection(
        truth,
        scores,
        active,
        sample_time_s=0.2,
    )

    assert metrics.auroc == 1.0
    assert metrics.auprc == 1.0
    assert metrics.event_count == 2
    assert metrics.detected_count == 1
    assert metrics.censored_count == 1
    assert metrics.detection_rate == 0.5
    assert metrics.events[0].onset_index == 2
    assert metrics.events[0].detection_index == 3
    assert metrics.events[0].delay_s == pytest.approx(0.2)
    assert metrics.events[1].censored
    assert metrics.events[1].delay_s is None
    assert json.loads(json.dumps(metrics.to_dict()))["evaluation_only"] is True


def test_ood_metrics_accept_pvalues_with_lower_is_more_ood() -> None:
    metrics = evaluate_ood_detection(
        [0, 0, 1, 1],
        [0.9, 0.8, 0.01, 0.02],
        [0, 0, 1, 1],
        sample_time_s=1.0,
        higher_score_more_ood=False,
    )

    assert metrics.auroc == 1.0
    assert metrics.auprc == 1.0
    assert metrics.events[0].delay_s == 0.0


def test_ood_episode_boundary_starts_a_new_interval() -> None:
    metrics = evaluate_ood_detection(
        [1, 1, 0, 1],
        [0.9, 0.8, 0.1, 0.7],
        [1, 1, 0, 1],
        sample_time_s=0.5,
        episode_ids=["a", "a", "b", "b"],
    )

    assert metrics.event_count == 2
    assert [event.onset_index for event in metrics.events] == [0, 3]


def test_ood_preexisting_alarm_requires_a_new_activation_after_onset() -> None:
    metrics = evaluate_ood_detection(
        [0, 0, 1, 1, 1, 1],
        [0.1, 0.2, 0.9, 0.8, 0.7, 0.95],
        [0, 1, 1, 1, 0, 1],
        sample_time_s=1.0,
        time_s=[10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
    )

    event = metrics.events[0]
    assert event.preexisting_active
    assert event.onset_time_s == 12.0
    assert event.detection_time_s == 15.0
    assert event.delay_s == 3.0


def test_ood_preexisting_alarm_without_new_edge_is_censored() -> None:
    metrics = evaluate_ood_detection(
        [0, 1, 1, 1],
        [0.1, 0.9, 0.8, 0.7],
        [1, 1, 1, 1],
        sample_time_s=0.5,
    )

    assert metrics.events[0].preexisting_active
    assert metrics.events[0].censored
    assert metrics.detected_count == 0


def test_ood_metrics_reject_undefined_auc_and_invalid_vectors() -> None:
    with pytest.raises(ValueError, match="both known and OOD"):
        evaluate_ood_detection(
            [0, 0],
            [0.1, 0.2],
            [0, 0],
            sample_time_s=1.0,
        )
    with pytest.raises(TypeError, match="booleans"):
        evaluate_ood_detection(
            [0.0, 1.0],
            [0.1, 0.9],
            [0, 1],
            sample_time_s=1.0,
        )
    with pytest.raises(ValueError, match="equal lengths"):
        evaluate_ood_detection(
            [0, 1],
            [0.1],
            [0, 1],
            sample_time_s=1.0,
        )
    with pytest.raises(TypeError, match="boolean"):
        evaluate_ood_detection(
            [0, 1],
            [0.1, 0.9],
            [0, 1],
            sample_time_s=1.0,
            higher_score_more_ood=1,
        )
