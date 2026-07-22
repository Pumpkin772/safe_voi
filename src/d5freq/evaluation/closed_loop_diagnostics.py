"""Evaluation-only diagnostic metrics for one closed-loop episode.

The functions in this module merge controller-side diagnostic records with
simulator truth *after* every controller action has finished.  Runtime code is
never given a reference label.  Native K-component beliefs are aggregated to
the four declared semantic classes only in this evaluation layer.

Failed episodes retain any complete, time-aligned prefix.  Missing data are
reported as nullable metrics plus an audit reason; malformed or internally
misaligned non-empty data are rejected instead of being silently repaired.
Truth-informed Oracle routing is explicitly qualified and is never published
in the standard diagnostic columns used to compare deployable methods.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from numbers import Integral, Real
import re
from types import MappingProxyType
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from d5freq.evaluation.closed_loop_runner import (
    EpisodeEvaluationData,
    EvaluationContribution,
)
from d5freq.evaluation.online_diagnostic_metrics import (
    FalseAlarmMetrics,
    ModeProbabilityMetrics,
    OODDetectionMetrics,
    SwitchDetectionMetrics,
    evaluate_false_alarms,
    evaluate_mode_probabilities,
    evaluate_ood_detection,
    evaluate_switch_detection,
)


FloatArray = NDArray[np.float64]
DiagnosticQualification = Literal["none", "runtime", "truth_informed"]

KNOWN_SEMANTIC_CLASSES: tuple[str, ...] = (
    "nominal",
    "sluggish",
    "derated",
    "unavailable",
)

DIAGNOSTIC_EPISODE_FIELDS: tuple[str, ...] = (
    "mode_accuracy",
    "macro_f1",
    "detection_delay_s",
    "detection_event_count",
    "detection_censored_count",
    "detection_censoring_time_s",
    "false_alarm_rate",
    "brier",
    "nll",
    "ece",
    "ood_auroc",
    "ood_auprc",
    "ood_detected",
    "ood_detection_delay_s",
    "ood_detection_event_count",
    "ood_detection_censored_count",
    "ood_detection_censoring_time_s",
    "diagnostic_risk_iae",
)

_BELIEF_COLUMN = re.compile(r"^belief_(\d+)$")
_METHODS_WITHOUT_RUNTIME_DIAGNOSIS = frozenset({"B0", "B1", "B2"})


def _null_metric_values() -> dict[str, float | int | bool | None]:
    return {name: None for name in DIAGNOSTIC_EPISODE_FIELDS}


def _finite(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _positive(value: object, name: str) -> float:
    normalized = _finite(value, name)
    if normalized <= 0.0:
        raise ValueError(f"{name} must be strictly positive")
    return normalized


def _positive_int(value: object, name: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    minimum = 0 if allow_zero else 1
    if normalized < minimum:
        relation = "non-negative" if allow_zero else "strictly positive"
        raise ValueError(f"{name} must be {relation}")
    return normalized


@dataclass(frozen=True, slots=True)
class ClosedLoopDiagnosticConfig:
    """Frozen single-episode diagnostic definitions for Phase 6."""

    sample_time_s: float = 0.5
    nominal_frequency_hz: float = 50.0
    switch_belief_threshold: float = 0.8
    switch_consecutive_steps: int = 3
    false_alarm_persistence_steps: int = 3
    reliability_bin_count: int = 10
    probability_floor: float = 1.0e-12
    warmup_steps: int = 2
    time_tolerance_s: float = 1.0e-9
    probability_sum_tolerance: float = 1.0e-8

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "sample_time_s", _positive(self.sample_time_s, "sample_time_s")
        )
        object.__setattr__(
            self,
            "nominal_frequency_hz",
            _positive(self.nominal_frequency_hz, "nominal_frequency_hz"),
        )
        threshold = _finite(
            self.switch_belief_threshold, "switch_belief_threshold"
        )
        if not 0.0 < threshold <= 1.0:
            raise ValueError("switch_belief_threshold must lie in (0, 1]")
        object.__setattr__(self, "switch_belief_threshold", threshold)
        object.__setattr__(
            self,
            "switch_consecutive_steps",
            _positive_int(self.switch_consecutive_steps, "switch_consecutive_steps"),
        )
        object.__setattr__(
            self,
            "false_alarm_persistence_steps",
            _positive_int(
                self.false_alarm_persistence_steps,
                "false_alarm_persistence_steps",
                allow_zero=True,
            ),
        )
        object.__setattr__(
            self,
            "reliability_bin_count",
            _positive_int(self.reliability_bin_count, "reliability_bin_count"),
        )
        floor = _finite(self.probability_floor, "probability_floor")
        if not 0.0 < floor <= 1.0:
            raise ValueError("probability_floor must lie in (0, 1]")
        object.__setattr__(self, "probability_floor", floor)
        object.__setattr__(
            self,
            "warmup_steps",
            _positive_int(self.warmup_steps, "warmup_steps", allow_zero=True),
        )
        tolerance = _finite(self.time_tolerance_s, "time_tolerance_s")
        if tolerance < 0.0:
            raise ValueError("time_tolerance_s must be non-negative")
        object.__setattr__(self, "time_tolerance_s", tolerance)
        sum_tolerance = _finite(
            self.probability_sum_tolerance, "probability_sum_tolerance"
        )
        if sum_tolerance <= 0.0:
            raise ValueError("probability_sum_tolerance must be strictly positive")
        object.__setattr__(
            self, "probability_sum_tolerance", sum_tolerance
        )


@dataclass(frozen=True, slots=True)
class DiagnosticEpisodeEvaluation:
    """Nullable flat fields plus the complete evaluation-only audit record."""

    metric_values: Mapping[str, float | int | bool | None]
    audit: Mapping[str, Any]

    def __post_init__(self) -> None:
        if set(self.metric_values) != set(DIAGNOSTIC_EPISODE_FIELDS):
            raise ValueError("metric_values do not match diagnostic episode fields")
        object.__setattr__(
            self, "metric_values", MappingProxyType(dict(self.metric_values))
        )
        object.__setattr__(self, "audit", MappingProxyType(dict(self.audit)))

    def to_contribution(self) -> EvaluationContribution:
        return EvaluationContribution(
            metric_overrides=self.metric_values,
            artifacts={"closed_loop_diagnostics_eval_only": self.audit},
        )


@dataclass(frozen=True, slots=True)
class _AlignedDiagnosticTrace:
    times_s: FloatArray
    true_modes: tuple[str, ...]
    beliefs: FloatArray
    records: tuple[Mapping[str, Any], ...]
    original_indices: tuple[int, ...]
    dropped_unaligned_suffix_count: int


def _qualification(value: object) -> DiagnosticQualification:
    if not isinstance(value, str):
        raise TypeError("diagnostic_qualification must be a string")
    normalized = value.strip().lower()
    if normalized not in {"none", "runtime", "truth_informed"}:
        raise ValueError(
            "diagnostic_qualification must be none, runtime, or truth_informed"
        )
    return normalized  # type: ignore[return-value]


def _known_classes(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise TypeError("known_semantic_classes must be a sequence")
    labels = tuple(str(value).strip() for value in values)
    if not labels or any(not value for value in labels):
        raise ValueError("known_semantic_classes must contain non-empty names")
    if len(set(labels)) != len(labels):
        raise ValueError("known_semantic_classes must be unique")
    return labels


def _component_mapping(
    raw: Mapping[int | str, str] | None,
    labels: tuple[str, ...],
) -> dict[int, str]:
    if raw is None or not isinstance(raw, Mapping) or not raw:
        raise ValueError("runtime diagnostics require a non-empty component mapping")
    mapping: dict[int, str] = {}
    for key, value in raw.items():
        if isinstance(key, (bool, np.bool_)):
            raise TypeError("component IDs must be non-negative integers")
        if isinstance(key, Integral):
            component_id = int(key)
        elif isinstance(key, str) and re.fullmatch(r"0|[1-9]\d*", key.strip()):
            component_id = int(key.strip())
        else:
            raise TypeError("component IDs must be non-negative integers")
        if component_id < 0 or component_id in mapping:
            raise ValueError("component IDs must be unique non-negative integers")
        semantic = str(value).strip()
        if semantic not in labels:
            raise ValueError("component mapping references an unknown semantic class")
        mapping[component_id] = semantic
    if set(mapping) != set(range(len(mapping))):
        raise ValueError("component mapping must cover contiguous IDs 0..K-1")
    return mapping


def _record_time(record: Mapping[str, Any], ordinal: int) -> float:
    if not isinstance(record, Mapping):
        raise TypeError(f"controller_records[{ordinal}] must be a mapping")
    if "time_s" not in record:
        raise KeyError(f"controller_records[{ordinal}] lacks time_s")
    time_s = _finite(record["time_s"], f"controller_records[{ordinal}].time_s")
    if time_s < 0.0:
        raise ValueError("controller record times must be non-negative")
    return time_s


def _valid_update(record: Mapping[str, Any], ordinal: int, warmup_steps: int) -> bool:
    if "valid_update" in record:
        value = record["valid_update"]
        if not isinstance(value, (bool, np.bool_)):
            raise TypeError("valid_update must be boolean")
        return bool(value)
    sample_index = record.get("sample_index", ordinal)
    if isinstance(sample_index, (bool, np.bool_)) or not isinstance(
        sample_index, Integral
    ):
        raise TypeError("sample_index must be an integer when present")
    if int(sample_index) < 0:
        raise ValueError("sample_index must be non-negative")
    return int(sample_index) >= warmup_steps


def _belief_vector(
    record: Mapping[str, Any],
    *,
    component_count: int,
    ordinal: int,
    sum_tolerance: float,
) -> FloatArray:
    if "raw_mode_belief" in record:
        raw: object = record["raw_mode_belief"]
    elif "mode_belief" in record:
        raw = record["mode_belief"]
    else:
        indexed: dict[int, object] = {}
        for key, value in record.items():
            match = _BELIEF_COLUMN.fullmatch(str(key))
            if match is not None:
                indexed[int(match.group(1))] = value
        if set(indexed) != set(range(component_count)):
            raise ValueError(
                f"controller_records[{ordinal}] belief columns do not match K="
                f"{component_count}"
            )
        raw = [indexed[index] for index in range(component_count)]
    array_raw = np.asarray(raw)
    if np.iscomplexobj(array_raw):
        raise TypeError("component beliefs must be real-valued")
    values = np.asarray(array_raw, dtype=np.float64)
    if values.shape != (component_count,):
        raise ValueError(
            f"controller_records[{ordinal}] belief must have shape "
            f"({component_count},)"
        )
    if not np.all(np.isfinite(values)) or np.any(values < 0.0):
        raise ValueError("component beliefs must be finite and non-negative")
    total = float(np.sum(values))
    if total <= 0.0 or abs(total - 1.0) > sum_tolerance:
        raise ValueError("component belief must sum to one within tolerance")
    normalized = values / total
    map_mode = record.get("map_mode")
    if map_mode is not None:
        if isinstance(map_mode, (bool, np.bool_)) or not isinstance(
            map_mode, Integral
        ):
            raise TypeError("map_mode must be an integer when present")
        if int(map_mode) != int(np.argmax(normalized)):
            raise ValueError("map_mode disagrees with the component belief argmax")
    return normalized


def _truth_timeline(
    truth_points_eval_only: Sequence[Mapping[str, Any]],
    tolerance: float,
) -> tuple[FloatArray, tuple[str, ...]]:
    times: list[float] = []
    modes: list[str] = []
    for ordinal, point in enumerate(truth_points_eval_only):
        if not isinstance(point, Mapping):
            raise TypeError(f"truth_points_eval_only[{ordinal}] must be a mapping")
        if "time_s" not in point or "true_mode_eval_only" not in point:
            raise KeyError("truth points require time_s and true_mode_eval_only")
        time_s = _finite(point["time_s"], f"truth_points_eval_only[{ordinal}].time_s")
        if time_s < 0.0:
            raise ValueError("truth point times must be non-negative")
        mode = str(point["true_mode_eval_only"]).strip()
        if not mode:
            raise ValueError("true_mode_eval_only must be non-empty")
        if times and time_s < times[-1] - tolerance:
            raise ValueError("truth point times must be non-decreasing")
        if times and abs(time_s - times[-1]) <= tolerance:
            if mode != modes[-1]:
                raise ValueError("duplicate truth time carries conflicting modes")
            continue
        times.append(time_s)
        modes.append(mode)
    return np.asarray(times, dtype=np.float64), tuple(modes)


def _truth_at_exact_time(
    time_s: float,
    truth_times: FloatArray,
    truth_modes: tuple[str, ...],
    tolerance: float,
) -> str | None:
    if truth_times.size == 0:
        return None
    insertion = int(np.searchsorted(truth_times, time_s, side="left"))
    candidates = tuple(
        index
        for index in (insertion - 1, insertion)
        if 0 <= index < truth_times.size
    )
    matches = [
        index for index in candidates if abs(float(truth_times[index]) - time_s) <= tolerance
    ]
    if not matches:
        return None
    best = min(matches, key=lambda index: abs(float(truth_times[index]) - time_s))
    return truth_modes[best]


def _align_trace(
    controller_records: Sequence[Mapping[str, Any]],
    truth_points_eval_only: Sequence[Mapping[str, Any]],
    mapping: Mapping[int, str],
    config: ClosedLoopDiagnosticConfig,
    *,
    run_completed: bool,
) -> _AlignedDiagnosticTrace | None:
    record_times = [
        _record_time(record, ordinal)
        for ordinal, record in enumerate(controller_records)
    ]
    if any(
        current <= previous
        for previous, current in zip(record_times, record_times[1:], strict=False)
    ):
        raise ValueError("controller record times must be strictly increasing")
    for previous, current in zip(record_times, record_times[1:], strict=False):
        if not math.isclose(
            current - previous,
            config.sample_time_s,
            rel_tol=0.0,
            abs_tol=config.time_tolerance_s,
        ):
            raise ValueError(
                "controller record spacing does not match the declared sample_time_s"
            )
    truth_times, truth_modes = _truth_timeline(
        truth_points_eval_only, config.time_tolerance_s
    )
    if not record_times or truth_times.size == 0:
        return None

    retained_records: list[Mapping[str, Any]] = []
    retained_times: list[float] = []
    retained_truth: list[str] = []
    retained_indices: list[int] = []
    beliefs: list[FloatArray] = []
    unmatched_suffix = False
    dropped = 0
    last_truth_time = float(truth_times[-1])
    for ordinal, (record, time_s) in enumerate(
        zip(controller_records, record_times, strict=True)
    ):
        mode = _truth_at_exact_time(
            time_s, truth_times, truth_modes, config.time_tolerance_s
        )
        if mode is None:
            suffix_candidate = time_s > last_truth_time + config.time_tolerance_s
            if not run_completed and suffix_candidate:
                unmatched_suffix = True
                dropped += 1
                continue
            raise ValueError(
                f"controller record at {time_s:.12g} s has no exact evaluator-truth sample"
            )
        if unmatched_suffix:
            raise ValueError("an unaligned controller suffix cannot return to aligned truth")
        if not _valid_update(record, ordinal, config.warmup_steps):
            continue
        retained_records.append(record)
        retained_times.append(time_s)
        retained_truth.append(mode)
        retained_indices.append(ordinal)
        beliefs.append(
            _belief_vector(
                record,
                component_count=len(mapping),
                ordinal=ordinal,
                sum_tolerance=config.probability_sum_tolerance,
            )
        )
    if not retained_records:
        return _AlignedDiagnosticTrace(
            times_s=np.empty(0, dtype=np.float64),
            true_modes=(),
            beliefs=np.empty((0, len(mapping)), dtype=np.float64),
            records=(),
            original_indices=(),
            dropped_unaligned_suffix_count=dropped,
        )
    return _AlignedDiagnosticTrace(
        times_s=np.asarray(retained_times, dtype=np.float64),
        true_modes=tuple(retained_truth),
        beliefs=np.vstack(beliefs),
        records=tuple(retained_records),
        original_indices=tuple(retained_indices),
        dropped_unaligned_suffix_count=dropped,
    )


def _aggregate_beliefs(
    component_beliefs: FloatArray,
    mapping: Mapping[int, str],
    labels: tuple[str, ...],
) -> FloatArray:
    label_index = {label: index for index, label in enumerate(labels)}
    aggregate = np.zeros((component_beliefs.shape[0], len(labels)), dtype=np.float64)
    for component_id, semantic in mapping.items():
        aggregate[:, label_index[semantic]] += component_beliefs[:, component_id]
    row_sums = np.sum(aggregate, axis=1, keepdims=True)
    if np.any(row_sums <= 0.0):
        raise ValueError("aggregated semantic beliefs have a zero-probability row")
    aggregate /= row_sums
    return aggregate


def _known_segment_ids(
    original_indices: Sequence[int], true_modes: Sequence[str], known: set[str]
) -> tuple[str, ...]:
    segment = -1
    previous_index: int | None = None
    result: list[str] = []
    for original_index, mode in zip(original_indices, true_modes, strict=True):
        if mode not in known:
            previous_index = None
            continue
        if previous_index is None or original_index != previous_index + 1:
            segment += 1
        result.append(f"known-segment-{segment}")
        previous_index = original_index
    return tuple(result)


def _active_value(record: Mapping[str, Any]) -> bool | None:
    explicit = record.get("ood_active")
    state_value = record.get("diagnostic_state", record.get("ood_state"))
    state = None if state_value is None else str(state_value).strip().upper()
    if explicit is not None:
        if not isinstance(explicit, (bool, np.bool_)):
            raise TypeError("ood_active must be boolean when present")
        active = bool(explicit)
        if state is not None and (state == "OOD_ACTIVE") != active:
            raise ValueError("ood_active disagrees with diagnostic/ood state")
        return active
    if state is None:
        return None
    return state == "OOD_ACTIVE"


def _ood_vectors(
    records: Sequence[Mapping[str, Any]],
) -> tuple[FloatArray, NDArray[np.bool_], str] | None:
    source: str | None = None
    scores: list[float] = []
    active_values: list[bool] = []
    for record in records:
        if "ood_pvalue" in record:
            current_source = "ood_pvalue_lower_is_more_ood"
            value = _finite(record["ood_pvalue"], "ood_pvalue")
            if not 0.0 <= value <= 1.0:
                raise ValueError("ood_pvalue must lie in [0, 1]")
            score = 1.0 - value
        elif "ood_score" in record:
            current_source = "ood_score_higher_is_more_ood"
            score = _finite(record["ood_score"], "ood_score")
        else:
            return None
        active = _active_value(record)
        if active is None:
            return None
        if source is None:
            source = current_source
        elif source != current_source:
            raise ValueError("OOD score source cannot change within one episode")
        scores.append(score)
        active_values.append(active)
    assert source is not None
    return (
        np.asarray(scores, dtype=np.float64),
        np.asarray(active_values, dtype=np.bool_),
        source,
    )


def _mean_censoring_time(events: Sequence[object]) -> float | None:
    values = [
        float(getattr(event, "censoring_time_s"))
        for event in events
        if bool(getattr(event, "censored"))
    ]
    return None if not values else float(np.mean(np.asarray(values, dtype=np.float64)))


def _metrics_artifact(
    probability: ModeProbabilityMetrics | None,
    switches: SwitchDetectionMetrics | None,
    false_alarms: FalseAlarmMetrics | None,
    ood: OODDetectionMetrics | None,
) -> dict[str, Any]:
    return {
        "known_mode_probability": None if probability is None else probability.to_dict(),
        "known_mode_switch_detection": None if switches is None else switches.to_dict(),
        "known_mode_false_alarms": (
            None if false_alarms is None else false_alarms.to_dict()
        ),
        "ood_detection": None if ood is None else ood.to_dict(),
    }


def _not_published(
    *,
    qualification: DiagnosticQualification,
    run_completed: bool,
    controller_record_count: int,
    truth_point_count: int,
    reason: str,
    method_id: str | None,
) -> DiagnosticEpisodeEvaluation:
    return DiagnosticEpisodeEvaluation(
        metric_values=_null_metric_values(),
        audit={
            "schema_version": "d5freq.closed-loop-diagnostics.v1",
            "evaluation_only": True,
            "diagnostic_qualification": qualification,
            "standard_diagnostic_fields_published": False,
            "status": "not_eligible" if qualification != "runtime" else "unavailable",
            "reason": reason,
            "method_id": method_id,
            "run_completed": bool(run_completed),
            "trace_scope": "complete_episode" if run_completed else "failure_prefix",
            "controller_record_count": controller_record_count,
            "truth_point_count": truth_point_count,
            "aligned_valid_sample_count": 0,
            "known_sample_count": 0,
            "ood_sample_count": 0,
            "metrics": _metrics_artifact(None, None, None, None),
        },
    )


def evaluate_diagnostic_trace(
    controller_records: Sequence[Mapping[str, Any]],
    truth_points_eval_only: Sequence[Mapping[str, Any]],
    *,
    component_to_semantic_eval_only: Mapping[int | str, str] | None = None,
    diagnostic_qualification: DiagnosticQualification = "runtime",
    run_completed: bool = True,
    method_id: str | None = None,
    config: ClosedLoopDiagnosticConfig = ClosedLoopDiagnosticConfig(),
    known_semantic_classes: Sequence[str] = KNOWN_SEMANTIC_CLASSES,
) -> DiagnosticEpisodeEvaluation:
    """Evaluate one diagnostic trace after joining evaluator-only truth.

    ``diagnostic_qualification="none"`` is required for methods without an
    online diagnosis.  ``truth_informed`` explicitly marks an Oracle-like
    diagnostic and suppresses all standard comparison fields.  Only
    ``runtime`` diagnostics are evaluated and published.
    """

    if isinstance(controller_records, (str, bytes, bytearray)) or not isinstance(
        controller_records, Sequence
    ):
        raise TypeError("controller_records must be a sequence of mappings")
    if isinstance(truth_points_eval_only, (str, bytes, bytearray)) or not isinstance(
        truth_points_eval_only, Sequence
    ):
        raise TypeError("truth_points_eval_only must be a sequence of mappings")
    if not isinstance(run_completed, (bool, np.bool_)):
        raise TypeError("run_completed must be boolean")
    if method_id is not None and (not isinstance(method_id, str) or not method_id.strip()):
        raise ValueError("method_id must be a non-empty string or None")
    if not isinstance(config, ClosedLoopDiagnosticConfig):
        raise TypeError("config must be ClosedLoopDiagnosticConfig")
    qualification = _qualification(diagnostic_qualification)
    normalized_method = None if method_id is None else method_id.strip()
    if normalized_method == "B4" and qualification == "runtime":
        raise ValueError(
            "B4 Oracle diagnostics must be explicitly truth_informed or none"
        )
    if normalized_method in _METHODS_WITHOUT_RUNTIME_DIAGNOSIS:
        return _not_published(
            qualification="none",
            run_completed=bool(run_completed),
            controller_record_count=len(controller_records),
            truth_point_count=len(truth_points_eval_only),
            reason="method_declares_no_runtime_diagnosis",
            method_id=normalized_method,
        )
    if qualification == "none":
        return _not_published(
            qualification=qualification,
            run_completed=bool(run_completed),
            controller_record_count=len(controller_records),
            truth_point_count=len(truth_points_eval_only),
            reason="method_declares_no_runtime_diagnosis",
            method_id=normalized_method,
        )
    if qualification == "truth_informed":
        return _not_published(
            qualification=qualification,
            run_completed=bool(run_completed),
            controller_record_count=len(controller_records),
            truth_point_count=len(truth_points_eval_only),
            reason="truth_informed_diagnostics_are_upper_bound_only",
            method_id=normalized_method,
        )

    labels = _known_classes(known_semantic_classes)
    mapping = _component_mapping(component_to_semantic_eval_only, labels)
    if not controller_records:
        return _not_published(
            qualification=qualification,
            run_completed=bool(run_completed),
            controller_record_count=0,
            truth_point_count=len(truth_points_eval_only),
            reason="no_controller_diagnostic_records",
            method_id=normalized_method,
        )
    if not truth_points_eval_only:
        return _not_published(
            qualification=qualification,
            run_completed=bool(run_completed),
            controller_record_count=len(controller_records),
            truth_point_count=0,
            reason="no_evaluator_truth_prefix",
            method_id=normalized_method,
        )

    aligned = _align_trace(
        controller_records,
        truth_points_eval_only,
        mapping,
        config,
        run_completed=bool(run_completed),
    )
    if aligned is None or aligned.times_s.size == 0:
        return _not_published(
            qualification=qualification,
            run_completed=bool(run_completed),
            controller_record_count=len(controller_records),
            truth_point_count=len(truth_points_eval_only),
            reason="no_valid_time_aligned_diagnostic_updates",
            method_id=normalized_method,
        )

    semantic_beliefs = _aggregate_beliefs(aligned.beliefs, mapping, labels)
    known_set = set(labels)
    known_mask = np.asarray(
        [mode in known_set for mode in aligned.true_modes], dtype=np.bool_
    )
    ood_truth = ~known_mask
    predicted_semantics = np.asarray(labels, dtype=object)[
        np.argmax(semantic_beliefs, axis=1)
    ]

    probability_metrics: ModeProbabilityMetrics | None = None
    switch_metrics: SwitchDetectionMetrics | None = None
    false_metrics: FalseAlarmMetrics | None = None
    if np.any(known_mask):
        probability_metrics = evaluate_mode_probabilities(
            [
                mode
                for mode, is_known in zip(
                    aligned.true_modes, known_mask.tolist(), strict=True
                )
                if is_known
            ],
            semantic_beliefs[known_mask],
            class_labels=labels,
            reliability_bin_count=config.reliability_bin_count,
            minimum_probability=config.probability_floor,
        )
        known_truth = tuple(
            mode
            for mode, is_known in zip(
                aligned.true_modes, known_mask.tolist(), strict=True
            )
            if is_known
        )
        switch_metrics = evaluate_switch_detection(
            known_truth,
            semantic_beliefs[known_mask],
            sample_time_s=config.sample_time_s,
            belief_threshold=config.switch_belief_threshold,
            consecutive_steps=config.switch_consecutive_steps,
            class_labels=labels,
            episode_ids=_known_segment_ids(
                aligned.original_indices, aligned.true_modes, known_set
            ),
            time_s=aligned.times_s[known_mask],
        )
        if (
            all(mode in known_set for mode in aligned.true_modes)
            and len(set(aligned.true_modes)) == 1
        ):
            false_metrics = evaluate_false_alarms(
                aligned.true_modes,
                predicted_semantics.tolist(),
                sample_time_s=config.sample_time_s,
                persistence_limit_steps=config.false_alarm_persistence_steps,
            )

    ood_metrics: OODDetectionMetrics | None = None
    ood_score_source: str | None = None
    ood_missing_runtime_fields = False
    if np.any(ood_truth) and np.any(known_mask):
        ood_vectors = _ood_vectors(aligned.records)
        if ood_vectors is None:
            ood_missing_runtime_fields = True
        else:
            ood_scores, ood_active, ood_score_source = ood_vectors
            ood_metrics = evaluate_ood_detection(
                ood_truth,
                ood_scores,
                ood_active,
                sample_time_s=config.sample_time_s,
                time_s=aligned.times_s,
                higher_score_more_ood=True,
            )

    values = _null_metric_values()
    if probability_metrics is not None:
        values.update(
            {
                "mode_accuracy": probability_metrics.accuracy,
                "macro_f1": probability_metrics.macro_f1,
                "brier": probability_metrics.brier_score,
                "nll": probability_metrics.negative_log_likelihood,
                "ece": probability_metrics.expected_calibration_error,
            }
        )
    if switch_metrics is not None:
        values.update(
            {
                "detection_delay_s": switch_metrics.mean_detected_delay_s,
                "detection_event_count": switch_metrics.event_count,
                "detection_censored_count": switch_metrics.censored_count,
                "detection_censoring_time_s": _mean_censoring_time(
                    switch_metrics.events
                ),
            }
        )
    if false_metrics is not None:
        values["false_alarm_rate"] = false_metrics.false_alarms_per_hour
    if ood_metrics is not None:
        values.update(
            {
                "ood_auroc": ood_metrics.auroc,
                "ood_auprc": ood_metrics.auprc,
                "ood_detected": ood_metrics.detected_count > 0,
                "ood_detection_delay_s": ood_metrics.mean_detected_delay_s,
                "ood_detection_event_count": ood_metrics.event_count,
                "ood_detection_censored_count": ood_metrics.censored_count,
                "ood_detection_censoring_time_s": _mean_censoring_time(
                    ood_metrics.events
                ),
            }
        )

    audit = {
        "schema_version": "d5freq.closed-loop-diagnostics.v1",
        "evaluation_only": True,
        "diagnostic_qualification": qualification,
        "standard_diagnostic_fields_published": True,
        "status": "evaluated_prefix" if not run_completed else "evaluated_complete",
        "reason": None,
        "method_id": normalized_method,
        "run_completed": bool(run_completed),
        "trace_scope": "complete_episode" if run_completed else "failure_prefix",
        "controller_record_count": len(controller_records),
        "truth_point_count": len(truth_points_eval_only),
        "aligned_valid_sample_count": int(aligned.times_s.size),
        "known_sample_count": int(np.count_nonzero(known_mask)),
        "ood_sample_count": int(np.count_nonzero(ood_truth)),
        "dropped_unaligned_failure_suffix_count": (
            aligned.dropped_unaligned_suffix_count
        ),
        "first_valid_time_s": float(aligned.times_s[0]),
        "last_valid_time_s": float(aligned.times_s[-1]),
        "known_semantic_classes": list(labels),
        "component_to_semantic_eval_only": {
            str(component_id): semantic
            for component_id, semantic in sorted(mapping.items())
        },
        "switch_definition": {
            "belief_threshold": config.switch_belief_threshold,
            "consecutive_steps": config.switch_consecutive_steps,
        },
        "false_alarm_definition": {
            "wrong_map_run_must_strictly_exceed_steps": (
                config.false_alarm_persistence_steps
            ),
            "eligible_scope": "known-only episode without a true known-mode switch",
        },
        "ood_score_source": ood_score_source,
        "ood_runtime_fields_missing": ood_missing_runtime_fields,
        "unknown_truth_excluded_from_known_probability_metrics": True,
        "metrics": _metrics_artifact(
            probability_metrics, switch_metrics, false_metrics, ood_metrics
        ),
    }
    return DiagnosticEpisodeEvaluation(metric_values=values, audit=audit)


def evaluate_episode_diagnostics(
    data: EpisodeEvaluationData,
    *,
    component_to_semantic_eval_only: Mapping[int | str, str] | None = None,
    diagnostic_qualification: DiagnosticQualification = "runtime",
    config: ClosedLoopDiagnosticConfig = ClosedLoopDiagnosticConfig(),
    known_semantic_classes: Sequence[str] = KNOWN_SEMANTIC_CLASSES,
) -> EvaluationContribution:
    """Adapter from :class:`EpisodeEvaluationData` to a runner contribution."""

    if not isinstance(data, EpisodeEvaluationData):
        raise TypeError("data must be EpisodeEvaluationData")
    evaluated = evaluate_diagnostic_trace(
        data.controller_records,
        data.truth_points_eval_only,
        component_to_semantic_eval_only=component_to_semantic_eval_only,
        diagnostic_qualification=diagnostic_qualification,
        run_completed=data.run_completed,
        method_id=data.identity.method,
        config=config,
        known_semantic_classes=known_semantic_classes,
    )
    values = dict(evaluated.metric_values)
    audit = dict(evaluated.audit)
    switch_summary = audit.get("metrics", {}).get("known_mode_switch_detection")
    if (
        audit.get("standard_diagnostic_fields_published") is True
        and isinstance(switch_summary, Mapping)
        and switch_summary.get("events")
        and data.high_frequency_truth is not None
        and len(data.high_frequency_truth.time_s) >= 2
    ):
        truth = data.high_frequency_truth
        time_s = np.asarray(truth.time_s, dtype=np.float64)
        delta_hz = np.asarray(
            truth.delta_hz(config.nominal_frequency_hz), dtype=np.float64
        )
        event_risks: list[dict[str, float | bool]] = []
        total_risk = 0.0
        for event in switch_summary["events"]:
            if not isinstance(event, Mapping):
                raise TypeError("switch-detection event audit must be a mapping")
            onset = _finite(event["switch_time_s"], "switch_time_s")
            detection = event.get("detection_time_s")
            censored = bool(event.get("censored"))
            endpoint = (
                onset + _finite(event["censoring_time_s"], "censoring_time_s")
                if detection is None
                else _finite(detection, "detection_time_s")
            )
            lower = max(onset, float(time_s[0]))
            upper = min(endpoint, float(time_s[-1]))
            risk = 0.0
            if upper > lower:
                inside = (time_s > lower) & (time_s < upper)
                clipped_time = np.concatenate(([lower], time_s[inside], [upper]))
                clipped_delta = np.interp(clipped_time, time_s, delta_hz)
                risk = float(np.trapezoid(np.abs(clipped_delta), clipped_time))
            total_risk += risk
            event_risks.append(
                {
                    "switch_time_s": onset,
                    "endpoint_time_s": endpoint,
                    "censored": censored,
                    "frequency_iae_hz_s": risk,
                }
            )
        values["diagnostic_risk_iae"] = total_risk
        audit["diagnostic_risk"] = {
            "definition": "sum integral |delta_f| from each switch to detection or censoring boundary",
            "nominal_frequency_hz": config.nominal_frequency_hz,
            "events": event_risks,
            "total_frequency_iae_hz_s": total_risk,
        }
    return DiagnosticEpisodeEvaluation(values, audit).to_contribution()


def make_closed_loop_diagnostic_evaluator(
    *,
    component_to_semantic_eval_only: Mapping[int | str, str] | None = None,
    diagnostic_qualification: DiagnosticQualification = "runtime",
    config: ClosedLoopDiagnosticConfig = ClosedLoopDiagnosticConfig(),
    known_semantic_classes: Sequence[str] = KNOWN_SEMANTIC_CLASSES,
):
    """Freeze evaluator arguments for ``run_closed_loop_episode(evaluators=...)``."""

    qualification = _qualification(diagnostic_qualification)
    labels = _known_classes(known_semantic_classes)
    frozen_mapping = (
        None
        if component_to_semantic_eval_only is None
        else MappingProxyType(dict(component_to_semantic_eval_only))
    )

    def evaluator(data: EpisodeEvaluationData) -> EvaluationContribution:
        return evaluate_episode_diagnostics(
            data,
            component_to_semantic_eval_only=frozen_mapping,
            diagnostic_qualification=qualification,
            config=config,
            known_semantic_classes=labels,
        )

    return evaluator


__all__ = [
    "DIAGNOSTIC_EPISODE_FIELDS",
    "KNOWN_SEMANTIC_CLASSES",
    "ClosedLoopDiagnosticConfig",
    "DiagnosticEpisodeEvaluation",
    "DiagnosticQualification",
    "evaluate_diagnostic_trace",
    "evaluate_episode_diagnostics",
    "make_closed_loop_diagnostic_evaluator",
]
