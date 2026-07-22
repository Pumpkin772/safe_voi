"""Strict, flat schemas for episode-level evaluation results.

The episode table is the statistical source of truth.  In particular, a
simulation or post-processing failure still produces exactly one row.  A
missing metric is represented by ``None`` (and therefore by a nullable value
in a dataframe), never by a fabricated number and never by removing the row.

``run_completed`` answers whether the requested simulation finished.
``scientific_success`` is deliberately stricter: the run must have completed,
its metrics must be complete, and none of the predeclared catastrophic events
may have occurred.  ``success`` is retained as a compatibility alias for
``scientific_success``; the two are validated to be identical.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, fields
import math
from numbers import Integral, Real
from typing import Any, ClassVar

import numpy as np
import pandas as pd


SCHEMA_VERSION = "d5freq.episode-result.v2"


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, name)


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{name} must be boolean")
    return bool(value)


def _optional_boolean(value: object, name: str) -> bool | None:
    if value is None:
        return None
    return _boolean(value, name)


def _optional_finite(value: object, name: str) -> float | None:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number or None")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite or None; NaN/inf are not schema values")
    return normalized


def _optional_nonnegative_int(value: object, name: str) -> int | None:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be an integer-valued number or None")
    numeric = float(value)
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise TypeError(f"{name} must be an integer-valued number or None")
    normalized = int(numeric)
    if normalized < 0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


@dataclass(frozen=True, slots=True)
class EpisodeResult:
    """One flat, serializable row for one attempted episode.

    All metric fields are nullable so a runner can preserve a failed episode.
    Catastrophic flags and completion flags are never nullable.  Use
    :meth:`failed` when no metrics could be computed, or :meth:`from_metrics`
    to merge a closed-loop metric mapping without weakening this validation.
    """

    run_id: str
    scenario_id: str
    method: str
    seed: int
    schema_version: str = SCHEMA_VERSION

    run_completed: bool = False
    metrics_complete: bool = False
    scientific_success: bool | None = None
    success: bool | None = None

    failure_stage: str | None = None
    failure_type: str | None = None
    failure_message: str | None = None

    catastrophic_failure: bool | None = None
    catastrophic_safety_boundary: bool = False
    catastrophic_solver_without_fallback: bool = False
    catastrophic_nan_detected: bool = False
    catastrophic_persistent_command_violation: bool = False
    catastrophic_not_recovered: bool = False

    max_abs_freq_hz: float | None = None
    nadir_delta_hz: float | None = None
    zenith_delta_hz: float | None = None
    nadir_hz: float | None = None
    zenith_hz: float | None = None
    max_abs_rocof_hz_s: float | None = None
    freq_iae: float | None = None
    freq_ise: float | None = None
    settling_time_s: float | None = None
    settling_censored: bool | None = None
    settling_censoring_time_s: float | None = None
    freq_violation_duration_s: float | None = None
    rocof_violation_duration_s: float | None = None
    constraint_violation_count: int | None = None
    violation_duration_s: float | None = None

    sg_mileage: float | None = None
    ibr_mileage: float | None = None
    ibr_tracking_error: float | None = None
    sg_abs_energy_pu_s: float | None = None
    ibr_abs_energy_pu_s: float | None = None
    peak_abs_sg_command_pu: float | None = None
    peak_abs_ibr_command_pu: float | None = None
    responsibility_transfer_time_s: float | None = None
    responsibility_transfer_censored: bool | None = None
    responsibility_transfer_censoring_time_s: float | None = None
    fallback_duration_s: float | None = None
    sg_command_violation_count: int | None = None
    sg_command_violation_duration_s: float | None = None
    max_contiguous_sg_command_violation_s: float | None = None
    ibr_command_violation_count: int | None = None
    ibr_command_violation_duration_s: float | None = None
    max_contiguous_ibr_command_violation_s: float | None = None

    solver_attempt_count: int | None = None
    solve_time_mean_s: float | None = None
    solve_time_p95_s: float | None = None
    solve_time_max_s: float | None = None
    solver_fail_count: int | None = None
    solver_timeout_count: int | None = None
    solver_timeout_rate: float | None = None
    solver_infeasible_count: int | None = None
    solver_infeasible_rate: float | None = None
    solver_inaccurate_count: int | None = None
    solver_inaccurate_rate: float | None = None
    max_freq_slack_hz: float | None = None
    max_rocof_slack_hz_s: float | None = None
    max_power_slack_pu: float | None = None

    mode_accuracy: float | None = None
    macro_f1: float | None = None
    detection_delay_s: float | None = None
    detection_event_count: int | None = None
    detection_censored_count: int | None = None
    detection_censoring_time_s: float | None = None
    false_alarm_rate: float | None = None
    brier: float | None = None
    nll: float | None = None
    ece: float | None = None
    ood_auroc: float | None = None
    ood_auprc: float | None = None
    ood_detected: bool | None = None
    ood_detection_delay_s: float | None = None
    ood_detection_event_count: int | None = None
    ood_detection_censored_count: int | None = None
    ood_detection_censoring_time_s: float | None = None
    diagnostic_risk_iae: float | None = None

    oracle_regret: float | None = None
    wall_time_s: float | None = None

    _FLOAT_FIELDS: ClassVar[tuple[str, ...]] = (
        "max_abs_freq_hz",
        "nadir_delta_hz",
        "zenith_delta_hz",
        "nadir_hz",
        "zenith_hz",
        "max_abs_rocof_hz_s",
        "freq_iae",
        "freq_ise",
        "settling_time_s",
        "settling_censoring_time_s",
        "freq_violation_duration_s",
        "rocof_violation_duration_s",
        "violation_duration_s",
        "sg_mileage",
        "ibr_mileage",
        "ibr_tracking_error",
        "sg_abs_energy_pu_s",
        "ibr_abs_energy_pu_s",
        "peak_abs_sg_command_pu",
        "peak_abs_ibr_command_pu",
        "responsibility_transfer_time_s",
        "responsibility_transfer_censoring_time_s",
        "fallback_duration_s",
        "sg_command_violation_duration_s",
        "max_contiguous_sg_command_violation_s",
        "ibr_command_violation_duration_s",
        "max_contiguous_ibr_command_violation_s",
        "solve_time_mean_s",
        "solve_time_p95_s",
        "solve_time_max_s",
        "solver_timeout_rate",
        "solver_infeasible_rate",
        "solver_inaccurate_rate",
        "max_freq_slack_hz",
        "max_rocof_slack_hz_s",
        "max_power_slack_pu",
        "mode_accuracy",
        "macro_f1",
        "detection_delay_s",
        "detection_censoring_time_s",
        "false_alarm_rate",
        "brier",
        "nll",
        "ece",
        "ood_auroc",
        "ood_auprc",
        "ood_detection_delay_s",
        "ood_detection_censoring_time_s",
        "diagnostic_risk_iae",
        "oracle_regret",
        "wall_time_s",
    )
    _INT_FIELDS: ClassVar[tuple[str, ...]] = (
        "constraint_violation_count",
        "sg_command_violation_count",
        "ibr_command_violation_count",
        "solver_attempt_count",
        "solver_fail_count",
        "solver_timeout_count",
        "solver_infeasible_count",
        "solver_inaccurate_count",
        "detection_event_count",
        "detection_censored_count",
        "ood_detection_event_count",
        "ood_detection_censored_count",
    )
    _OPTIONAL_BOOL_FIELDS: ClassVar[tuple[str, ...]] = (
        "settling_censored",
        "responsibility_transfer_censored",
        "ood_detected",
    )
    _CATASTROPHIC_FIELDS: ClassVar[tuple[str, ...]] = (
        "catastrophic_safety_boundary",
        "catastrophic_solver_without_fallback",
        "catastrophic_nan_detected",
        "catastrophic_persistent_command_violation",
        "catastrophic_not_recovered",
    )

    def __post_init__(self) -> None:
        for name in ("run_id", "scenario_id", "method"):
            object.__setattr__(self, name, _nonempty_string(getattr(self, name), name))
        object.__setattr__(self, "schema_version", _nonempty_string(self.schema_version, "schema_version"))
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION!r}")
        if isinstance(self.seed, (bool, np.bool_)) or not isinstance(self.seed, Integral):
            raise TypeError("seed must be an integer")
        object.__setattr__(self, "seed", int(self.seed))

        for name in ("run_completed", "metrics_complete", *self._CATASTROPHIC_FIELDS):
            object.__setattr__(self, name, _boolean(getattr(self, name), name))
        for name in ("failure_stage", "failure_type", "failure_message"):
            object.__setattr__(self, name, _optional_string(getattr(self, name), name))
        for name in self._FLOAT_FIELDS:
            object.__setattr__(self, name, _optional_finite(getattr(self, name), name))
        for name in self._INT_FIELDS:
            object.__setattr__(self, name, _optional_nonnegative_int(getattr(self, name), name))
        for name in self._OPTIONAL_BOOL_FIELDS:
            object.__setattr__(self, name, _optional_boolean(getattr(self, name), name))

        catastrophic = any(bool(getattr(self, name)) for name in self._CATASTROPHIC_FIELDS)
        declared_catastrophic = _optional_boolean(
            self.catastrophic_failure, "catastrophic_failure"
        )
        if declared_catastrophic is not None and declared_catastrophic != catastrophic:
            raise ValueError("catastrophic_failure must equal the OR of its subflags")
        object.__setattr__(self, "catastrophic_failure", catastrophic)

        derived_success = bool(
            self.run_completed and self.metrics_complete and not catastrophic
        )
        for name in ("scientific_success", "success"):
            declared = _optional_boolean(getattr(self, name), name)
            if declared is not None and declared != derived_success:
                raise ValueError(
                    f"{name} must equal run_completed AND metrics_complete AND "
                    "NOT catastrophic_failure"
                )
            object.__setattr__(self, name, derived_success)

        if not self.run_completed and self.failure_type is None:
            raise ValueError("an incomplete run must retain failure_type")
        if not self.metrics_complete and self.failure_type is None:
            raise ValueError("incomplete metrics must retain failure_type")
        if self.scientific_success and any(
            value is not None
            for value in (self.failure_stage, self.failure_type, self.failure_message)
        ):
            raise ValueError("a scientifically successful row cannot carry failure metadata")

    @classmethod
    def failed(
        cls,
        *,
        run_id: str,
        scenario_id: str,
        method: str,
        seed: int,
        failure_stage: str,
        failure_type: str,
        failure_message: str,
        **known_values: Any,
    ) -> "EpisodeResult":
        """Build the mandatory row for a failed or interrupted episode."""

        return cls(
            run_id=run_id,
            scenario_id=scenario_id,
            method=method,
            seed=seed,
            run_completed=False,
            metrics_complete=False,
            failure_stage=failure_stage,
            failure_type=failure_type,
            failure_message=failure_message,
            **known_values,
        )

    @classmethod
    def from_metrics(
        cls,
        *,
        run_id: str,
        scenario_id: str,
        method: str,
        seed: int,
        metrics: Mapping[str, Any] | object,
        run_completed: bool,
        failure_stage: str | None = None,
        failure_type: str | None = None,
        failure_message: str | None = None,
        **overrides: Any,
    ) -> "EpisodeResult":
        """Merge a flat metric object while ignoring non-schema diagnostics.

        ``metrics`` may be a mapping, a dataclass, or an object exposing
        ``to_dict``.  Identity and failure state always come from explicit
        arguments; an output object cannot accidentally overwrite them.
        """

        if isinstance(metrics, Mapping):
            source = dict(metrics)
        elif hasattr(metrics, "to_dict"):
            source = dict(metrics.to_dict())
        else:
            try:
                source = asdict(metrics)  # type: ignore[arg-type]
            except TypeError as exc:
                raise TypeError("metrics must be a mapping, dataclass, or expose to_dict") from exc
        allowed = {item.name for item in fields(cls)}
        protected = {
            "run_id",
            "scenario_id",
            "method",
            "seed",
            "run_completed",
            "failure_stage",
            "failure_type",
            "failure_message",
        }
        payload = {
            key: value
            for key, value in source.items()
            if key in allowed and key not in protected
        }
        unknown_overrides = set(overrides) - allowed
        if unknown_overrides:
            raise TypeError(f"unknown EpisodeResult override(s): {sorted(unknown_overrides)!r}")
        payload.update(overrides)
        return cls(
            run_id=run_id,
            scenario_id=scenario_id,
            method=method,
            seed=seed,
            run_completed=run_completed,
            failure_stage=failure_stage,
            failure_type=failure_type,
            failure_message=failure_message,
            **payload,
        )

    def to_row(self) -> dict[str, Any]:
        """Return primitive scalars in the canonical column order."""

        return {item.name: _primitive(getattr(self, item.name)) for item in fields(self)}

    def to_json_dict(self) -> dict[str, Any]:
        """Alias emphasizing that strict JSON serialization is safe."""

        return self.to_row()


def _primitive(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite values cannot be serialized in the result schema")
        return value
    raise TypeError(f"episode result contains a non-scalar value: {type(value).__name__}")


EPISODE_RESULT_COLUMNS: tuple[str, ...] = tuple(
    item.name for item in fields(EpisodeResult)
)
EPISODE_KEY_COLUMNS: tuple[str, ...] = (
    "run_id",
    "scenario_id",
    "method",
    "seed",
)


def episode_results_frame(records: Iterable[EpisodeResult]) -> pd.DataFrame:
    """Create a stable-column dataframe without discarding failure rows."""

    rows = [record.to_row() for record in records]
    frame = pd.DataFrame.from_records(rows, columns=EPISODE_RESULT_COLUMNS)
    validate_episode_frame(frame)
    return frame


def validate_episode_frame(frame: pd.DataFrame, *, exact_columns: bool = True) -> None:
    """Validate table shape, row identity, and per-row schema invariants.

    Validation reconstructs every row as :class:`EpisodeResult`.  Nullable
    dataframe values are converted back to ``None`` first, so CSV/Parquet
    round trips remain valid.  The input frame is never mutated.
    """

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    missing = tuple(column for column in EPISODE_RESULT_COLUMNS if column not in frame.columns)
    if missing:
        raise ValueError(f"episode table is missing columns: {missing!r}")
    if exact_columns and tuple(frame.columns) != EPISODE_RESULT_COLUMNS:
        raise ValueError("episode table columns must exactly match the canonical order")
    if frame["run_id"].duplicated().any():
        duplicates = frame.loc[frame["run_id"].duplicated(keep=False), "run_id"].tolist()
        raise ValueError(f"run_id must identify exactly one episode row: {duplicates!r}")
    init_names = {item.name for item in fields(EpisodeResult) if item.init}
    for row_index, raw_row in frame.loc[:, EPISODE_RESULT_COLUMNS].iterrows():
        payload: dict[str, Any] = {}
        for key, value in raw_row.items():
            if key not in init_names:
                continue
            payload[key] = None if pd.isna(value) else value
        try:
            EpisodeResult(**payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid episode row at index {row_index!r}: {exc}") from exc


__all__ = [
    "EPISODE_KEY_COLUMNS",
    "EPISODE_RESULT_COLUMNS",
    "EpisodeResult",
    "SCHEMA_VERSION",
    "episode_results_frame",
    "validate_episode_frame",
]
