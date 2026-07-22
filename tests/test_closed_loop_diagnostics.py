from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from d5freq.evaluation.closed_loop_diagnostics import (
    DIAGNOSTIC_EPISODE_FIELDS,
    ClosedLoopDiagnosticConfig,
    evaluate_diagnostic_trace,
    evaluate_episode_diagnostics,
    make_closed_loop_diagnostic_evaluator,
)
from d5freq.evaluation.closed_loop_runner import EpisodeEvaluationData
from d5freq.evaluation.closed_loop_metrics import HighFrequencyTruthTrace
from d5freq.evaluation.experiment_store import RunIdentity


K6_TO_SEMANTIC = {
    0: "nominal",
    1: "nominal",
    2: "sluggish",
    3: "derated",
    4: "derated",
    5: "unavailable",
}
K4_TO_SEMANTIC = {
    0: "derated",
    1: "nominal",
    2: "unavailable",
    3: "sluggish",
}


def _truth(times: list[float], modes: list[str]) -> list[dict[str, object]]:
    return [
        {"time_s": time_s, "true_mode_eval_only": mode}
        for time_s, mode in zip(times, modes, strict=True)
    ]


def _record(
    time_s: float,
    belief: list[float],
    *,
    sample_index: int,
    pvalue: float = 0.9,
    active: bool = False,
    valid_update: bool | None = True,
) -> dict[str, object]:
    row: dict[str, object] = {
        "time_s": time_s,
        "sample_index": sample_index,
        "map_mode": int(np.argmax(belief)),
        "ood_pvalue": pvalue,
        "ood_active": active,
        "diagnostic_state": "OOD_ACTIVE" if active else "KNOWN",
    }
    if valid_update is not None:
        row["valid_update"] = valid_update
    for index, probability in enumerate(belief):
        row[f"belief_{index}"] = probability
    return row


def _one_hot(component: int, count: int = 6, confidence: float = 0.9) -> list[float]:
    remaining = (1.0 - confidence) / (count - 1)
    values = [remaining] * count
    values[component] = confidence
    return values


def test_k6_beliefs_are_aggregated_and_switch_requires_three_consecutive_steps() -> None:
    times = [0.0, 0.5, 1.0, 1.5, 2.0]
    modes = ["nominal", "nominal", "sluggish", "sluggish", "sluggish"]
    beliefs = [
        [0.45, 0.45, 0.05, 0.02, 0.02, 0.01],
        [0.40, 0.50, 0.04, 0.02, 0.02, 0.02],
        [0.03, 0.03, 0.82, 0.04, 0.04, 0.04],
        [0.02, 0.03, 0.85, 0.03, 0.03, 0.04],
        [0.01, 0.02, 0.90, 0.02, 0.02, 0.03],
    ]
    records = [
        _record(time_s, belief, sample_index=index)
        for index, (time_s, belief) in enumerate(zip(times, beliefs, strict=True))
    ]

    result = evaluate_diagnostic_trace(
        records,
        _truth(times, modes),
        component_to_semantic_eval_only=K6_TO_SEMANTIC,
        method_id="P",
    )

    assert result.metric_values["mode_accuracy"] == 1.0
    assert result.metric_values["detection_event_count"] == 1
    assert result.metric_values["detection_censored_count"] == 0
    assert result.metric_values["detection_delay_s"] == pytest.approx(1.0)
    assert result.metric_values["detection_censoring_time_s"] is None
    # Switched episodes are deliberately outside the no-switch false-alarm rate.
    assert result.metric_values["false_alarm_rate"] is None
    probability = result.audit["metrics"]["known_mode_probability"]
    assert probability["sample_count"] == 5
    assert probability["class_labels"] == [
        "nominal",
        "sluggish",
        "derated",
        "unavailable",
    ]


def test_k4_probability_rows_are_normalized_only_within_declared_tolerance() -> None:
    row = _record(
        0.0,
        [0.02, 0.96, 0.01, 0.010000000001],
        sample_index=0,
    )
    result = evaluate_diagnostic_trace(
        [row],
        _truth([0.0], ["nominal"]),
        component_to_semantic_eval_only=K4_TO_SEMANTIC,
    )

    assert result.metric_values["mode_accuracy"] == 1.0
    assert result.audit["aligned_valid_sample_count"] == 1

    bad = dict(row)
    bad["belief_1"] = 0.90
    bad["map_mode"] = 1
    with pytest.raises(ValueError, match="sum to one"):
        evaluate_diagnostic_trace(
            [bad],
            _truth([0.0], ["nominal"]),
            component_to_semantic_eval_only=K4_TO_SEMANTIC,
        )


def test_false_alarm_rate_is_exposure_normalized_on_constant_known_episode() -> None:
    times = [0.5 * index for index in range(8)]
    beliefs = [
        _one_hot(0),
        _one_hot(2),
        _one_hot(2),
        _one_hot(2),
        _one_hot(2),
        _one_hot(0),
        _one_hot(0),
        _one_hot(0),
    ]
    records = [
        _record(time_s, belief, sample_index=index)
        for index, (time_s, belief) in enumerate(zip(times, beliefs, strict=True))
    ]

    result = evaluate_diagnostic_trace(
        records,
        _truth(times, ["nominal"] * len(times)),
        component_to_semantic_eval_only=K6_TO_SEMANTIC,
    )

    # One wrong-MAP run is strictly longer than L_fa=3; exposure is 8*0.5 s.
    assert result.metric_values["false_alarm_rate"] == pytest.approx(900.0)
    false_alarm = result.audit["metrics"]["known_mode_false_alarms"]
    assert false_alarm["event_count"] == 1
    assert false_alarm["exposure_time_s"] == 4.0


def test_ood_metrics_exclude_unknown_truth_from_known_class_probabilities() -> None:
    times = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    modes = ["nominal"] * 3 + ["asymmetric_limit"] * 3
    pvalues = [0.9, 0.8, 0.7, 0.03, 0.02, 0.01]
    active = [False, False, False, False, True, True]
    records = [
        _record(
            time_s,
            _one_hot(0),
            sample_index=index,
            pvalue=pvalue,
            active=is_active,
        )
        for index, (time_s, pvalue, is_active) in enumerate(
            zip(times, pvalues, active, strict=True)
        )
    ]

    result = evaluate_diagnostic_trace(
        records,
        _truth(times, modes),
        component_to_semantic_eval_only=K6_TO_SEMANTIC,
    )

    probability = result.audit["metrics"]["known_mode_probability"]
    assert probability["sample_count"] == 3
    assert result.audit["known_sample_count"] == 3
    assert result.audit["ood_sample_count"] == 3
    assert result.metric_values["ood_auroc"] == 1.0
    assert result.metric_values["ood_auprc"] == 1.0
    assert result.metric_values["ood_detected"] is True
    assert result.metric_values["ood_detection_event_count"] == 1
    assert result.metric_values["ood_detection_censored_count"] == 0
    assert result.metric_values["ood_detection_delay_s"] == pytest.approx(0.5)
    assert result.metric_values["false_alarm_rate"] is None
    assert result.audit["ood_score_source"] == "ood_pvalue_lower_is_more_ood"


def test_ood_event_is_retained_as_right_censored() -> None:
    times = [0.0, 0.5, 1.0, 1.5]
    records = [
        _record(
            time_s,
            _one_hot(0),
            sample_index=index,
            pvalue=[0.9, 0.8, 0.02, 0.01][index],
            active=False,
        )
        for index, time_s in enumerate(times)
    ]
    result = evaluate_diagnostic_trace(
        records,
        _truth(times, ["nominal", "nominal", "time_varying_delay", "time_varying_delay"]),
        component_to_semantic_eval_only=K6_TO_SEMANTIC,
        run_completed=False,
    )

    assert result.metric_values["ood_detected"] is False
    assert result.metric_values["ood_detection_delay_s"] is None
    assert result.metric_values["ood_detection_censored_count"] == 1
    assert result.metric_values["ood_detection_censoring_time_s"] == pytest.approx(0.5)
    assert result.audit["trace_scope"] == "failure_prefix"


def test_methods_without_diagnosis_publish_only_null_fields() -> None:
    result = evaluate_diagnostic_trace(
        [{"malformed": object()}],
        [{"also": "malformed"}],
        diagnostic_qualification="none",
        method_id="B0",
    )

    assert set(result.metric_values) == set(DIAGNOSTIC_EPISODE_FIELDS)
    assert all(value is None for value in result.metric_values.values())
    assert result.audit["diagnostic_qualification"] == "none"
    assert result.audit["standard_diagnostic_fields_published"] is False
    assert result.audit["reason"] == "method_declares_no_runtime_diagnosis"

    # A singleton controller record must not turn B1/B2 into diagnostic methods
    # merely because those baselines share controller infrastructure.
    singleton = evaluate_diagnostic_trace(
        [_record(0.0, [1.0], sample_index=0)],
        _truth([0.0], ["nominal"]),
        component_to_semantic_eval_only={0: "nominal"},
        method_id="B1",
    )
    assert all(value is None for value in singleton.metric_values.values())
    assert singleton.audit["diagnostic_qualification"] == "none"


def test_oracle_requires_truth_informed_qualification_and_never_publishes_standard_fields() -> None:
    records = [_record(0.0, [1.0], sample_index=0)]
    truth = _truth([0.0], ["nominal"])
    with pytest.raises(ValueError, match="truth_informed"):
        evaluate_diagnostic_trace(
            records,
            truth,
            component_to_semantic_eval_only={0: "nominal"},
            diagnostic_qualification="runtime",
            method_id="B4",
        )

    result = evaluate_diagnostic_trace(
        records,
        truth,
        diagnostic_qualification="truth_informed",
        method_id="B4",
    )
    assert all(value is None for value in result.metric_values.values())
    assert result.audit["diagnostic_qualification"] == "truth_informed"
    assert result.audit["reason"] == "truth_informed_diagnostics_are_upper_bound_only"


def test_failed_episode_retains_aligned_prefix_and_drops_only_unobservable_suffix() -> None:
    records = [
        _record(time_s, _one_hot(0), sample_index=index)
        for index, time_s in enumerate([0.0, 0.5, 1.0, 1.5])
    ]
    result = evaluate_diagnostic_trace(
        records,
        _truth([0.0, 0.5, 1.0], ["nominal"] * 3),
        component_to_semantic_eval_only=K6_TO_SEMANTIC,
        run_completed=False,
    )

    assert result.metric_values["mode_accuracy"] == 1.0
    assert result.audit["status"] == "evaluated_prefix"
    assert result.audit["aligned_valid_sample_count"] == 3
    assert result.audit["dropped_unaligned_failure_suffix_count"] == 1

    unavailable = evaluate_diagnostic_trace(
        [records[0]],
        [],
        component_to_semantic_eval_only=K6_TO_SEMANTIC,
        run_completed=False,
    )
    assert all(value is None for value in unavailable.metric_values.values())
    assert unavailable.audit["reason"] == "no_evaluator_truth_prefix"


def test_internal_or_complete_time_misalignment_is_rejected() -> None:
    records = [
        _record(0.0, _one_hot(0), sample_index=0),
        _record(0.5, _one_hot(0), sample_index=1),
        _record(1.0, _one_hot(0), sample_index=2),
    ]
    truth = _truth([0.0, 0.4, 1.0], ["nominal"] * 3)
    with pytest.raises(ValueError, match="no exact evaluator-truth sample"):
        evaluate_diagnostic_trace(
            records,
            truth,
            component_to_semantic_eval_only=K6_TO_SEMANTIC,
            run_completed=False,
        )
    with pytest.raises(ValueError, match="no exact evaluator-truth sample"):
        evaluate_diagnostic_trace(
            records[:2],
            truth,
            component_to_semantic_eval_only=K6_TO_SEMANTIC,
            run_completed=True,
        )


def test_warmup_and_explicit_invalid_updates_are_excluded() -> None:
    records = [
        _record(0.0, _one_hot(2), sample_index=0, valid_update=None),
        _record(0.5, _one_hot(2), sample_index=1, valid_update=None),
        _record(1.0, _one_hot(0), sample_index=2, valid_update=None),
        _record(1.5, _one_hot(2), sample_index=3, valid_update=False),
    ]
    result = evaluate_diagnostic_trace(
        records,
        _truth([0.0, 0.5, 1.0, 1.5], ["nominal"] * 4),
        component_to_semantic_eval_only=K6_TO_SEMANTIC,
    )

    assert result.audit["aligned_valid_sample_count"] == 1
    assert result.metric_values["mode_accuracy"] == 1.0


def test_missing_ood_runtime_fields_do_not_fabricate_ood_metrics() -> None:
    times = [0.0, 0.5]
    records = [
        {
            "time_s": time_s,
            "sample_index": index,
            "valid_update": True,
            "mode_belief": _one_hot(0),
            "map_mode": 0,
        }
        for index, time_s in enumerate(times)
    ]
    result = evaluate_diagnostic_trace(
        records,
        _truth(times, ["nominal", "asymmetric_limit"]),
        component_to_semantic_eval_only=K6_TO_SEMANTIC,
    )

    assert result.metric_values["mode_accuracy"] == 1.0
    assert result.metric_values["ood_auroc"] is None
    assert result.metric_values["ood_detected"] is None
    assert result.audit["ood_runtime_fields_missing"] is True


def test_mapping_and_record_invariants_are_strict() -> None:
    records = [_record(0.0, _one_hot(0), sample_index=0)]
    truth = _truth([0.0], ["nominal"])
    with pytest.raises(ValueError, match="contiguous"):
        evaluate_diagnostic_trace(
            records,
            truth,
            component_to_semantic_eval_only={1: "nominal"},
        )
    with pytest.raises(ValueError, match="unknown semantic"):
        evaluate_diagnostic_trace(
            records,
            truth,
            component_to_semantic_eval_only={0: "secret-label"},
        )
    with pytest.raises(TypeError, match="non-negative integers"):
        evaluate_diagnostic_trace(
            records,
            truth,
            component_to_semantic_eval_only={0.5: "nominal"},
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        evaluate_diagnostic_trace(
            [records[0], dict(records[0])],
            truth,
            component_to_semantic_eval_only=K6_TO_SEMANTIC,
        )


def test_episode_data_adapter_returns_runner_contribution() -> None:
    record = _record(0.0, _one_hot(0), sample_index=0)
    data = EpisodeEvaluationData(
        identity=RunIdentity("run", "scenario", "P", 7),
        scenario=SimpleNamespace(),
        run_completed=True,
        measurements=(),
        actions=(),
        simulator_evaluations=(),
        truth_points_eval_only=tuple(_truth([0.0], ["nominal"])),
        truth_intervals_eval_only=(),
        controller_records=(record,),
        high_frequency_truth=None,
        control_trace=None,
        control_trajectory=(),
        base_metrics=None,
        failure_stage=None,
        failure_type=None,
        failure_message=None,
    )

    contribution = evaluate_episode_diagnostics(
        data,
        component_to_semantic_eval_only=K6_TO_SEMANTIC,
    )
    assert contribution.metric_overrides["mode_accuracy"] == 1.0
    artifact = contribution.artifacts["closed_loop_diagnostics_eval_only"]
    assert artifact["method_id"] == "P"
    assert artifact["evaluation_only"] is True

    evaluator = make_closed_loop_diagnostic_evaluator(
        component_to_semantic_eval_only=K6_TO_SEMANTIC,
        config=ClosedLoopDiagnosticConfig(sample_time_s=0.5),
    )
    assert evaluator(data).metric_overrides["mode_accuracy"] == 1.0


def test_episode_adapter_computes_diagnostic_risk_to_detection() -> None:
    times = [0.0, 0.5, 1.0, 1.5, 2.0]
    records = tuple(
        _record(
            time_s,
            _one_hot(0 if time_s < 1.0 else 2),
            sample_index=index,
        )
        for index, time_s in enumerate(times)
    )
    data = EpisodeEvaluationData(
        identity=RunIdentity("risk", "switch", "P", 8),
        scenario=SimpleNamespace(),
        run_completed=True,
        measurements=(),
        actions=(),
        simulator_evaluations=(),
        truth_points_eval_only=tuple(
            _truth(times, ["nominal", "nominal", "sluggish", "sluggish", "sluggish"])
        ),
        truth_intervals_eval_only=(),
        controller_records=records,
        high_frequency_truth=HighFrequencyTruthTrace(
            time_s=times,
            delta_frequency_hz=[0.1] * len(times),
        ),
        control_trace=None,
        control_trajectory=(),
        base_metrics=None,
        failure_stage=None,
        failure_type=None,
        failure_message=None,
    )
    contribution = evaluate_episode_diagnostics(
        data,
        component_to_semantic_eval_only=K6_TO_SEMANTIC,
    )
    assert contribution.metric_overrides["detection_delay_s"] == pytest.approx(1.0)
    assert contribution.metric_overrides["diagnostic_risk_iae"] == pytest.approx(0.1)
