"""Closed-loop metrics computed at the physically appropriate sample rates.

Frequency integrals, extrema, RoCoF, and safety durations are evaluated from
the evaluator-only high-frequency truth trace.  Control effort, resource use,
fallback exposure, and solver statistics are evaluated from the control-rate
trace.  This separation prevents control sampling from hiding fast frequency
or RoCoF excursions.

Non-finite trace values are never silently filtered.  They set the NaN
catastrophe flag and make ``metrics_complete`` false.  Metrics preceding the
first non-finite value may still be returned as explicitly incomplete prefix
metrics, allowing a failed episode to remain useful without pretending that
it finished.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
import math
from numbers import Real
from typing import Any, ClassVar

import numpy as np
from numpy.typing import ArrayLike, NDArray


FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]

# Constraint audits compare values produced by several floating-point
# operations (notably command differences divided by the sample period).
# Permit only a small round-off envelope: eight binary64 epsilons relative to
# the configured, non-zero constraint.  This is about 1.8e-17 at a 0.01-pu
# limit and therefore does not relax the physical/protocol constraint.
_COMMAND_AUDIT_RELATIVE_ROUNDOFF = 8.0 * np.finfo(np.float64).eps


def _finite_scalar(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _positive(value: object, name: str) -> float:
    normalized = _finite_scalar(value, name)
    if normalized <= 0.0:
        raise ValueError(f"{name} must be strictly positive")
    return normalized


def _nonnegative(value: object, name: str) -> float:
    normalized = _finite_scalar(value, name)
    if normalized < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def _optional_finite(value: object | None, name: str) -> float | None:
    return None if value is None else _finite_scalar(value, name)


def _vector(values: ArrayLike, name: str, *, nonempty: bool = True) -> FloatArray:
    raw = np.asarray(values)
    if np.iscomplexobj(raw):
        raise TypeError(f"{name} must be real-valued")
    result = np.asarray(raw, dtype=np.float64)
    if result.ndim != 1 or (nonempty and result.size == 0):
        qualifier = "non-empty " if nonempty else ""
        raise ValueError(f"{name} must be a {qualifier}one-dimensional vector")
    result = result.copy()
    result.setflags(write=False)
    return result


def _time_vector(values: ArrayLike, name: str, *, minimum_size: int) -> FloatArray:
    result = _vector(values, name)
    if result.size < minimum_size:
        raise ValueError(f"{name} must contain at least {minimum_size} samples")
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must contain only finite values")
    if np.any(np.diff(result) <= 0.0):
        raise ValueError(f"{name} must be strictly increasing")
    return result


def _bool_vector(values: ArrayLike, name: str, expected_size: int) -> BoolArray:
    raw = np.asarray(values)
    if raw.shape != (expected_size,):
        raise ValueError(f"{name} must contain one value per control sample")
    if np.issubdtype(raw.dtype, np.bool_):
        result = np.asarray(raw, dtype=np.bool_).copy()
    elif np.issubdtype(raw.dtype, np.integer) and np.all((raw == 0) | (raw == 1)):
        result = np.asarray(raw, dtype=np.bool_)
    else:
        raise TypeError(f"{name} must contain booleans or integer 0/1 values")
    result.setflags(write=False)
    return result


def _text_vector(
    values: Sequence[object] | ArrayLike | None,
    name: str,
    expected_size: int,
    default: str,
) -> tuple[str, ...]:
    if values is None:
        return (default,) * expected_size
    raw = np.asarray(values, dtype=object)
    if raw.shape != (expected_size,):
        raise ValueError(f"{name} must contain one value per control sample")
    normalized: list[str] = []
    for item in raw.tolist():
        if hasattr(item, "value"):
            item = item.value
        text = str(item).strip()
        if not text:
            raise ValueError(f"{name} cannot contain empty values")
        normalized.append(text)
    return tuple(normalized)


def _readonly(values: FloatArray) -> FloatArray:
    copied = np.asarray(values, dtype=np.float64).copy()
    copied.setflags(write=False)
    return copied


def _point_value(point: Mapping[str, Any] | object, name: str) -> Any:
    if isinstance(point, Mapping):
        if name not in point:
            raise KeyError(name)
        return point[name]
    if not hasattr(point, name):
        raise AttributeError(name)
    return getattr(point, name)


@dataclass(frozen=True, slots=True)
class HighFrequencyTruthTrace:
    """Evaluator-only truth samples; exactly one frequency representation is used."""

    time_s: ArrayLike
    omega_true_pu: ArrayLike | None = None
    delta_frequency_hz: ArrayLike | None = None
    rocof_true_hz_per_s: ArrayLike | None = None

    def __post_init__(self) -> None:
        time = _time_vector(self.time_s, "time_s", minimum_size=2)
        supplied = (self.omega_true_pu is not None, self.delta_frequency_hz is not None)
        if sum(supplied) != 1:
            raise ValueError(
                "exactly one of omega_true_pu and delta_frequency_hz must be supplied"
            )
        object.__setattr__(self, "time_s", time)
        for name in ("omega_true_pu", "delta_frequency_hz", "rocof_true_hz_per_s"):
            raw = getattr(self, name)
            if raw is None:
                continue
            values = _vector(raw, name)
            if values.shape != time.shape:
                raise ValueError(f"{name} must contain one value per truth time")
            object.__setattr__(self, name, values)

    @classmethod
    def from_points(
        cls,
        points: Sequence[Mapping[str, Any] | object],
        *,
        time_field: str = "time_s",
        omega_field: str = "omega_true_pu",
        rocof_field: str = "rocof_true_hz_per_s",
        duplicate_tolerance: float = 1e-12,
    ) -> "HighFrequencyTruthTrace":
        """Build from simulator points, coalescing identical step-boundary times.

        Adjacent control steps normally repeat their shared boundary point.
        Equal or microscopically regressed times are accepted only when their
        truth values agree within ``duplicate_tolerance``; disagreement is an
        evaluator data-integrity error, not something to average away.  A
        strictly later point is retained even within that tolerance because it
        can be the right side of a real event discontinuity.  Exact RoCoF is
        optional for compatibility with externally supplied traces, but its
        presence must be consistent across all points.
        """

        if not points:
            raise ValueError("points must not be empty")
        tolerance = _nonnegative(duplicate_tolerance, "duplicate_tolerance")
        times: list[float] = []
        omega: list[float] = []
        rocof: list[float] = []
        has_exact_rocof: bool | None = None
        for ordinal, point in enumerate(points):
            try:
                point_time = float(_point_value(point, time_field))
                point_omega = float(_point_value(point, omega_field))
                point_has_rocof = (
                    rocof_field in point
                    if isinstance(point, Mapping)
                    else hasattr(point, rocof_field)
                )
                point_rocof = (
                    float(_point_value(point, rocof_field))
                    if point_has_rocof
                    else None
                )
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid truth point at index {ordinal}: {exc}") from exc
            if has_exact_rocof is None:
                has_exact_rocof = point_has_rocof
            elif point_has_rocof != has_exact_rocof:
                raise ValueError(
                    "truth points must consistently include or omit exact RoCoF"
                )
            if times and point_time < times[-1] - tolerance:
                raise ValueError("truth points must be in non-decreasing time order")
            if times and point_time <= times[-1]:
                if not (
                    (math.isnan(point_omega) and math.isnan(omega[-1]))
                    or math.isclose(point_omega, omega[-1], rel_tol=0.0, abs_tol=tolerance)
                ):
                    raise ValueError("duplicate truth times contain inconsistent values")
                if point_rocof is not None and not (
                    (math.isnan(point_rocof) and math.isnan(rocof[-1]))
                    or math.isclose(
                        point_rocof,
                        rocof[-1],
                        rel_tol=0.0,
                        abs_tol=tolerance,
                    )
                ):
                    raise ValueError(
                        "duplicate truth times contain inconsistent exact RoCoF"
                    )
                continue
            times.append(point_time)
            omega.append(point_omega)
            if point_rocof is not None:
                rocof.append(point_rocof)
        return cls(
            time_s=times,
            omega_true_pu=omega,
            rocof_true_hz_per_s=rocof if has_exact_rocof else None,
        )

    def delta_hz(self, nominal_frequency_hz: float) -> FloatArray:
        """Return frequency deviation without exposing truth to a controller."""

        nominal = _positive(nominal_frequency_hz, "nominal_frequency_hz")
        if self.delta_frequency_hz is not None:
            return _readonly(np.asarray(self.delta_frequency_hz, dtype=np.float64))
        assert self.omega_true_pu is not None
        return _readonly(nominal * np.asarray(self.omega_true_pu, dtype=np.float64))


@dataclass(frozen=True, slots=True)
class ControlRateTrace:
    """Commands, realized IBR power, controller state, and solver audit samples."""

    time_s: ArrayLike
    u_sg_pu: ArrayLike
    u_ibr_pu: ArrayLike
    p_ibr_pu: ArrayLike
    controller_state: Sequence[object] | ArrayLike | None = None
    solver_outcome: Sequence[object] | ArrayLike | None = None
    solver_status: Sequence[object] | ArrayLike | None = None
    solve_time_s: ArrayLike | None = None
    max_freq_slack_hz: ArrayLike | None = None
    max_rocof_slack_hz_s: ArrayLike | None = None
    max_power_slack_pu: ArrayLike | None = None
    diagnostic_alarm_active: ArrayLike | None = None
    ood_alarm_active: ArrayLike | None = None
    u_sg_initial_pu: float | None = None
    u_ibr_initial_pu: float | None = None
    responsibility_event_time_s: float | None = None

    _NUMERIC_OPTIONALS: ClassVar[tuple[tuple[str, float], ...]] = (
        ("solve_time_s", 0.0),
        ("max_freq_slack_hz", 0.0),
        ("max_rocof_slack_hz_s", 0.0),
        ("max_power_slack_pu", 0.0),
    )

    def __post_init__(self) -> None:
        time = _time_vector(self.time_s, "time_s", minimum_size=1)
        size = time.size
        object.__setattr__(self, "time_s", time)
        for name in ("u_sg_pu", "u_ibr_pu", "p_ibr_pu"):
            values = _vector(getattr(self, name), name)
            if values.shape != time.shape:
                raise ValueError(f"{name} must contain one value per control time")
            object.__setattr__(self, name, values)
        object.__setattr__(
            self,
            "controller_state",
            _text_vector(self.controller_state, "controller_state", size, "UNSPECIFIED"),
        )
        object.__setattr__(
            self,
            "solver_outcome",
            _text_vector(self.solver_outcome, "solver_outcome", size, "not_run"),
        )
        object.__setattr__(
            self,
            "solver_status",
            _text_vector(self.solver_status, "solver_status", size, "not_run"),
        )
        for name, default in self._NUMERIC_OPTIONALS:
            raw = getattr(self, name)
            values = np.full(size, default, dtype=np.float64) if raw is None else _vector(raw, name)
            if values.shape != time.shape:
                raise ValueError(f"{name} must contain one value per control time")
            object.__setattr__(self, name, _readonly(values))
        for name in ("diagnostic_alarm_active", "ood_alarm_active"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, _bool_vector(raw, name, size))
        for name in ("u_sg_initial_pu", "u_ibr_initial_pu", "responsibility_event_time_s"):
            object.__setattr__(self, name, _optional_finite(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class DetectionWindow:
    """One truth-known event interval used only by the evaluation layer."""

    event_id: str
    onset_time_s: float
    end_time_s: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("event_id must be a non-empty string")
        object.__setattr__(self, "event_id", self.event_id.strip())
        onset = _finite_scalar(self.onset_time_s, "onset_time_s")
        end = _optional_finite(self.end_time_s, "end_time_s")
        if end is not None and end < onset:
            raise ValueError("end_time_s cannot precede onset_time_s")
        object.__setattr__(self, "onset_time_s", onset)
        object.__setattr__(self, "end_time_s", end)


@dataclass(frozen=True, slots=True)
class DetectionEventResult:
    """Detected or explicitly right-censored event latency."""

    event_id: str
    onset_time_s: float
    interval_end_time_s: float
    detected: bool
    detection_time_s: float | None
    delay_s: float | None
    censored: bool
    censoring_time_s: float
    preexisting_alarm: bool

    def to_dict(self) -> dict[str, Any]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


@dataclass(frozen=True, slots=True)
class DetectionDelaySummary:
    """Event-level delay summary that retains all censored events."""

    event_count: int
    detected_count: int
    censored_count: int
    detection_rate: float | None
    mean_detected_delay_s: float | None
    median_detected_delay_s: float | None
    mean_censoring_time_s: float | None
    events: tuple[DetectionEventResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_count": self.event_count,
            "detected_count": self.detected_count,
            "censored_count": self.censored_count,
            "detection_rate": self.detection_rate,
            "mean_detected_delay_s": self.mean_detected_delay_s,
            "median_detected_delay_s": self.median_detected_delay_s,
            "mean_censoring_time_s": self.mean_censoring_time_s,
            "events": [event.to_dict() for event in self.events],
        }


def evaluate_detection_delay(
    time_s: ArrayLike,
    alarm_active: ArrayLike,
    event_windows: Sequence[DetectionWindow],
) -> DetectionDelaySummary:
    """Evaluate rising-edge latency and right censoring for known event windows.

    An alarm already active immediately before an event onset earns no zero
    delay.  It must first clear and then produce a new rising edge inside the
    event window.  This prevents a stale or permanently active alarm from
    receiving artificial detection credit.
    """

    times = _time_vector(time_s, "time_s", minimum_size=1)
    active = _bool_vector(alarm_active, "alarm_active", times.size)
    results: list[DetectionEventResult] = []
    for event in event_windows:
        if event.onset_time_s < times[0] or event.onset_time_s > times[-1]:
            raise ValueError(f"event {event.event_id!r} onset lies outside the trace")
        interval_end = times[-1] if event.end_time_s is None else min(event.end_time_s, times[-1])
        start_index = int(np.searchsorted(times, event.onset_time_s, side="left"))
        end_exclusive = int(np.searchsorted(times, interval_end, side="right"))
        previous_active = bool(active[start_index - 1]) if start_index > 0 else False
        preexisting = previous_active
        detection_index: int | None = None
        for index in range(start_index, end_exclusive):
            current = bool(active[index])
            if current and not previous_active:
                detection_index = index
                break
            previous_active = current
        detected = detection_index is not None
        detection_time = None if detection_index is None else float(times[detection_index])
        delay = None if detection_time is None else detection_time - event.onset_time_s
        results.append(
            DetectionEventResult(
                event_id=event.event_id,
                onset_time_s=event.onset_time_s,
                interval_end_time_s=float(interval_end),
                detected=detected,
                detection_time_s=detection_time,
                delay_s=delay,
                censored=not detected,
                censoring_time_s=float(interval_end - event.onset_time_s),
                preexisting_alarm=preexisting,
            )
        )
    delays = [event.delay_s for event in results if event.delay_s is not None]
    censoring = [event.censoring_time_s for event in results if event.censored]
    count = len(results)
    detected_count = len(delays)
    return DetectionDelaySummary(
        event_count=count,
        detected_count=detected_count,
        censored_count=count - detected_count,
        detection_rate=None if count == 0 else detected_count / count,
        mean_detected_delay_s=None if not delays else float(np.mean(delays)),
        median_detected_delay_s=None if not delays else float(np.median(delays)),
        mean_censoring_time_s=None if not censoring else float(np.mean(censoring)),
        events=tuple(results),
    )


@dataclass(frozen=True, slots=True)
class ClosedLoopMetricConfig:
    """Thresholds and unambiguous conventions for closed-loop evaluation."""

    nominal_frequency_hz: float = 50.0
    frequency_limit_hz: float = 0.5
    rocof_limit_hz_per_s: float = 1.0
    safety_frequency_limit_hz: float = 2.0
    settling_band_hz: float = 0.05
    sg_command_min_pu: float | None = None
    sg_command_max_pu: float | None = None
    sg_slew_limit_pu_per_s: float | None = None
    ibr_command_min_pu: float | None = None
    ibr_command_max_pu: float | None = None
    ibr_slew_limit_pu_per_s: float | None = None
    command_sample_period_s: float | None = None
    command_violation_persistence_s: float = 0.2
    responsibility_sg_share: float = 0.8
    responsibility_hold_s: float = 0.1
    fallback_states: tuple[str, ...] = ("FALLBACK",)

    def __post_init__(self) -> None:
        for name in (
            "nominal_frequency_hz",
            "frequency_limit_hz",
            "rocof_limit_hz_per_s",
            "safety_frequency_limit_hz",
            "settling_band_hz",
        ):
            object.__setattr__(self, name, _positive(getattr(self, name), name))
        if self.safety_frequency_limit_hz < self.frequency_limit_hz:
            raise ValueError("safety_frequency_limit_hz cannot be below frequency_limit_hz")
        for name in (
            "sg_command_min_pu",
            "sg_command_max_pu",
            "ibr_command_min_pu",
            "ibr_command_max_pu",
        ):
            object.__setattr__(self, name, _optional_finite(getattr(self, name), name))
        if (
            self.sg_command_min_pu is not None
            and self.sg_command_max_pu is not None
            and self.sg_command_min_pu > self.sg_command_max_pu
        ):
            raise ValueError("SG command minimum cannot exceed maximum")
        if (
            self.ibr_command_min_pu is not None
            and self.ibr_command_max_pu is not None
            and self.ibr_command_min_pu > self.ibr_command_max_pu
        ):
            raise ValueError("IBR command minimum cannot exceed maximum")
        for name in ("sg_slew_limit_pu_per_s", "ibr_slew_limit_pu_per_s"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _positive(value, name))
        if self.command_sample_period_s is not None:
            object.__setattr__(
                self,
                "command_sample_period_s",
                _positive(self.command_sample_period_s, "command_sample_period_s"),
            )
        if (
            self.sg_slew_limit_pu_per_s is not None
            or self.ibr_slew_limit_pu_per_s is not None
        ) and self.command_sample_period_s is None:
            raise ValueError(
                "command_sample_period_s is required when a command slew limit is configured"
            )
        object.__setattr__(
            self,
            "command_violation_persistence_s",
            _nonnegative(
                self.command_violation_persistence_s,
                "command_violation_persistence_s",
            ),
        )
        share = _finite_scalar(self.responsibility_sg_share, "responsibility_sg_share")
        if not 0.0 < share <= 1.0:
            raise ValueError("responsibility_sg_share must lie in (0, 1]")
        object.__setattr__(self, "responsibility_sg_share", share)
        object.__setattr__(
            self,
            "responsibility_hold_s",
            _nonnegative(self.responsibility_hold_s, "responsibility_hold_s"),
        )
        states = tuple(str(value).strip().upper() for value in self.fallback_states)
        if not states or any(not value for value in states):
            raise ValueError("fallback_states must contain non-empty names")
        object.__setattr__(self, "fallback_states", states)


@dataclass(frozen=True, slots=True)
class ClosedLoopMetrics:
    """Flat episode metrics plus event-level detection audit records."""

    metrics_complete: bool
    truth_sample_count: int
    control_sample_count: int
    evaluated_truth_end_time_s: float | None

    max_abs_freq_hz: float | None
    nadir_delta_hz: float | None
    zenith_delta_hz: float | None
    nadir_hz: float | None
    zenith_hz: float | None
    max_abs_rocof_hz_s: float | None
    freq_iae: float | None
    freq_ise: float | None
    settling_time_s: float | None
    settling_censored: bool | None
    settling_censoring_time_s: float | None
    freq_violation_duration_s: float | None
    rocof_violation_duration_s: float | None
    constraint_violation_count: int | None
    violation_duration_s: float | None

    sg_mileage: float | None
    ibr_mileage: float | None
    ibr_tracking_error: float | None
    sg_abs_energy_pu_s: float | None
    ibr_abs_energy_pu_s: float | None
    peak_abs_sg_command_pu: float | None
    peak_abs_ibr_command_pu: float | None
    responsibility_transfer_time_s: float | None
    responsibility_transfer_censored: bool | None
    responsibility_transfer_censoring_time_s: float | None
    fallback_duration_s: float | None
    sg_command_violation_count: int | None
    sg_command_violation_duration_s: float | None
    max_contiguous_sg_command_violation_s: float | None
    ibr_command_violation_count: int | None
    ibr_command_violation_duration_s: float | None
    max_contiguous_ibr_command_violation_s: float | None

    solver_attempt_count: int
    solve_time_mean_s: float | None
    solve_time_p95_s: float | None
    solve_time_max_s: float | None
    solver_fail_count: int
    solver_timeout_count: int
    solver_timeout_rate: float | None
    solver_infeasible_count: int
    solver_infeasible_rate: float | None
    solver_inaccurate_count: int
    solver_inaccurate_rate: float | None
    max_freq_slack_hz: float | None
    max_rocof_slack_hz_s: float | None
    max_power_slack_pu: float | None

    detection_delay_s: float | None
    detection_event_count: int
    detection_censored_count: int
    detection_censoring_time_s: float | None
    ood_detected: bool | None
    ood_detection_delay_s: float | None
    ood_detection_event_count: int
    ood_detection_censored_count: int
    ood_detection_censoring_time_s: float | None
    diagnostic_risk_iae: float | None

    catastrophic_failure: bool
    catastrophic_safety_boundary: bool
    catastrophic_solver_without_fallback: bool
    catastrophic_nan_detected: bool
    catastrophic_persistent_command_violation: bool
    catastrophic_not_recovered: bool

    diagnostic_detection_events: tuple[DetectionEventResult, ...] = ()
    ood_detection_events: tuple[DetectionEventResult, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name.endswith("_events"):
                result[item.name] = [event.to_dict() for event in value]
            elif isinstance(value, np.generic):
                result[item.name] = value.item()
            else:
                result[item.name] = value
        return result


def _finite_prefix_length(*arrays: FloatArray) -> int:
    if not arrays:
        return 0
    size = arrays[0].size
    mask = np.ones(size, dtype=np.bool_)
    for array in arrays:
        if array.size != size:
            raise ValueError("internal metric arrays must have equal lengths")
        mask &= np.isfinite(array)
    invalid = np.flatnonzero(~mask)
    return size if invalid.size == 0 else int(invalid[0])


def _duration_above_abs_limit(time: FloatArray, signal: FloatArray, limit: float) -> float:
    duration = 0.0
    for index, step in enumerate(np.diff(time)):
        first = float(signal[index])
        second = float(signal[index + 1])
        fractions = [0.0, 1.0]
        slope = second - first
        if slope != 0.0:
            for boundary in (-limit, limit):
                fraction = (boundary - first) / slope
                if 0.0 < fraction < 1.0:
                    fractions.append(float(fraction))
        fractions = sorted(set(fractions))
        for left, right in zip(fractions[:-1], fractions[1:], strict=True):
            midpoint = 0.5 * (left + right)
            value = first + midpoint * slope
            if abs(value) > limit:
                duration += (right - left) * float(step)
    return float(duration)


def _duration_union_abs_limits(
    time: FloatArray,
    signals_and_limits: Sequence[tuple[FloatArray, float]],
) -> float:
    duration = 0.0
    for index, step in enumerate(np.diff(time)):
        fractions = [0.0, 1.0]
        segments: list[tuple[float, float, float]] = []
        for signal, limit in signals_and_limits:
            first = float(signal[index])
            slope = float(signal[index + 1] - signal[index])
            segments.append((first, slope, limit))
            if slope != 0.0:
                for boundary in (-limit, limit):
                    fraction = (boundary - first) / slope
                    if 0.0 < fraction < 1.0:
                        fractions.append(float(fraction))
        fractions = sorted(set(fractions))
        for left, right in zip(fractions[:-1], fractions[1:], strict=True):
            midpoint = 0.5 * (left + right)
            if any(abs(first + midpoint * slope) > limit for first, slope, limit in segments):
                duration += (right - left) * float(step)
    return float(duration)


def _run_count(mask: BoolArray) -> int:
    if mask.size == 0:
        return 0
    return int(bool(mask[0])) + int(np.count_nonzero(mask[1:] & ~mask[:-1]))


def _zoh_duration(time: FloatArray, mask: BoolArray) -> float:
    if time.size < 2:
        return 0.0
    return float(np.sum(np.diff(time) * mask[:-1]))


def _max_zoh_run_duration(time: FloatArray, mask: BoolArray) -> float:
    if time.size < 2:
        return 0.0
    longest = 0.0
    current = 0.0
    for index, step in enumerate(np.diff(time)):
        if bool(mask[index]):
            current += float(step)
            longest = max(longest, current)
        else:
            current = 0.0
    return longest


def _settling(
    time: FloatArray,
    signal: FloatArray,
    band: float,
    *,
    trace_complete: bool,
) -> tuple[float | None, bool, float]:
    censoring = float(time[-1] - time[0])
    if not trace_complete or abs(float(signal[-1])) > band:
        return None, True, censoring
    outside = np.flatnonzero(np.abs(signal) > band)
    if outside.size == 0:
        return 0.0, False, censoring
    last_outside = int(outside[-1])
    if last_outside >= signal.size - 1:
        return None, True, censoring
    first = float(signal[last_outside])
    second = float(signal[last_outside + 1])
    target = math.copysign(band, first)
    fraction = 0.0 if second == first else (target - first) / (second - first)
    fraction = min(1.0, max(0.0, fraction))
    crossing = float(time[last_outside] + fraction * (time[last_outside + 1] - time[last_outside]))
    return crossing - float(time[0]), False, censoring


def _trace_from_reference(
    time: FloatArray,
    signal: FloatArray,
    reference_time_s: float,
) -> tuple[FloatArray, FloatArray] | None:
    """Clip a finite trace at an explicit event reference, interpolating once."""

    if reference_time_s > time[-1]:
        return None
    if math.isclose(reference_time_s, float(time[0]), rel_tol=0.0, abs_tol=1e-12):
        return time, signal
    after = time > reference_time_s
    clipped_time = np.concatenate(
        ([reference_time_s], np.asarray(time[after], dtype=np.float64))
    )
    clipped_signal = np.concatenate(
        ([float(np.interp(reference_time_s, time, signal))], signal[after])
    )
    return clipped_time, clipped_signal


def _mileage(values: FloatArray, initial: float | None) -> float:
    differences = np.diff(values)
    total = float(np.sum(np.abs(differences)))
    if initial is not None and values.size:
        total += abs(float(values[0]) - initial)
    return total


def _left_integral(time: FloatArray, values: FloatArray) -> float:
    if time.size < 2:
        return 0.0
    return float(np.sum(np.diff(time) * values[:-1]))


def _responsibility_transfer(
    time: FloatArray,
    u_sg: FloatArray,
    u_ibr: FloatArray,
    event_time: float | None,
    share_threshold: float,
    hold_s: float,
    *,
    trace_complete: bool,
) -> tuple[float | None, bool | None, float | None]:
    if event_time is None:
        return None, None, None
    if event_time < time[0] or event_time > time[-1]:
        raise ValueError("responsibility_event_time_s lies outside the control trace")
    denominator = np.abs(u_sg) + np.abs(u_ibr)
    share = np.divide(
        np.abs(u_sg),
        denominator,
        out=np.zeros_like(denominator),
        where=denominator > 0.0,
    )
    responsible = share >= share_threshold
    start = int(np.searchsorted(time, event_time, side="left"))
    for candidate in range(start, time.size):
        if not responsible[candidate]:
            continue
        candidate_time = max(event_time, float(time[candidate]))
        end_required = candidate_time + hold_s
        if end_required > time[-1]:
            continue
        end_index = int(np.searchsorted(time, end_required, side="left"))
        if np.all(responsible[candidate : end_index + 1]):
            return candidate_time - event_time, False, float(time[-1] - event_time)
    return None, True, float(time[-1] - event_time)


def _command_violation_mask(
    time: FloatArray,
    command: FloatArray,
    *,
    command_min_pu: float | None,
    command_max_pu: float | None,
    slew_limit_pu_per_s: float | None,
    initial_command_pu: float | None,
    sample_period_s: float | None,
    resource_name: str,
) -> BoolArray:
    mask = np.zeros(command.size, dtype=np.bool_)
    if command_min_pu is not None:
        tolerance = _COMMAND_AUDIT_RELATIVE_ROUNDOFF * abs(command_min_pu)
        mask |= command < command_min_pu - tolerance
    if command_max_pu is not None:
        tolerance = _COMMAND_AUDIT_RELATIVE_ROUNDOFF * abs(command_max_pu)
        mask |= command > command_max_pu + tolerance
    if slew_limit_pu_per_s is not None:
        if initial_command_pu is None:
            raise ValueError(
                f"{resource_name} initial command is required for complete slew audit"
            )
        if sample_period_s is None:
            raise ValueError("command sample period is required for complete slew audit")
        if command.size:
            initial_slew = abs(float(command[0]) - initial_command_pu) / sample_period_s
            tolerance = _COMMAND_AUDIT_RELATIVE_ROUNDOFF * abs(slew_limit_pu_per_s)
            mask[0] |= initial_slew > slew_limit_pu_per_s + tolerance
    if slew_limit_pu_per_s is not None and command.size >= 2:
        slew = np.abs(np.diff(command) / np.diff(time))
        tolerance = _COMMAND_AUDIT_RELATIVE_ROUNDOFF * abs(slew_limit_pu_per_s)
        mask[1:] |= slew > slew_limit_pu_per_s + tolerance
    return mask


def _solver_metrics(control: ControlRateTrace) -> dict[str, Any]:
    outcomes = np.asarray([value.lower() for value in control.solver_outcome], dtype=object)
    statuses = np.asarray([value.lower() for value in control.solver_status], dtype=object)
    attempted = ~np.isin(outcomes, ("not_run", "skipped", "none"))
    success = outcomes == "success"
    timeout = attempted & ((outcomes == "timeout") | (statuses == "timeout"))
    infeasible = attempted & (
        (outcomes == "infeasible") | np.char.startswith(statuses.astype(str), "infeasible")
    )
    inaccurate = attempted & (
        (outcomes == "inaccurate") | (statuses == "optimal_inaccurate")
    )
    failed = attempted & ~success
    attempt_count = int(np.count_nonzero(attempted))
    solve_times = np.asarray(control.solve_time_s, dtype=np.float64)[attempted]
    finite_times = solve_times[np.isfinite(solve_times)]

    def rate(mask: BoolArray) -> float | None:
        return None if attempt_count == 0 else float(np.count_nonzero(mask) / attempt_count)

    def maximum(name: str) -> float | None:
        values = np.asarray(getattr(control, name), dtype=np.float64)[attempted]
        finite = values[np.isfinite(values)]
        return None if finite.size == 0 else float(np.max(finite))

    return {
        "attempted": attempted,
        "failed": failed,
        "solver_attempt_count": attempt_count,
        "solve_time_mean_s": None if finite_times.size == 0 else float(np.mean(finite_times)),
        "solve_time_p95_s": None if finite_times.size == 0 else float(np.quantile(finite_times, 0.95)),
        "solve_time_max_s": None if finite_times.size == 0 else float(np.max(finite_times)),
        "solver_fail_count": int(np.count_nonzero(failed)),
        "solver_timeout_count": int(np.count_nonzero(timeout)),
        "solver_timeout_rate": rate(timeout),
        "solver_infeasible_count": int(np.count_nonzero(infeasible)),
        "solver_infeasible_rate": rate(infeasible),
        "solver_inaccurate_count": int(np.count_nonzero(inaccurate)),
        "solver_inaccurate_rate": rate(inaccurate),
        "max_freq_slack_hz": maximum("max_freq_slack_hz"),
        "max_rocof_slack_hz_s": maximum("max_rocof_slack_hz_s"),
        "max_power_slack_pu": maximum("max_power_slack_pu"),
    }


def _is_fallback_state(state: str, configured_states: tuple[str, ...]) -> bool:
    """Recognize the proposed state and method-prefixed baseline wrappers."""

    normalized = state.strip().upper()
    return normalized in configured_states or normalized.endswith("_FALLBACK")


def _integral_abs_between(
    time: FloatArray,
    signal: FloatArray,
    start: float,
    end: float,
) -> float:
    lower = max(float(time[0]), start)
    upper = min(float(time[-1]), end)
    if upper <= lower:
        return 0.0
    inside = (time > lower) & (time < upper)
    clipped_time = np.concatenate(([lower], time[inside], [upper]))
    clipped_signal = np.interp(clipped_time, time, signal)
    return float(np.trapezoid(np.abs(clipped_signal), clipped_time))


def compute_closed_loop_metrics(
    truth: HighFrequencyTruthTrace,
    control: ControlRateTrace,
    config: ClosedLoopMetricConfig,
    *,
    run_completed: bool,
    settling_reference_time_s: float | None = None,
    diagnostic_event_windows: Sequence[DetectionWindow] = (),
    ood_event_windows: Sequence[DetectionWindow] = (),
) -> ClosedLoopMetrics:
    """Compute one episode's auditable closed-loop metrics.

    Censored delays are not imputed.  Their numeric delay remains ``None`` and
    their observed exposure is reported in the corresponding censoring field.
    Diagnostic-risk IAE integrates to detection for detected events and to the
    censoring boundary otherwise, making a censored value an explicit lower
    bound rather than an invented detection time.
    """

    if not isinstance(run_completed, (bool, np.bool_)):
        raise TypeError("run_completed must be boolean")
    settling_reference = (
        float(truth.time_s[0])
        if settling_reference_time_s is None
        else _finite_scalar(settling_reference_time_s, "settling_reference_time_s")
    )
    if settling_reference < truth.time_s[0]:
        raise ValueError("settling_reference_time_s cannot precede the truth trace")
    if settling_reference > truth.time_s[-1] and bool(run_completed):
        raise ValueError(
            "a completed run requires settling_reference_time_s inside the truth trace"
        )
    delta_all = truth.delta_hz(config.nominal_frequency_hz)
    truth_arrays = [delta_all]
    if truth.rocof_true_hz_per_s is not None:
        truth_arrays.append(np.asarray(truth.rocof_true_hz_per_s, dtype=np.float64))
    truth_prefix = _finite_prefix_length(*truth_arrays)

    control_core = (
        np.asarray(control.u_sg_pu, dtype=np.float64),
        np.asarray(control.u_ibr_pu, dtype=np.float64),
        np.asarray(control.p_ibr_pu, dtype=np.float64),
    )
    control_prefix = _finite_prefix_length(*control_core)
    all_numeric_control = [*control_core]
    all_numeric_control.extend(
        np.asarray(getattr(control, name), dtype=np.float64)
        for name, _ in control._NUMERIC_OPTIONALS
    )
    nan_detected = truth_prefix != delta_all.size or any(
        not np.all(np.isfinite(values)) for values in all_numeric_control
    )
    metrics_complete = bool(
        run_completed
        and not nan_detected
        and truth_prefix == delta_all.size
        and control_prefix == control.time_s.size
    )

    frequency: dict[str, Any] = {
        "max_abs_freq_hz": None,
        "nadir_delta_hz": None,
        "zenith_delta_hz": None,
        "nadir_hz": None,
        "zenith_hz": None,
        "max_abs_rocof_hz_s": None,
        "freq_iae": None,
        "freq_ise": None,
        "settling_time_s": None,
        "settling_censored": True,
        "settling_censoring_time_s": None,
        "freq_violation_duration_s": None,
        "rocof_violation_duration_s": None,
        "constraint_violation_count": None,
        "violation_duration_s": None,
    }
    rocof = np.asarray([], dtype=np.float64)
    truth_time = np.asarray(truth.time_s, dtype=np.float64)[:truth_prefix]
    delta = np.asarray(delta_all, dtype=np.float64)[:truth_prefix]
    if truth_prefix >= 2:
        if truth.rocof_true_hz_per_s is None:
            edge_order = 2 if truth_prefix >= 3 else 1
            rocof = np.gradient(delta, truth_time, edge_order=edge_order)
        else:
            rocof = np.asarray(truth.rocof_true_hz_per_s, dtype=np.float64)[:truth_prefix]
        settling_trace = _trace_from_reference(
            truth_time,
            delta,
            settling_reference,
        )
        if settling_trace is None:
            settling_time, settling_censored, settling_exposure = None, True, 0.0
        else:
            settling_time, settling_censored, settling_exposure = _settling(
                settling_trace[0],
                settling_trace[1],
                config.settling_band_hz,
                trace_complete=metrics_complete,
            )
        freq_violation = np.abs(delta) > config.frequency_limit_hz
        rocof_violation = np.abs(rocof) > config.rocof_limit_hz_per_s
        frequency.update(
            max_abs_freq_hz=float(np.max(np.abs(delta))),
            nadir_delta_hz=float(np.min(delta)),
            zenith_delta_hz=float(np.max(delta)),
            nadir_hz=float(config.nominal_frequency_hz + np.min(delta)),
            zenith_hz=float(config.nominal_frequency_hz + np.max(delta)),
            max_abs_rocof_hz_s=float(np.max(np.abs(rocof))),
            freq_iae=float(np.trapezoid(np.abs(delta), truth_time)),
            freq_ise=float(np.trapezoid(delta * delta, truth_time)),
            settling_time_s=settling_time,
            settling_censored=settling_censored,
            settling_censoring_time_s=settling_exposure,
            freq_violation_duration_s=_duration_above_abs_limit(
                truth_time, delta, config.frequency_limit_hz
            ),
            rocof_violation_duration_s=_duration_above_abs_limit(
                truth_time, rocof, config.rocof_limit_hz_per_s
            ),
            constraint_violation_count=_run_count(freq_violation | rocof_violation),
            violation_duration_s=_duration_union_abs_limits(
                truth_time,
                (
                    (delta, config.frequency_limit_hz),
                    (rocof, config.rocof_limit_hz_per_s),
                ),
            ),
        )
    elif truth_prefix == 1:
        frequency.update(
            max_abs_freq_hz=float(abs(delta[0])),
            nadir_delta_hz=float(delta[0]),
            zenith_delta_hz=float(delta[0]),
            nadir_hz=float(config.nominal_frequency_hz + delta[0]),
            zenith_hz=float(config.nominal_frequency_hz + delta[0]),
            settling_censoring_time_s=0.0,
        )

    control_metrics: dict[str, Any] = {
        "sg_mileage": None,
        "ibr_mileage": None,
        "ibr_tracking_error": None,
        "sg_abs_energy_pu_s": None,
        "ibr_abs_energy_pu_s": None,
        "peak_abs_sg_command_pu": None,
        "peak_abs_ibr_command_pu": None,
        "responsibility_transfer_time_s": None,
        "responsibility_transfer_censored": None,
        "responsibility_transfer_censoring_time_s": None,
        "fallback_duration_s": None,
        "sg_command_violation_count": None,
        "sg_command_violation_duration_s": None,
        "max_contiguous_sg_command_violation_s": None,
        "ibr_command_violation_count": None,
        "ibr_command_violation_duration_s": None,
        "max_contiguous_ibr_command_violation_s": None,
    }
    sg_command_violation = np.asarray([], dtype=np.bool_)
    ibr_command_violation = np.asarray([], dtype=np.bool_)
    if control_prefix >= 1:
        control_time = np.asarray(control.time_s, dtype=np.float64)[:control_prefix]
        u_sg = control_core[0][:control_prefix]
        u_ibr = control_core[1][:control_prefix]
        p_ibr = control_core[2][:control_prefix]
        sg_command_violation = _command_violation_mask(
            control_time,
            u_sg,
            command_min_pu=config.sg_command_min_pu,
            command_max_pu=config.sg_command_max_pu,
            slew_limit_pu_per_s=config.sg_slew_limit_pu_per_s,
            initial_command_pu=control.u_sg_initial_pu,
            sample_period_s=config.command_sample_period_s,
            resource_name="SG",
        )
        ibr_command_violation = _command_violation_mask(
            control_time,
            u_ibr,
            command_min_pu=config.ibr_command_min_pu,
            command_max_pu=config.ibr_command_max_pu,
            slew_limit_pu_per_s=config.ibr_slew_limit_pu_per_s,
            initial_command_pu=control.u_ibr_initial_pu,
            sample_period_s=config.command_sample_period_s,
            resource_name="IBR",
        )
        transfer_time, transfer_censored, transfer_exposure = _responsibility_transfer(
            control_time,
            u_sg,
            u_ibr,
            control.responsibility_event_time_s,
            config.responsibility_sg_share,
            config.responsibility_hold_s,
            trace_complete=metrics_complete,
        )
        fallback = np.asarray(
            [
                _is_fallback_state(state, config.fallback_states)
                for state in control.controller_state[:control_prefix]
            ],
            dtype=np.bool_,
        )
        control_metrics.update(
            sg_mileage=_mileage(u_sg, control.u_sg_initial_pu),
            ibr_mileage=_mileage(u_ibr, control.u_ibr_initial_pu),
            ibr_tracking_error=_left_integral(control_time, np.abs(u_ibr - p_ibr)),
            sg_abs_energy_pu_s=_left_integral(control_time, np.abs(u_sg)),
            ibr_abs_energy_pu_s=_left_integral(control_time, np.abs(p_ibr)),
            peak_abs_sg_command_pu=float(np.max(np.abs(u_sg))),
            peak_abs_ibr_command_pu=float(np.max(np.abs(u_ibr))),
            responsibility_transfer_time_s=transfer_time,
            responsibility_transfer_censored=transfer_censored,
            responsibility_transfer_censoring_time_s=transfer_exposure,
            fallback_duration_s=_zoh_duration(control_time, fallback),
            sg_command_violation_count=_run_count(sg_command_violation),
            sg_command_violation_duration_s=_zoh_duration(
                control_time, sg_command_violation
            ),
            max_contiguous_sg_command_violation_s=_max_zoh_run_duration(
                control_time, sg_command_violation
            ),
            ibr_command_violation_count=_run_count(ibr_command_violation),
            ibr_command_violation_duration_s=_zoh_duration(
                control_time, ibr_command_violation
            ),
            max_contiguous_ibr_command_violation_s=_max_zoh_run_duration(
                control_time, ibr_command_violation
            ),
        )

    solver = _solver_metrics(control)
    fallback_all = np.asarray(
        [
            _is_fallback_state(state, config.fallback_states)
            for state in control.controller_state
        ],
        dtype=np.bool_,
    )
    solver_without_fallback = bool(np.any(solver["failed"] & ~fallback_all))

    diagnostic_summary = DetectionDelaySummary(0, 0, 0, None, None, None, None, ())
    if diagnostic_event_windows:
        if control.diagnostic_alarm_active is None:
            raise ValueError("diagnostic event windows require diagnostic_alarm_active")
        diagnostic_summary = evaluate_detection_delay(
            control.time_s, control.diagnostic_alarm_active, diagnostic_event_windows
        )
    ood_summary = DetectionDelaySummary(0, 0, 0, None, None, None, None, ())
    if ood_event_windows:
        if control.ood_alarm_active is None:
            raise ValueError("OOD event windows require ood_alarm_active")
        ood_summary = evaluate_detection_delay(
            control.time_s, control.ood_alarm_active, ood_event_windows
        )

    diagnostic_risk: float | None = None
    if diagnostic_summary.events and truth_prefix >= 2:
        diagnostic_risk = 0.0
        for event in diagnostic_summary.events:
            endpoint = (
                event.detection_time_s
                if event.detection_time_s is not None
                else event.interval_end_time_s
            )
            diagnostic_risk += _integral_abs_between(
                truth_time, delta, event.onset_time_s, endpoint
            )

    safety = bool(
        delta.size and np.any(np.abs(delta) > config.safety_frequency_limit_hz)
    )
    command_violation_durations = tuple(
        float(value)
        for value in (
            control_metrics["max_contiguous_sg_command_violation_s"],
            control_metrics["max_contiguous_ibr_command_violation_s"],
        )
        if value is not None
    )
    max_command_violation = (
        max(command_violation_durations) if command_violation_durations else None
    )
    has_command_violation = bool(
        (sg_command_violation.size and np.any(sg_command_violation))
        or (ibr_command_violation.size and np.any(ibr_command_violation))
    )
    persistent_command = bool(
        max_command_violation is not None
        and has_command_violation
        and max_command_violation + 1e-15 >= config.command_violation_persistence_s
    )
    not_recovered = bool(
        not run_completed
        or frequency["settling_censored"] is not False
        or nan_detected
    )
    catastrophic = safety or solver_without_fallback or nan_detected or persistent_command or not_recovered

    return ClosedLoopMetrics(
        metrics_complete=metrics_complete,
        truth_sample_count=int(truth_prefix),
        control_sample_count=int(control_prefix),
        evaluated_truth_end_time_s=None if truth_prefix == 0 else float(truth.time_s[truth_prefix - 1]),
        **frequency,
        **control_metrics,
        solver_attempt_count=solver["solver_attempt_count"],
        solve_time_mean_s=solver["solve_time_mean_s"],
        solve_time_p95_s=solver["solve_time_p95_s"],
        solve_time_max_s=solver["solve_time_max_s"],
        solver_fail_count=solver["solver_fail_count"],
        solver_timeout_count=solver["solver_timeout_count"],
        solver_timeout_rate=solver["solver_timeout_rate"],
        solver_infeasible_count=solver["solver_infeasible_count"],
        solver_infeasible_rate=solver["solver_infeasible_rate"],
        solver_inaccurate_count=solver["solver_inaccurate_count"],
        solver_inaccurate_rate=solver["solver_inaccurate_rate"],
        max_freq_slack_hz=solver["max_freq_slack_hz"],
        max_rocof_slack_hz_s=solver["max_rocof_slack_hz_s"],
        max_power_slack_pu=solver["max_power_slack_pu"],
        detection_delay_s=diagnostic_summary.mean_detected_delay_s,
        detection_event_count=diagnostic_summary.event_count,
        detection_censored_count=diagnostic_summary.censored_count,
        detection_censoring_time_s=diagnostic_summary.mean_censoring_time_s,
        ood_detected=(None if ood_summary.event_count == 0 else ood_summary.detected_count > 0),
        ood_detection_delay_s=ood_summary.mean_detected_delay_s,
        ood_detection_event_count=ood_summary.event_count,
        ood_detection_censored_count=ood_summary.censored_count,
        ood_detection_censoring_time_s=ood_summary.mean_censoring_time_s,
        diagnostic_risk_iae=diagnostic_risk,
        catastrophic_failure=catastrophic,
        catastrophic_safety_boundary=safety,
        catastrophic_solver_without_fallback=solver_without_fallback,
        catastrophic_nan_detected=nan_detected,
        catastrophic_persistent_command_violation=persistent_command,
        catastrophic_not_recovered=not_recovered,
        diagnostic_detection_events=diagnostic_summary.events,
        ood_detection_events=ood_summary.events,
    )


__all__ = [
    "ClosedLoopMetricConfig",
    "ClosedLoopMetrics",
    "ControlRateTrace",
    "DetectionDelaySummary",
    "DetectionEventResult",
    "DetectionWindow",
    "HighFrequencyTruthTrace",
    "compute_closed_loop_metrics",
    "evaluate_detection_delay",
]
