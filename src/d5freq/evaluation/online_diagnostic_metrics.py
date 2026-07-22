"""Evaluation-only metrics for online mode diagnosis and OOD detection.

This module is the only layer in the online-diagnosis pipeline that accepts
reference mode or OOD truth.  The returned records are reporting artifacts;
they must never be fed back to a runtime belief filter or controller.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    roc_auc_score,
)


FloatArray = NDArray[np.float64]


def _jsonable(value: Hashable) -> str | int | float | bool | None:
    """Convert a label to a stable, JSON-compatible scalar."""

    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value
    return repr(value)


def _label_vector(values: Sequence[Hashable] | ArrayLike, name: str) -> tuple[Hashable, ...]:
    array = np.asarray(values, dtype=object)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional vector")
    normalized: list[Hashable] = []
    for raw in array.tolist():
        value = raw.item() if isinstance(raw, np.generic) else raw
        if value is None:
            raise ValueError(f"{name} cannot contain None")
        try:
            hash(value)
        except TypeError as exc:
            raise TypeError(f"{name} must contain hashable labels") from exc
        if isinstance(value, Real) and not isinstance(value, (bool, np.bool_)):
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} cannot contain non-finite labels")
        normalized.append(value)
    return tuple(normalized)


def _class_labels(
    values: Sequence[Hashable] | ArrayLike | None,
    class_count: int,
) -> tuple[Hashable, ...]:
    labels = tuple(range(class_count)) if values is None else _label_vector(values, "class_labels")
    if len(labels) != class_count:
        raise ValueError("class_labels must have one label per probability column")
    if len(set(labels)) != len(labels):
        raise ValueError("class_labels must be unique")
    return labels


def _probability_matrix(values: ArrayLike) -> FloatArray:
    raw = np.asarray(values)
    if np.iscomplexobj(raw):
        raise TypeError("mode_probabilities must be real-valued")
    probabilities = np.asarray(raw, dtype=np.float64)
    if probabilities.ndim != 2 or probabilities.shape[0] == 0 or probabilities.shape[1] < 2:
        raise ValueError("mode_probabilities must have shape (n_samples, n_classes >= 2)")
    if not np.all(np.isfinite(probabilities)):
        raise ValueError("mode_probabilities must contain only finite values")
    if np.any(probabilities < 0.0) or np.any(probabilities > 1.0):
        raise ValueError("mode_probabilities must lie in [0, 1]")
    row_sums = np.sum(probabilities, axis=1)
    if not np.allclose(row_sums, 1.0, rtol=1e-9, atol=1e-9):
        raise ValueError("every probability row must sum to one")
    return probabilities.copy()


def _positive_float(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ValueError(f"{name} must be finite and strictly positive")
    return normalized


def _unit_interval(value: float, name: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    lower_ok = normalized >= 0.0 if allow_zero else normalized > 0.0
    if not math.isfinite(normalized) or not lower_ok or normalized > 1.0:
        boundary = "[0, 1]" if allow_zero else "(0, 1]"
        raise ValueError(f"{name} must lie in {boundary}")
    return normalized


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized <= 0:
        raise ValueError(f"{name} must be strictly positive")
    return normalized


def _nonnegative_int(value: int, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def _truth_indices(
    truth: Sequence[Hashable] | ArrayLike,
    labels: tuple[Hashable, ...],
    expected_length: int,
) -> NDArray[np.int64]:
    values = _label_vector(truth, "true_modes_eval_only")
    if len(values) != expected_length:
        raise ValueError("truth and prediction arrays must have equal sample counts")
    label_to_index = {label: index for index, label in enumerate(labels)}
    unknown = tuple(value for value in values if value not in label_to_index)
    if unknown:
        raise ValueError(f"truth contains labels absent from class_labels: {unknown[:3]}")
    return np.asarray([label_to_index[value] for value in values], dtype=np.int64)


def _episode_vector(
    episode_ids: Sequence[Hashable] | ArrayLike | None,
    sample_count: int,
) -> tuple[Hashable, ...]:
    if episode_ids is None:
        return tuple(0 for _ in range(sample_count))
    values = _label_vector(episode_ids, "episode_ids")
    if len(values) != sample_count:
        raise ValueError("episode_ids must have one entry per sample")
    seen: set[Hashable] = set()
    previous: Hashable | object = object()
    for value in values:
        if value != previous:
            if value in seen:
                raise ValueError("each episode_id must occupy one contiguous block")
            seen.add(value)
            previous = value
    return values


def _episode_slices(episode_ids: tuple[Hashable, ...]) -> tuple[tuple[int, int, Hashable], ...]:
    slices: list[tuple[int, int, Hashable]] = []
    start = 0
    for index in range(1, len(episode_ids) + 1):
        if index == len(episode_ids) or episode_ids[index] != episode_ids[start]:
            slices.append((start, index, episode_ids[start]))
            start = index
    return tuple(slices)


def _sample_times(
    values: ArrayLike | None,
    *,
    sample_count: int,
    episode_ids: tuple[Hashable, ...],
    sample_time_s: float,
) -> FloatArray:
    """Return actual or episode-local sample times with strict validation."""

    if values is None:
        times = np.empty(sample_count, dtype=np.float64)
        for start, end, _ in _episode_slices(episode_ids):
            times[start:end] = np.arange(end - start, dtype=np.float64) * sample_time_s
        return times
    raw = np.asarray(values)
    if np.iscomplexobj(raw):
        raise TypeError("time_s must be real-valued")
    times = np.asarray(raw, dtype=np.float64)
    if times.shape != (sample_count,):
        raise ValueError("time_s must have one entry per sample")
    if not np.all(np.isfinite(times)) or np.any(times < 0.0):
        raise ValueError("time_s must be finite and non-negative")
    for start, end, _ in _episode_slices(episode_ids):
        if np.any(np.diff(times[start:end]) <= 0.0):
            raise ValueError("time_s must be strictly increasing within each episode")
    return times.copy()


def _optional_mean(values: Sequence[float]) -> float | None:
    return None if not values else float(np.mean(np.asarray(values, dtype=np.float64)))


def _optional_median(values: Sequence[float]) -> float | None:
    return None if not values else float(np.median(np.asarray(values, dtype=np.float64)))


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    """Evaluation-only hard-label accuracy and macro-F1."""

    accuracy: float
    macro_f1: float
    sample_count: int
    class_labels: tuple[Hashable, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_only": True,
            "accuracy": self.accuracy,
            "macro_f1": self.macro_f1,
            "sample_count": self.sample_count,
            "class_labels": [_jsonable(value) for value in self.class_labels],
        }


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    """One confidence bin for a multiclass reliability diagram."""

    lower_bound: float
    upper_bound: float
    count: int
    mean_confidence: float | None
    empirical_accuracy: float | None
    calibration_gap: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "count": self.count,
            "mean_confidence": self.mean_confidence,
            "empirical_accuracy": self.empirical_accuracy,
            "calibration_gap": self.calibration_gap,
        }


@dataclass(frozen=True, slots=True)
class ModeProbabilityMetrics:
    """Evaluation-only multiclass probability and classification metrics."""

    accuracy: float
    macro_f1: float
    brier_score: float
    negative_log_likelihood: float
    expected_calibration_error: float
    sample_count: int
    class_labels: tuple[Hashable, ...]
    reliability_bins: tuple[ReliabilityBin, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_only": True,
            "accuracy": self.accuracy,
            "macro_f1": self.macro_f1,
            "brier_score": self.brier_score,
            "negative_log_likelihood": self.negative_log_likelihood,
            "expected_calibration_error": self.expected_calibration_error,
            "sample_count": self.sample_count,
            "class_labels": [_jsonable(value) for value in self.class_labels],
            "reliability_bins": [item.to_dict() for item in self.reliability_bins],
        }


def evaluate_classification(
    true_modes_eval_only: Sequence[Hashable] | ArrayLike,
    predicted_modes: Sequence[Hashable] | ArrayLike,
    *,
    class_labels: Sequence[Hashable] | ArrayLike | None = None,
) -> ClassificationMetrics:
    """Evaluate hard mode decisions without exposing truth to runtime code."""

    truth = _label_vector(true_modes_eval_only, "true_modes_eval_only")
    prediction = _label_vector(predicted_modes, "predicted_modes")
    if len(truth) != len(prediction):
        raise ValueError("true_modes_eval_only and predicted_modes must have equal lengths")
    if class_labels is None:
        labels = tuple(
            sorted(set(truth).union(prediction), key=lambda value: (type(value).__qualname__, repr(value)))
        )
    else:
        labels = _label_vector(class_labels, "class_labels")
        if len(set(labels)) != len(labels):
            raise ValueError("class_labels must be unique")
        unknown = set(truth).union(prediction).difference(labels)
        if unknown:
            raise ValueError("truth or predictions contain labels absent from class_labels")
    label_to_index = {label: index for index, label in enumerate(labels)}
    truth_index = np.asarray([label_to_index[value] for value in truth], dtype=np.int64)
    predicted_index = np.asarray([label_to_index[value] for value in prediction], dtype=np.int64)
    encoded_labels = np.arange(len(labels), dtype=np.int64)
    return ClassificationMetrics(
        accuracy=float(accuracy_score(truth_index, predicted_index)),
        macro_f1=float(
            f1_score(
                truth_index,
                predicted_index,
                labels=encoded_labels,
                average="macro",
                zero_division=0.0,
            )
        ),
        sample_count=len(truth),
        class_labels=labels,
    )


def evaluate_mode_probabilities(
    true_modes_eval_only: Sequence[Hashable] | ArrayLike,
    mode_probabilities: ArrayLike,
    *,
    class_labels: Sequence[Hashable] | ArrayLike | None = None,
    reliability_bin_count: int = 10,
    minimum_probability: float = 1e-15,
) -> ModeProbabilityMetrics:
    """Compute multiclass Brier, NLL, ECE, reliability, accuracy, and F1.

    Brier score is the sample mean of the sum across all class-wise squared
    probability errors.  ECE uses the maximum predicted probability as
    confidence and equal-width bins on ``[0, 1]``.
    """

    probabilities = _probability_matrix(mode_probabilities)
    labels = _class_labels(class_labels, probabilities.shape[1])
    truth_index = _truth_indices(true_modes_eval_only, labels, probabilities.shape[0])
    bin_count = _positive_int(reliability_bin_count, "reliability_bin_count")
    probability_floor = _unit_interval(
        minimum_probability, "minimum_probability", allow_zero=False
    )
    sample_index = np.arange(probabilities.shape[0], dtype=np.int64)
    predicted_index = np.argmax(probabilities, axis=1).astype(np.int64, copy=False)
    correct = predicted_index == truth_index
    one_hot = np.zeros_like(probabilities)
    one_hot[sample_index, truth_index] = 1.0
    brier = float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))
    true_probability = probabilities[sample_index, truth_index]
    nll = float(-np.mean(np.log(np.maximum(true_probability, probability_floor))))

    confidence = np.max(probabilities, axis=1)
    bin_indices = np.minimum((confidence * bin_count).astype(np.int64), bin_count - 1)
    bins: list[ReliabilityBin] = []
    ece = 0.0
    for index in range(bin_count):
        mask = bin_indices == index
        count = int(np.count_nonzero(mask))
        lower = index / bin_count
        upper = (index + 1) / bin_count
        if count == 0:
            bins.append(ReliabilityBin(lower, upper, 0, None, None, None))
            continue
        mean_confidence = float(np.mean(confidence[mask]))
        empirical_accuracy = float(np.mean(correct[mask]))
        gap = abs(empirical_accuracy - mean_confidence)
        ece += count / probabilities.shape[0] * gap
        bins.append(
            ReliabilityBin(
                lower_bound=lower,
                upper_bound=upper,
                count=count,
                mean_confidence=mean_confidence,
                empirical_accuracy=empirical_accuracy,
                calibration_gap=gap,
            )
        )

    encoded_labels = np.arange(len(labels), dtype=np.int64)
    return ModeProbabilityMetrics(
        accuracy=float(np.mean(correct)),
        macro_f1=float(
            f1_score(
                truth_index,
                predicted_index,
                labels=encoded_labels,
                average="macro",
                zero_division=0.0,
            )
        ),
        brier_score=brier,
        negative_log_likelihood=nll,
        expected_calibration_error=float(ece),
        sample_count=probabilities.shape[0],
        class_labels=labels,
        reliability_bins=tuple(bins),
    )


@dataclass(frozen=True, slots=True)
class SwitchDetectionEvent:
    """One true switch and its detected or right-censored outcome."""

    episode_id: Hashable
    switch_index: int
    switch_time_s: float
    previous_mode: Hashable
    new_mode: Hashable
    detection_index: int | None
    detection_time_s: float | None
    delay_s: float | None
    censored: bool
    censor_index: int
    censoring_time_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_only": True,
            "episode_id": _jsonable(self.episode_id),
            "switch_index": self.switch_index,
            "switch_time_s": self.switch_time_s,
            "previous_mode": _jsonable(self.previous_mode),
            "new_mode": _jsonable(self.new_mode),
            "detection_index": self.detection_index,
            "detection_time_s": self.detection_time_s,
            "delay_s": self.delay_s,
            "censored": self.censored,
            "censor_index": self.censor_index,
            "censoring_time_s": self.censoring_time_s,
        }


@dataclass(frozen=True, slots=True)
class SwitchDetectionMetrics:
    """Aggregate switch latency with censored failures retained as events."""

    event_count: int
    detected_count: int
    censored_count: int
    detection_rate: float | None
    mean_detected_delay_s: float | None
    median_detected_delay_s: float | None
    events: tuple[SwitchDetectionEvent, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_only": True,
            "event_count": self.event_count,
            "detected_count": self.detected_count,
            "censored_count": self.censored_count,
            "detection_rate": self.detection_rate,
            "mean_detected_delay_s": self.mean_detected_delay_s,
            "median_detected_delay_s": self.median_detected_delay_s,
            "events": [event.to_dict() for event in self.events],
        }


def evaluate_switch_detection(
    true_modes_eval_only: Sequence[Hashable] | ArrayLike,
    mode_probabilities: ArrayLike,
    *,
    sample_time_s: float,
    belief_threshold: float,
    consecutive_steps: int,
    class_labels: Sequence[Hashable] | ArrayLike | None = None,
    episode_ids: Sequence[Hashable] | ArrayLike | None = None,
    time_s: ArrayLike | None = None,
) -> SwitchDetectionMetrics:
    """Apply the specified consecutive-belief switch-delay definition.

    Confirmation is timestamped at the last sample of the first qualifying
    run.  A switch not confirmed before the next true switch or episode end is
    returned as a right-censored event instead of being dropped.
    """

    probabilities = _probability_matrix(mode_probabilities)
    labels = _class_labels(class_labels, probabilities.shape[1])
    truth_index = _truth_indices(true_modes_eval_only, labels, probabilities.shape[0])
    truth_labels = tuple(labels[index] for index in truth_index.tolist())
    sample_time = _positive_float(sample_time_s, "sample_time_s")
    threshold = _unit_interval(belief_threshold, "belief_threshold", allow_zero=False)
    run_length_required = _positive_int(consecutive_steps, "consecutive_steps")
    episodes = _episode_vector(episode_ids, probabilities.shape[0])
    times = _sample_times(
        time_s,
        sample_count=probabilities.shape[0],
        episode_ids=episodes,
        sample_time_s=sample_time,
    )

    events: list[SwitchDetectionEvent] = []
    for episode_start, episode_end, episode_id in _episode_slices(episodes):
        switch_indices = [
            index
            for index in range(episode_start + 1, episode_end)
            if truth_index[index] != truth_index[index - 1]
        ]
        for ordinal, switch_index in enumerate(switch_indices):
            segment_end = (
                switch_indices[ordinal + 1]
                if ordinal + 1 < len(switch_indices)
                else episode_end
            )
            new_index = int(truth_index[switch_index])
            qualifying_run = 0
            detection_index: int | None = None
            for index in range(switch_index, segment_end):
                if probabilities[index, new_index] >= threshold:
                    qualifying_run += 1
                    if qualifying_run >= run_length_required:
                        detection_index = index
                        break
                else:
                    qualifying_run = 0
            censor_index = segment_end - 1
            censored = detection_index is None
            detection_time = (
                None if censored else float(times[detection_index])
            )
            delay = (
                None
                if censored
                else float(times[detection_index] - times[switch_index])
            )
            events.append(
                SwitchDetectionEvent(
                    episode_id=episode_id,
                    switch_index=switch_index,
                    switch_time_s=float(times[switch_index]),
                    previous_mode=truth_labels[switch_index - 1],
                    new_mode=truth_labels[switch_index],
                    detection_index=detection_index,
                    detection_time_s=detection_time,
                    delay_s=delay,
                    censored=censored,
                    censor_index=censor_index,
                    censoring_time_s=float(
                        times[censor_index] - times[switch_index]
                    ),
                )
            )
    delays = [event.delay_s for event in events if event.delay_s is not None]
    event_count = len(events)
    detected_count = len(delays)
    return SwitchDetectionMetrics(
        event_count=event_count,
        detected_count=detected_count,
        censored_count=event_count - detected_count,
        detection_rate=None if event_count == 0 else detected_count / event_count,
        mean_detected_delay_s=_optional_mean(delays),
        median_detected_delay_s=_optional_median(delays),
        events=tuple(events),
    )


@dataclass(frozen=True, slots=True)
class FalseAlarmEvent:
    """One maximal wrong-MAP run whose length strictly exceeds ``L_fa``."""

    episode_id: Hashable
    run_start_index: int
    trigger_index: int
    run_end_index: int
    wrong_run_length_steps: int
    wrong_run_duration_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_only": True,
            "episode_id": _jsonable(self.episode_id),
            "run_start_index": self.run_start_index,
            "trigger_index": self.trigger_index,
            "run_end_index": self.run_end_index,
            "wrong_run_length_steps": self.wrong_run_length_steps,
            "wrong_run_duration_s": self.wrong_run_duration_s,
        }


@dataclass(frozen=True, slots=True)
class FalseAlarmMetrics:
    """False-alarm counts and exposure-normalized rates on no-switch episodes."""

    event_count: int
    false_alarms_per_hour: float | None
    evaluated_episode_count: int
    excluded_switched_episode_count: int
    episodes_with_false_alarm: int
    episode_false_alarm_rate: float | None
    exposure_time_s: float
    load_step_window_count: int
    load_step_windows_with_false_alarm: int
    load_step_window_false_alarm_rate: float | None
    events: tuple[FalseAlarmEvent, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_only": True,
            "event_count": self.event_count,
            "false_alarms_per_hour": self.false_alarms_per_hour,
            "evaluated_episode_count": self.evaluated_episode_count,
            "excluded_switched_episode_count": self.excluded_switched_episode_count,
            "episodes_with_false_alarm": self.episodes_with_false_alarm,
            "episode_false_alarm_rate": self.episode_false_alarm_rate,
            "exposure_time_s": self.exposure_time_s,
            "load_step_window_count": self.load_step_window_count,
            "load_step_windows_with_false_alarm": self.load_step_windows_with_false_alarm,
            "load_step_window_false_alarm_rate": self.load_step_window_false_alarm_rate,
            "events": [event.to_dict() for event in self.events],
        }


def _validated_windows(
    windows: Sequence[tuple[int, int]],
    sample_count: int,
) -> tuple[tuple[int, int], ...]:
    validated: list[tuple[int, int]] = []
    for ordinal, raw in enumerate(windows):
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 2:
            raise TypeError(f"load_step_windows[{ordinal}] must be a (start, end) pair")
        start = _nonnegative_int(raw[0], f"load_step_windows[{ordinal}][0]")
        end = _nonnegative_int(raw[1], f"load_step_windows[{ordinal}][1]")
        if start > end:
            raise ValueError("load-step window start cannot exceed its end")
        if end >= sample_count:
            raise ValueError("load-step windows must lie inside the sample range")
        validated.append((start, end))
    return tuple(validated)


def evaluate_false_alarms(
    true_modes_eval_only: Sequence[Hashable] | ArrayLike,
    map_modes: Sequence[Hashable] | ArrayLike,
    *,
    sample_time_s: float,
    persistence_limit_steps: int,
    episode_ids: Sequence[Hashable] | ArrayLike | None = None,
    load_step_windows: Sequence[tuple[int, int]] = (),
) -> FalseAlarmMetrics:
    """Count wrong-MAP runs strictly longer than ``persistence_limit_steps``.

    Only episodes with constant truth are eligible, matching the specified
    no-switch false-alarm definition.  Exposure is ``sample_count * Ts``.  A
    load-step window is positive when a false-alarm trigger sample lies in its
    inclusive ``(start, end)`` bounds.
    """

    truth = _label_vector(true_modes_eval_only, "true_modes_eval_only")
    predicted = _label_vector(map_modes, "map_modes")
    if len(truth) != len(predicted):
        raise ValueError("true_modes_eval_only and map_modes must have equal lengths")
    sample_time = _positive_float(sample_time_s, "sample_time_s")
    persistence_limit = _nonnegative_int(
        persistence_limit_steps, "persistence_limit_steps"
    )
    episodes = _episode_vector(episode_ids, len(truth))
    windows = _validated_windows(load_step_windows, len(truth))

    eligible_by_sample = np.zeros(len(truth), dtype=np.bool_)
    events: list[FalseAlarmEvent] = []
    evaluated_episodes: list[Hashable] = []
    excluded_count = 0
    exposure_samples = 0
    for episode_start, episode_end, episode_id in _episode_slices(episodes):
        if any(truth[index] != truth[episode_start] for index in range(episode_start + 1, episode_end)):
            excluded_count += 1
            continue
        evaluated_episodes.append(episode_id)
        eligible_by_sample[episode_start:episode_end] = True
        exposure_samples += episode_end - episode_start
        index = episode_start
        while index < episode_end:
            if predicted[index] == truth[index]:
                index += 1
                continue
            run_start = index
            while index < episode_end and predicted[index] != truth[index]:
                index += 1
            run_end = index - 1
            run_length = run_end - run_start + 1
            if run_length > persistence_limit:
                events.append(
                    FalseAlarmEvent(
                        episode_id=episode_id,
                        run_start_index=run_start,
                        trigger_index=run_start + persistence_limit,
                        run_end_index=run_end,
                        wrong_run_length_steps=run_length,
                        wrong_run_duration_s=run_length * sample_time,
                    )
                )

    for start, end in windows:
        if not np.all(eligible_by_sample[start : end + 1]):
            raise ValueError("each load-step window must lie wholly in one no-switch episode")
        if episodes[start] != episodes[end]:
            raise ValueError("a load-step window cannot cross an episode boundary")
    episode_ids_with_alarm = {event.episode_id for event in events}
    windows_with_alarm = sum(
        any(start <= event.trigger_index <= end for event in events)
        for start, end in windows
    )
    exposure_time = exposure_samples * sample_time
    event_count = len(events)
    evaluated_count = len(evaluated_episodes)
    window_count = len(windows)
    return FalseAlarmMetrics(
        event_count=event_count,
        false_alarms_per_hour=(
            None if exposure_time <= 0.0 else event_count * 3600.0 / exposure_time
        ),
        evaluated_episode_count=evaluated_count,
        excluded_switched_episode_count=excluded_count,
        episodes_with_false_alarm=len(episode_ids_with_alarm),
        episode_false_alarm_rate=(
            None if evaluated_count == 0 else len(episode_ids_with_alarm) / evaluated_count
        ),
        exposure_time_s=exposure_time,
        load_step_window_count=window_count,
        load_step_windows_with_false_alarm=windows_with_alarm,
        load_step_window_false_alarm_rate=(
            None if window_count == 0 else windows_with_alarm / window_count
        ),
        events=tuple(events),
    )


def _binary_vector(values: ArrayLike, name: str) -> NDArray[np.bool_]:
    raw = np.asarray(values)
    if raw.ndim != 1 or raw.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional vector")
    if np.issubdtype(raw.dtype, np.bool_):
        return np.asarray(raw, dtype=np.bool_).copy()
    if np.issubdtype(raw.dtype, np.integer) and np.all((raw == 0) | (raw == 1)):
        return np.asarray(raw, dtype=np.bool_)
    raise TypeError(f"{name} must contain booleans or integer 0/1 values")


def _finite_score_vector(values: ArrayLike, name: str) -> FloatArray:
    raw = np.asarray(values)
    if np.iscomplexobj(raw):
        raise TypeError(f"{name} must be real-valued")
    scores = np.asarray(raw, dtype=np.float64)
    if scores.ndim != 1 or scores.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional vector")
    if not np.all(np.isfinite(scores)):
        raise ValueError(f"{name} must contain only finite values")
    return scores.copy()


@dataclass(frozen=True, slots=True)
class OODDetectionEvent:
    """One contiguous true-OOD interval and its detection outcome."""

    episode_id: Hashable
    onset_index: int
    onset_time_s: float
    interval_end_index: int
    detection_index: int | None
    detection_time_s: float | None
    delay_s: float | None
    censored: bool
    preexisting_active: bool
    censoring_time_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_only": True,
            "episode_id": _jsonable(self.episode_id),
            "onset_index": self.onset_index,
            "onset_time_s": self.onset_time_s,
            "interval_end_index": self.interval_end_index,
            "detection_index": self.detection_index,
            "detection_time_s": self.detection_time_s,
            "delay_s": self.delay_s,
            "censored": self.censored,
            "preexisting_active": self.preexisting_active,
            "censoring_time_s": self.censoring_time_s,
        }


@dataclass(frozen=True, slots=True)
class OODDetectionMetrics:
    """Ranking quality and event latency for OOD evaluation only."""

    auroc: float
    auprc: float
    event_count: int
    detected_count: int
    censored_count: int
    detection_rate: float | None
    mean_detected_delay_s: float | None
    median_detected_delay_s: float | None
    events: tuple[OODDetectionEvent, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_only": True,
            "auroc": self.auroc,
            "auprc": self.auprc,
            "event_count": self.event_count,
            "detected_count": self.detected_count,
            "censored_count": self.censored_count,
            "detection_rate": self.detection_rate,
            "mean_detected_delay_s": self.mean_detected_delay_s,
            "median_detected_delay_s": self.median_detected_delay_s,
            "events": [event.to_dict() for event in self.events],
        }


def evaluate_ood_detection(
    true_ood_eval_only: ArrayLike,
    ood_scores: ArrayLike,
    ood_active: ArrayLike,
    *,
    sample_time_s: float,
    episode_ids: Sequence[Hashable] | ArrayLike | None = None,
    higher_score_more_ood: bool = True,
    time_s: ArrayLike | None = None,
) -> OODDetectionMetrics:
    """Compute OOD AUROC/AUPRC and right-censored interval delays.

    ``ood_active`` is the already-hysteretic runtime decision.  Set
    ``higher_score_more_ood=False`` when passing conformal p-values, whose
    smaller values are more anomalous.
    """

    truth = _binary_vector(true_ood_eval_only, "true_ood_eval_only")
    active = _binary_vector(ood_active, "ood_active")
    scores = _finite_score_vector(ood_scores, "ood_scores")
    if truth.size != active.size or truth.size != scores.size:
        raise ValueError("true OOD, scores, and active decisions must have equal lengths")
    if not isinstance(higher_score_more_ood, (bool, np.bool_)):
        raise TypeError("higher_score_more_ood must be boolean")
    if np.unique(truth).size != 2:
        raise ValueError("OOD AUROC/AUPRC require both known and OOD samples")
    sample_time = _positive_float(sample_time_s, "sample_time_s")
    episodes = _episode_vector(episode_ids, truth.size)
    times = _sample_times(
        time_s,
        sample_count=truth.size,
        episode_ids=episodes,
        sample_time_s=sample_time,
    )
    ranking_scores = scores if bool(higher_score_more_ood) else -scores

    events: list[OODDetectionEvent] = []
    for episode_start, episode_end, episode_id in _episode_slices(episodes):
        index = episode_start
        while index < episode_end:
            if not truth[index]:
                index += 1
                continue
            onset = index
            while index < episode_end and truth[index]:
                index += 1
            interval_end = index - 1
            preexisting_active = bool(
                onset > episode_start and active[onset - 1]
            )
            previous_active = preexisting_active
            detection_index: int | None = None
            for candidate in range(onset, interval_end + 1):
                current_active = bool(active[candidate])
                if current_active and not previous_active:
                    detection_index = candidate
                    break
                previous_active = current_active
            censored = detection_index is None
            detection_time = (
                None if censored else float(times[detection_index])
            )
            delay = (
                None
                if censored
                else float(times[detection_index] - times[onset])
            )
            events.append(
                OODDetectionEvent(
                    episode_id=episode_id,
                    onset_index=onset,
                    onset_time_s=float(times[onset]),
                    interval_end_index=interval_end,
                    detection_index=detection_index,
                    detection_time_s=detection_time,
                    delay_s=delay,
                    censored=censored,
                    preexisting_active=preexisting_active,
                    censoring_time_s=float(
                        times[interval_end] - times[onset]
                    ),
                )
            )
    delays = [event.delay_s for event in events if event.delay_s is not None]
    event_count = len(events)
    detected_count = len(delays)
    return OODDetectionMetrics(
        auroc=float(roc_auc_score(truth.astype(np.int64), ranking_scores)),
        auprc=float(average_precision_score(truth.astype(np.int64), ranking_scores)),
        event_count=event_count,
        detected_count=detected_count,
        censored_count=event_count - detected_count,
        detection_rate=None if event_count == 0 else detected_count / event_count,
        mean_detected_delay_s=_optional_mean(delays),
        median_detected_delay_s=_optional_median(delays),
        events=tuple(events),
    )


__all__ = [
    "ClassificationMetrics",
    "FalseAlarmEvent",
    "FalseAlarmMetrics",
    "ModeProbabilityMetrics",
    "OODDetectionEvent",
    "OODDetectionMetrics",
    "ReliabilityBin",
    "SwitchDetectionEvent",
    "SwitchDetectionMetrics",
    "evaluate_classification",
    "evaluate_false_alarms",
    "evaluate_mode_probabilities",
    "evaluate_ood_detection",
    "evaluate_switch_detection",
]
