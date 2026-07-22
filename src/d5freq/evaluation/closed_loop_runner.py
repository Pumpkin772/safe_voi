"""Factory-independent execution of one closed-loop evaluation episode.

The runner accepts already-built simulator, scenario, and controller objects.
Ordinary controllers receive only :class:`~d5freq.interfaces.Measurement`.
An Oracle can receive evaluator truth only when the caller supplies both an
explicit truth provider and an explicit evaluation-only action callback.

All failures are converted to one :class:`EpisodeResult` and atomically saved
through :class:`PerRunExperimentStore`.  Available truth and control prefixes
are still post-processed, but incomplete metrics are marked as such and the
episode row is never dropped.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields, is_dataclass, replace
import math
from numbers import Integral, Real
from types import MappingProxyType
from typing import Any, TypeAlias
from time import perf_counter

import numpy as np

from d5freq.evaluation.closed_loop_metrics import (
    ClosedLoopMetricConfig,
    ClosedLoopMetrics,
    ControlRateTrace,
    HighFrequencyTruthTrace,
    compute_closed_loop_metrics,
)
from d5freq.evaluation.experiment_store import (
    PerRunExperimentStore,
    RunIdentity,
    RunIntegrityError,
    StoredRun,
    strict_json_value,
)
from d5freq.evaluation.results_schema import EpisodeResult
from d5freq.interfaces import ControlAction, Measurement


TruthProvider: TypeAlias = Callable[[object, float, Mapping[str, Any] | None], Mapping[str, Any]]
OracleActionCallback: TypeAlias = Callable[
    [object, Measurement, Mapping[str, Any]], ControlAction
]
ControllerRecordsGetter: TypeAlias = Callable[[object], Sequence[object]]
MetricFunction: TypeAlias = Callable[..., ClosedLoopMetrics]
ImmutableRunArtifactWriter: TypeAlias = Callable[
    ["EpisodeEvaluationData", EpisodeResult], Mapping[str, Any]
]

FAILURE_TRACE_STORAGE_SCHEMA_VERSION = "d5freq.failure_trace_storage.v1"
FAILURE_TRACE_POINT_LIMIT = 2_001
FAILURE_TRACE_INTERVAL_LIMIT = 401


def _finite(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


@dataclass(frozen=True, slots=True)
class EpisodeRunnerConfig:
    """Execution/storage policy; the final protocol defaults to 180 seconds."""

    expected_duration_s: float | None = 180.0
    duration_tolerance_s: float = 1e-9
    max_control_steps: int = 1_000_000
    resume: bool = True
    replace_existing: bool = False
    persist_control_trajectory: bool = True
    persist_high_frequency_trace: bool = False
    persist_controller_records: bool = True

    def __post_init__(self) -> None:
        if self.expected_duration_s is not None:
            duration = _finite(self.expected_duration_s, "expected_duration_s")
            if duration <= 0.0:
                raise ValueError("expected_duration_s must be positive")
            object.__setattr__(self, "expected_duration_s", duration)
        tolerance = _finite(self.duration_tolerance_s, "duration_tolerance_s")
        if tolerance < 0.0:
            raise ValueError("duration_tolerance_s must be non-negative")
        object.__setattr__(self, "duration_tolerance_s", tolerance)
        if (
            isinstance(self.max_control_steps, (bool, np.bool_))
            or not isinstance(self.max_control_steps, Integral)
            or int(self.max_control_steps) <= 0
        ):
            raise ValueError("max_control_steps must be a strictly positive integer")
        object.__setattr__(self, "max_control_steps", int(self.max_control_steps))
        for name in (
            "resume",
            "replace_existing",
            "persist_control_trajectory",
            "persist_high_frequency_trace",
            "persist_controller_records",
        ):
            if not isinstance(getattr(self, name), (bool, np.bool_)):
                raise TypeError(f"{name} must be boolean")
            object.__setattr__(self, name, bool(getattr(self, name)))
        if self.resume and self.replace_existing:
            raise ValueError("resume and replace_existing cannot both be true")


@dataclass(frozen=True, slots=True)
class EvaluationContribution:
    """Evaluator-only scalar result fields and optional auditable artifacts."""

    metric_overrides: Mapping[str, Any] = field(default_factory=dict)
    artifacts: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("metric_overrides", "artifacts"):
            value = getattr(self, name)
            if not isinstance(value, Mapping) or not all(
                isinstance(key, str) for key in value
            ):
                raise TypeError(f"{name} must be a string-keyed mapping")
            converted = (
                dict(value)
                if name == "metric_overrides"
                else strict_json_value(value)
            )
            object.__setattr__(self, name, MappingProxyType(dict(converted)))


@dataclass(frozen=True, slots=True)
class EpisodeEvaluationData:
    """Evaluator-owned traces; this object is never supplied to a controller."""

    identity: RunIdentity
    scenario: object
    run_completed: bool
    measurements: tuple[Measurement, ...]
    actions: tuple[ControlAction, ...]
    simulator_evaluations: tuple[Mapping[str, Any], ...]
    truth_points_eval_only: tuple[Mapping[str, Any], ...]
    truth_intervals_eval_only: tuple[Mapping[str, Any], ...]
    controller_records: tuple[Mapping[str, Any], ...]
    high_frequency_truth: HighFrequencyTruthTrace | None
    control_trace: ControlRateTrace | None
    control_trajectory: tuple[Mapping[str, Any], ...]
    base_metrics: ClosedLoopMetrics | None
    failure_stage: str | None
    failure_type: str | None
    failure_message: str | None


EpisodeEvaluator: TypeAlias = Callable[[EpisodeEvaluationData], EvaluationContribution]


@dataclass(frozen=True, slots=True)
class EpisodeRunOutcome:
    identity: RunIdentity
    episode_result: EpisodeResult
    stored_run: StoredRun
    resumed: bool
    evaluation_data: EpisodeEvaluationData | None


def scenario_truth_provider(
    scenario: object,
    time_s: float,
    latest_evaluation: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    """Explicit evaluator-side provider for B4's current hidden-mode key."""

    current_time = _finite(time_s, "time_s")
    if latest_evaluation is not None:
        evaluation_time = float(latest_evaluation.get("time_s", math.nan))
        if math.isclose(evaluation_time, current_time, rel_tol=0.0, abs_tol=1e-9):
            if "true_mode_eval_only" not in latest_evaluation:
                raise KeyError("latest evaluation lacks true_mode_eval_only")
            return MappingProxyType(
                {
                    "time_s": current_time,
                    "true_mode_eval_only": str(
                        latest_evaluation["true_mode_eval_only"]
                    ),
                }
            )
    schedule = getattr(scenario, "mode_schedule", None)
    if schedule is None or not callable(getattr(schedule, "mode_at", None)):
        raise TypeError("scenario truth provider requires scenario.mode_schedule.mode_at")
    return MappingProxyType(
        {
            "time_s": current_time,
            "true_mode_eval_only": str(schedule.mode_at(current_time)),
        }
    )


def oracle_action_from_truth(
    controller: object,
    measurement: Measurement,
    truth: Mapping[str, Any],
) -> ControlAction:
    """The sole generic bridge to an Oracle's label-bearing runtime method."""

    method = getattr(controller, "act_evaluation_only", None)
    if not callable(method):
        raise TypeError("Oracle controller must expose act_evaluation_only")
    if "true_mode_eval_only" not in truth:
        raise KeyError("Oracle truth context lacks true_mode_eval_only")
    action = method(
        measurement,
        true_mode_eval_only=str(truth["true_mode_eval_only"]),
    )
    if not isinstance(action, ControlAction):
        raise TypeError("Oracle action callback must return ControlAction")
    return action


def _record_mapping(record: object) -> dict[str, Any]:
    if isinstance(record, Mapping):
        return dict(record)
    if callable(getattr(record, "to_log_record", None)):
        value = record.to_log_record()
        if not isinstance(value, Mapping):
            raise TypeError("controller to_log_record() must return a mapping")
        return dict(value)
    if callable(getattr(record, "to_dict", None)):
        value = record.to_dict()
        if not isinstance(value, Mapping):
            raise TypeError("controller record to_dict() must return a mapping")
        return dict(value)
    if is_dataclass(record):
        return asdict(record)
    raise TypeError(f"unsupported controller step record {type(record).__name__}")


def controller_step_records(controller: object) -> tuple[Mapping[str, Any], ...]:
    """Read direct records or one explicit ``inner_controller`` layer for B4."""

    candidates = (controller, getattr(controller, "inner_controller", None))
    for candidate in candidates:
        if candidate is None or not hasattr(candidate, "step_records"):
            continue
        raw = getattr(candidate, "step_records")
        raw = raw() if callable(raw) else raw
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            raise TypeError("controller step_records must be a sequence")
        return tuple(MappingProxyType(_record_mapping(record)) for record in raw)
    return ()


def _copy_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{name} must be a string-keyed mapping")
    return MappingProxyType(dict(value))


def _same_truth_value(first: Any, second: Any, tolerance: float) -> bool:
    if isinstance(first, Real) and not isinstance(first, (bool, np.bool_)):
        if not isinstance(second, Real) or isinstance(second, (bool, np.bool_)):
            return False
        left = float(first)
        right = float(second)
        if math.isnan(left) and math.isnan(right):
            return True
        return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)
    return first == second


def _deduplicate_truth_points(
    points: Sequence[Mapping[str, Any]],
    *,
    tolerance: float = 1e-12,
) -> tuple[Mapping[str, Any], ...]:
    deduplicated: list[Mapping[str, Any]] = []
    for ordinal, point in enumerate(points):
        if "time_s" not in point:
            raise KeyError(f"truth point {ordinal} lacks time_s")
        point_time = float(point["time_s"])
        if not math.isfinite(point_time):
            raise ValueError("truth point time_s must be finite")
        if deduplicated:
            previous_time = float(deduplicated[-1]["time_s"])
            if point_time < previous_time - tolerance:
                raise ValueError("truth points are not in non-decreasing time order")
            # Only equal (or microscopically regressed) timestamps are
            # duplicates.  A slightly later point can be the right side of a
            # real disturbance discontinuity whose left endpoint accumulated
            # a few floating-point ulps below the registered event time.
            if point_time <= previous_time:
                previous = deduplicated[-1]
                if set(previous) != set(point) or any(
                    not _same_truth_value(previous[key], point[key], tolerance)
                    for key in previous
                ):
                    raise ValueError("duplicate truth boundary contains inconsistent values")
                continue
        deduplicated.append(MappingProxyType(dict(point)))
    return tuple(deduplicated)


def _endpoint_preserving_trace_sample(
    rows: Sequence[Mapping[str, Any]],
    limit: int,
) -> tuple[Mapping[str, Any], ...]:
    if limit < 2:
        raise ValueError("trace sample limit must preserve both endpoints")
    if len(rows) <= limit:
        return tuple(rows)
    final_index = len(rows) - 1
    indices = tuple(
        ordinal * final_index // (limit - 1) for ordinal in range(limit)
    )
    if indices[0] != 0 or indices[-1] != final_index:
        raise AssertionError("endpoint-preserving trace sample lost an endpoint")
    if len(set(indices)) != limit:
        raise AssertionError("endpoint-preserving trace sample repeated an index")
    return tuple(rows[index] for index in indices)


def _solver_outcome(status: str) -> str:
    normalized = status.strip().lower()
    if normalized == "optimal":
        return "success"
    if normalized == "optimal_inaccurate":
        return "inaccurate"
    if normalized.startswith("infeasible"):
        return "infeasible"
    if normalized == "unbounded":
        return "unbounded"
    if normalized == "timeout":
        return "timeout"
    if normalized in {
        "fallback_lqi",
        "not_applicable",
        "not_run",
        "skipped",
    }:
        return "not_run"
    return "error"


def _mode_belief(record: Mapping[str, Any]) -> Any:
    if "mode_belief" in record:
        return record["mode_belief"]
    indexed: list[tuple[int, Any]] = []
    for key, value in record.items():
        if not key.startswith("belief_"):
            continue
        suffix = key.removeprefix("belief_")
        if suffix.isdigit():
            indexed.append((int(suffix), value))
    if not indexed:
        return None
    indexed.sort(key=lambda item: item[0])
    if [index for index, _ in indexed] != list(range(len(indexed))):
        raise ValueError("flattened belief columns must be consecutive from belief_0")
    return [float(value) for _, value in indexed]


def _truth_power_at(
    time_s: float,
    truth_points: Sequence[Mapping[str, Any]],
    fallback: float,
) -> float:
    for point in reversed(truth_points):
        if math.isclose(float(point["time_s"]), time_s, rel_tol=0.0, abs_tol=1e-9):
            value = point.get("p_ibr_true_pu", fallback)
            return float(value)
        if float(point["time_s"]) < time_s - 1e-9:
            break
    return float(fallback)


def _build_control_trace(
    measurements: Sequence[Measurement],
    actions: Sequence[ControlAction],
    records: Sequence[Mapping[str, Any]],
    truth_points: Sequence[Mapping[str, Any]],
    *,
    responsibility_event_time_s: float | None,
) -> tuple[ControlRateTrace | None, tuple[Mapping[str, Any], ...]]:
    if not actions:
        return None, ()
    if records and len(records) != len(actions):
        raise ValueError(
            "controller step_records must contain one record per returned action"
        )
    sample_count = len(actions)
    sample_times = [float(measurements[index].time_s) for index in range(sample_count)]
    u_sg = [float(action.u_sg_pu) for action in actions]
    u_ibr = [float(action.u_ibr_pu) for action in actions]
    p_ibr = [
        _truth_power_at(
            sample_times[index], truth_points, measurements[index].p_ibr_pu
        )
        for index in range(sample_count)
    ]
    states: list[str] = []
    statuses: list[str] = []
    outcomes: list[str] = []
    solve_times: list[float] = []
    freq_slacks: list[float] = []
    rocof_slacks: list[float] = []
    power_slacks: list[float] = []
    ood_active: list[bool] = []
    rows: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        record = records[index] if records else {}
        state = str(record.get("controller_state", action.controller_state))
        status = str(record.get("solver_status", action.solver_status))
        outcome = str(record.get("solver_outcome", _solver_outcome(status)))
        solve_time = float(record.get("solve_time_s", action.solve_time_s))
        freq_slack = float(record.get("max_freq_slack_hz", action.max_freq_slack_hz))
        rocof_slack = float(
            record.get(
                "max_rocof_slack_hz_s",
                record.get("max_rocof_slack_hz_per_s", 0.0),
            )
        )
        power_slack = float(record.get("max_power_slack_pu", 0.0))
        diagnostic_state = str(record.get("diagnostic_state", "UNSPECIFIED"))
        is_ood = diagnostic_state.upper() == "OOD_ACTIVE"
        states.append(state)
        statuses.append(status)
        outcomes.append(outcome)
        solve_times.append(solve_time)
        freq_slacks.append(freq_slack)
        rocof_slacks.append(rocof_slack)
        power_slacks.append(power_slack)
        ood_active.append(is_ood)
        row: dict[str, Any] = {
            "time_s": sample_times[index],
            "omega_measurement_pu": measurements[index].omega_pu,
            "p_mech_measurement_pu": measurements[index].p_mech_pu,
            "p_ibr_true_pu": p_ibr[index],
            "u_sg_pu": u_sg[index],
            "u_ibr_pu": u_ibr[index],
            "controller_state": state,
            "solver_status": status,
            "solver_outcome": outcome,
            "solve_time_s": solve_time,
            "max_freq_slack_hz": freq_slack,
            "max_rocof_slack_hz_s": rocof_slack,
            "max_power_slack_pu": power_slack,
            "diagnostic_state": diagnostic_state,
            "mode_belief": _mode_belief(record),
            "map_mode": record.get("map_mode"),
            "belief_entropy": record.get("belief_entropy"),
            "ood_pvalue": record.get("ood_pvalue"),
            "terminal_endpoint": False,
        }
        rows.append(row)

    # A final controller-free endpoint closes the last ZOH integration
    # interval.  Its solver is explicitly not_run, avoiding a fabricated solve.
    if len(measurements) > len(actions):
        terminal = measurements[len(actions)]
        if terminal.time_s > sample_times[-1]:
            sample_times.append(float(terminal.time_s))
            u_sg.append(u_sg[-1])
            u_ibr.append(u_ibr[-1])
            p_ibr.append(_truth_power_at(terminal.time_s, truth_points, terminal.p_ibr_pu))
            states.append(states[-1])
            statuses.append("not_run")
            outcomes.append("not_run")
            solve_times.append(0.0)
            freq_slacks.append(0.0)
            rocof_slacks.append(0.0)
            power_slacks.append(0.0)
            ood_active.append(ood_active[-1])
            rows.append(
                {
                    "time_s": terminal.time_s,
                    "omega_measurement_pu": terminal.omega_pu,
                    "p_mech_measurement_pu": terminal.p_mech_pu,
                    "p_ibr_true_pu": p_ibr[-1],
                    "u_sg_pu": u_sg[-1],
                    "u_ibr_pu": u_ibr[-1],
                    "controller_state": states[-1],
                    "solver_status": "not_run",
                    "solver_outcome": "not_run",
                    "solve_time_s": 0.0,
                    "max_freq_slack_hz": 0.0,
                    "max_rocof_slack_hz_s": 0.0,
                    "max_power_slack_pu": 0.0,
                    "diagnostic_state": rows[-1]["diagnostic_state"],
                    "mode_belief": rows[-1]["mode_belief"],
                    "map_mode": rows[-1]["map_mode"],
                    "belief_entropy": rows[-1]["belief_entropy"],
                    "ood_pvalue": rows[-1]["ood_pvalue"],
                    "terminal_endpoint": True,
                }
            )

    trace = ControlRateTrace(
        time_s=sample_times,
        u_sg_pu=u_sg,
        u_ibr_pu=u_ibr,
        p_ibr_pu=p_ibr,
        controller_state=states,
        solver_outcome=outcomes,
        solver_status=statuses,
        solve_time_s=solve_times,
        max_freq_slack_hz=freq_slacks,
        max_rocof_slack_hz_s=rocof_slacks,
        max_power_slack_pu=power_slacks,
        ood_alarm_active=ood_active,
        u_sg_initial_pu=measurements[0].u_sg_prev_pu,
        u_ibr_initial_pu=measurements[0].u_ibr_prev_pu,
        responsibility_event_time_s=responsibility_event_time_s,
    )
    return trace, tuple(MappingProxyType(row) for row in rows)


def _exception_fields(stage: str, error: Exception) -> tuple[str, str, str]:
    message = str(error).strip() or repr(error)
    return stage, type(error).__name__, message


def _looks_nonfinite(error: Exception) -> bool:
    text = f"{type(error).__name__}: {error}".lower()
    return isinstance(error, FloatingPointError) or "nan" in text or "non-finite" in text


def settling_reference_time(scenario: object) -> float:
    """Return the last deterministic load or hidden-mode transition, else zero."""

    transition_times = [0.0]
    schedule = getattr(scenario, "mode_schedule", None)
    for switch in getattr(schedule, "switches", ()):
        transition_times.append(_finite(getattr(switch, "time_s"), "mode switch time"))
    disturbance = getattr(scenario, "disturbance", None)
    for event in getattr(disturbance, "events", ()):
        transition_times.append(
            _finite(getattr(event, "start_time_s"), "load event start time")
        )
        end_time = getattr(event, "end_time_s", None)
        if end_time is not None:
            transition_times.append(_finite(end_time, "load event end time"))
    return max(transition_times)


_EPISODE_FIELDS = {item.name for item in fields(EpisodeResult)}
_PROTECTED_OVERRIDES = {
    "run_id",
    "scenario_id",
    "method",
    "seed",
    "schema_version",
    "run_completed",
    "metrics_complete",
    "scientific_success",
    "success",
    "failure_stage",
    "failure_type",
    "failure_message",
    "catastrophic_failure",
    "oracle_regret",
}


def _merge_contribution(
    target: dict[str, Any],
    contribution: EvaluationContribution,
) -> None:
    unknown = set(contribution.metric_overrides) - _EPISODE_FIELDS
    protected = set(contribution.metric_overrides) & _PROTECTED_OVERRIDES
    if unknown:
        raise ValueError(f"evaluator returned unknown EpisodeResult fields: {sorted(unknown)!r}")
    if protected:
        raise ValueError(f"evaluator cannot override protected result fields: {sorted(protected)!r}")
    overlap = set(target) & set(contribution.metric_overrides)
    if overlap:
        raise ValueError(f"multiple evaluators returned the same fields: {sorted(overlap)!r}")
    target.update(contribution.metric_overrides)


def run_closed_loop_episode(
    *,
    identity: RunIdentity,
    simulator: object,
    scenario: object,
    controller: object,
    metric_config: ClosedLoopMetricConfig,
    store: PerRunExperimentStore,
    runner_config: EpisodeRunnerConfig = EpisodeRunnerConfig(),
    oracle_action_callback: OracleActionCallback | None = None,
    truth_provider: TruthProvider | None = None,
    controller_records_getter: ControllerRecordsGetter | None = None,
    evaluators: Sequence[EpisodeEvaluator] = (),
    responsibility_event_time_s: float | None = None,
    run_provenance: Mapping[str, Any] | None = None,
    metric_function: MetricFunction = compute_closed_loop_metrics,
    immutable_run_artifact_writer: ImmutableRunArtifactWriter | None = None,
) -> EpisodeRunOutcome:
    """Execute, evaluate, and atomically publish exactly one episode.

    ``oracle_action_callback`` and ``truth_provider`` must be supplied together.
    Without them the only online call is ``controller.act(measurement)``.
    ``metric_function`` is injectable for deterministic failure testing; final
    runs should use the default strict metric implementation.  An optional
    ``immutable_run_artifact_writer`` runs after scientific evaluation but
    before the per-run envelope is published.  Its failures propagate to the
    orchestration layer so an envelope can never authenticate a missing or
    partially written external artifact.
    """

    if not isinstance(identity, RunIdentity):
        raise TypeError("identity must be a RunIdentity")
    if not isinstance(metric_config, ClosedLoopMetricConfig):
        raise TypeError("metric_config must be ClosedLoopMetricConfig")
    if not isinstance(store, PerRunExperimentStore):
        raise TypeError("store must be PerRunExperimentStore")
    if not isinstance(runner_config, EpisodeRunnerConfig):
        raise TypeError("runner_config must be EpisodeRunnerConfig")
    normalized_provenance: Mapping[str, Any] | None = None
    if run_provenance is not None:
        if not isinstance(run_provenance, Mapping):
            raise TypeError("run_provenance must be a mapping or None")
        converted_provenance = strict_json_value(run_provenance)
        if not isinstance(converted_provenance, Mapping):
            raise TypeError("run_provenance must normalize to a JSON object")
        normalized_provenance = MappingProxyType(dict(converted_provenance))
    if (oracle_action_callback is None) != (truth_provider is None):
        raise ValueError(
            "oracle_action_callback and truth_provider must be supplied together"
        )
    if responsibility_event_time_s is not None:
        responsibility_event_time_s = _finite(
            responsibility_event_time_s, "responsibility_event_time_s"
        )
    if runner_config.resume:
        existing = store.load(identity)
        if existing is not None:
            if (
                normalized_provenance is not None
                and existing.run_payload.get("provenance")
                != normalized_provenance
            ):
                raise RunIntegrityError(
                    "stored run provenance differs from the requested run provenance"
                )
            return EpisodeRunOutcome(
                identity=identity,
                episode_result=existing.episode_result,
                stored_run=existing,
                resumed=True,
                evaluation_data=None,
            )

    started = perf_counter()
    measurements: list[Measurement] = []
    actions: list[ControlAction] = []
    simulator_evaluations: list[Mapping[str, Any]] = []
    raw_truth_points: list[Mapping[str, Any]] = []
    raw_truth_intervals: list[Mapping[str, Any]] = []
    run_completed = False
    latest_evaluation: Mapping[str, Any] | None = None
    failure: tuple[str, str, str] | None = None
    failure_error: Exception | None = None
    secondary_errors: list[dict[str, str]] = []

    try:
        duration = _finite(getattr(scenario, "duration_s"), "scenario.duration_s")
        if duration <= 0.0:
            raise ValueError("scenario.duration_s must be positive")
        if runner_config.expected_duration_s is not None and not math.isclose(
            duration,
            runner_config.expected_duration_s,
            rel_tol=0.0,
            abs_tol=runner_config.duration_tolerance_s,
        ):
            raise ValueError(
                f"scenario duration {duration} does not equal frozen duration "
                f"{runner_config.expected_duration_s}"
            )
    except Exception as exc:
        duration = math.nan
        failure = _exception_fields("setup", exc)
        failure_error = exc

    if failure is None:
        try:
            reset = getattr(simulator, "reset")
            initial = reset(identity.seed, scenario)
            if not isinstance(initial, Measurement):
                raise TypeError("simulator.reset must return Measurement")
            measurements.append(initial)
        except Exception as exc:
            failure = _exception_fields("simulator_reset", exc)
            failure_error = exc

    if failure is None:
        try:
            reset_controller = getattr(controller, "reset")
            reset_controller(measurements[0])
        except Exception as exc:
            failure = _exception_fields("controller_reset", exc)
            failure_error = exc

    step_count = 0
    while failure is None and not run_completed:
        if step_count >= runner_config.max_control_steps:
            error = RuntimeError("maximum control-step guard reached before episode completion")
            failure = _exception_fields("execution_guard", error)
            failure_error = error
            break
        measurement = measurements[-1]
        try:
            if oracle_action_callback is None:
                act = getattr(controller, "act")
                action = act(measurement)
            else:
                assert truth_provider is not None
                truth = truth_provider(
                    scenario,
                    measurement.time_s,
                    latest_evaluation,
                )
                truth = _copy_mapping(truth, "truth_provider output")
                action = oracle_action_callback(controller, measurement, truth)
            if not isinstance(action, ControlAction):
                raise TypeError("controller action call must return ControlAction")
            actions.append(action)
        except Exception as exc:
            failure = _exception_fields("controller_act", exc)
            failure_error = exc
            break

        try:
            next_measurement, raw_evaluation = getattr(simulator, "step")(action)
            if not isinstance(next_measurement, Measurement):
                raise TypeError("simulator.step must return Measurement first")
            evaluation = _copy_mapping(raw_evaluation, "simulator evaluation")
            if next_measurement.time_s <= measurement.time_s:
                raise ValueError("simulator measurement time did not advance")
            raw_points = evaluation.get("true_trace_points_eval_only", ())
            if not isinstance(raw_points, Sequence) or isinstance(
                raw_points, (str, bytes, bytearray)
            ):
                raise TypeError("true_trace_points_eval_only must be a sequence")
            for point in raw_points:
                raw_truth_points.append(_copy_mapping(point, "truth point"))
            raw_intervals = evaluation.get("true_trace_intervals_eval_only", ())
            if not isinstance(raw_intervals, Sequence) or isinstance(
                raw_intervals, (str, bytes, bytearray)
            ):
                raise TypeError("true_trace_intervals_eval_only must be a sequence")
            for interval in raw_intervals:
                raw_truth_intervals.append(_copy_mapping(interval, "truth interval"))
            measurements.append(next_measurement)
            simulator_evaluations.append(evaluation)
            latest_evaluation = evaluation
            done = evaluation.get("done")
            if not isinstance(done, (bool, np.bool_)):
                raise TypeError("simulator evaluation done flag must be boolean")
            if bool(done):
                if not math.isclose(
                    next_measurement.time_s,
                    duration,
                    rel_tol=0.0,
                    abs_tol=runner_config.duration_tolerance_s,
                ):
                    raise ValueError("simulator declared done away from scenario endpoint")
                run_completed = True
            elif next_measurement.time_s >= duration - runner_config.duration_tolerance_s:
                raise RuntimeError("simulator reached scenario endpoint without done=true")
        except Exception as exc:
            failure = _exception_fields("simulator_step", exc)
            failure_error = exc
            break
        step_count += 1

    records: tuple[Mapping[str, Any], ...] = ()
    try:
        records_raw = (
            controller_step_records(controller)
            if controller_records_getter is None
            else tuple(controller_records_getter(controller))
        )
        records = tuple(
            MappingProxyType(_record_mapping(record)) for record in records_raw
        )
    except Exception as exc:
        if failure is None:
            failure = _exception_fields("record_extraction", exc)
            failure_error = exc
        else:
            stage, kind, message = _exception_fields("record_extraction", exc)
            secondary_errors.append({"stage": stage, "type": kind, "message": message})

    truth_points: tuple[Mapping[str, Any], ...] = ()
    high_frequency_truth: HighFrequencyTruthTrace | None = None
    control_trace: ControlRateTrace | None = None
    control_trajectory: tuple[Mapping[str, Any], ...] = ()
    try:
        truth_points = _deduplicate_truth_points(raw_truth_points)
        if len(truth_points) >= 2:
            high_frequency_truth = HighFrequencyTruthTrace.from_points(truth_points)
        control_trace, control_trajectory = _build_control_trace(
            measurements,
            actions,
            records,
            truth_points,
            responsibility_event_time_s=responsibility_event_time_s,
        )
    except Exception as exc:
        if failure is None:
            failure = _exception_fields("trace_construction", exc)
            failure_error = exc
        else:
            stage, kind, message = _exception_fields("trace_construction", exc)
            secondary_errors.append({"stage": stage, "type": kind, "message": message})

    base_metrics: ClosedLoopMetrics | None = None
    if high_frequency_truth is not None and control_trace is not None:
        try:
            base_metrics = metric_function(
                high_frequency_truth,
                control_trace,
                metric_config,
                run_completed=run_completed,
                settling_reference_time_s=settling_reference_time(scenario),
            )
            if not isinstance(base_metrics, ClosedLoopMetrics):
                raise TypeError("metric_function must return ClosedLoopMetrics")
        except Exception as exc:
            if failure is None:
                failure = _exception_fields("metrics", exc)
                failure_error = exc
            else:
                stage, kind, message = _exception_fields("metrics", exc)
                secondary_errors.append({"stage": stage, "type": kind, "message": message})
    elif failure is None:
        error = RuntimeError("episode completed without enough trace data for metrics")
        failure = _exception_fields("metrics", error)
        failure_error = error

    data = EpisodeEvaluationData(
        identity=identity,
        scenario=scenario,
        run_completed=run_completed,
        measurements=tuple(measurements),
        actions=tuple(actions),
        simulator_evaluations=tuple(simulator_evaluations),
        truth_points_eval_only=truth_points,
        truth_intervals_eval_only=tuple(raw_truth_intervals),
        controller_records=records,
        high_frequency_truth=high_frequency_truth,
        control_trace=control_trace,
        control_trajectory=control_trajectory,
        base_metrics=base_metrics,
        failure_stage=None if failure is None else failure[0],
        failure_type=None if failure is None else failure[1],
        failure_message=None if failure is None else failure[2],
    )

    evaluator_metrics: dict[str, Any] = {}
    evaluator_artifacts: dict[str, Any] = {}
    for ordinal, evaluator in enumerate(evaluators):
        try:
            contribution = evaluator(data)
            if not isinstance(contribution, EvaluationContribution):
                raise TypeError("episode evaluator must return EvaluationContribution")
            _merge_contribution(evaluator_metrics, contribution)
            evaluator_artifacts[f"evaluator_{ordinal}"] = dict(contribution.artifacts)
        except Exception as exc:
            if failure is None:
                failure = _exception_fields("evaluator", exc)
                failure_error = exc
            else:
                stage, kind, message = _exception_fields("evaluator", exc)
                secondary_errors.append({"stage": stage, "type": kind, "message": message})
            break

    if base_metrics is not None and not base_metrics.metrics_complete and failure is None:
        error = RuntimeError("closed-loop metrics are incomplete for a completed run")
        failure = _exception_fields("metrics", error)
        failure_error = error

    wall_time = perf_counter() - started

    def bare_failure_result() -> EpisodeResult:
        assert failure is not None
        return EpisodeResult(
            run_id=identity.run_id,
            scenario_id=identity.scenario_id,
            method=identity.method,
            seed=identity.seed,
            run_completed=run_completed,
            metrics_complete=False,
            failure_stage=failure[0],
            failure_type=failure[1],
            failure_message=failure[2],
            catastrophic_nan_detected=(
                failure_error is not None and _looks_nonfinite(failure_error)
            ),
            catastrophic_not_recovered=not run_completed,
            wall_time_s=wall_time,
        )

    try:
        if base_metrics is not None:
            metric_payload = base_metrics.to_dict()
            metric_payload.update(evaluator_metrics)
            if failure is not None:
                metric_payload["metrics_complete"] = False
            episode_result = EpisodeResult.from_metrics(
                run_id=identity.run_id,
                scenario_id=identity.scenario_id,
                method=identity.method,
                seed=identity.seed,
                metrics=metric_payload,
                run_completed=run_completed,
                failure_stage=None if failure is None else failure[0],
                failure_type=None if failure is None else failure[1],
                failure_message=None if failure is None else failure[2],
                wall_time_s=wall_time,
            )
        else:
            if failure is None:
                error = RuntimeError("no metrics and no recorded failure")
                failure = _exception_fields("metrics", error)
                failure_error = error
            episode_result = bare_failure_result()
    except Exception as exc:
        stage, kind, message = _exception_fields("result_schema", exc)
        if failure is None:
            failure = (stage, kind, message)
            failure_error = exc
        else:
            secondary_errors.append({"stage": stage, "type": kind, "message": message})
        # Drop evaluator overrides first; validated base metrics remain useful.
        if base_metrics is not None:
            try:
                safe_metrics = base_metrics.to_dict()
                safe_metrics["metrics_complete"] = False
                episode_result = EpisodeResult.from_metrics(
                    run_id=identity.run_id,
                    scenario_id=identity.scenario_id,
                    method=identity.method,
                    seed=identity.seed,
                    metrics=safe_metrics,
                    run_completed=run_completed,
                    failure_stage=failure[0],
                    failure_type=failure[1],
                    failure_message=failure[2],
                    wall_time_s=wall_time,
                )
            except Exception:
                episode_result = bare_failure_result()
        else:
            episode_result = bare_failure_result()

    data = replace(
        data,
        failure_stage=None if failure is None else failure[0],
        failure_type=None if failure is None else failure[1],
        failure_message=None if failure is None else failure[2],
    )

    run_payload: dict[str, Any] = {
        "execution": {
            "run_completed": run_completed,
            "control_action_count": len(actions),
            "control_sample_count_including_endpoint": (
                0 if control_trace is None else len(control_trace.time_s)
            ),
            "truth_point_count": len(truth_points),
            "terminal_time_s": None if not measurements else measurements[-1].time_s,
            "secondary_errors": secondary_errors,
        },
        "evaluation_artifacts": evaluator_artifacts,
    }
    if normalized_provenance is not None:
        run_payload["provenance"] = dict(normalized_provenance)
    if runner_config.persist_controller_records:
        run_payload["controller_records"] = [dict(record) for record in records]
    if runner_config.persist_control_trajectory:
        run_payload["control_trajectory"] = [dict(row) for row in control_trajectory]
    if not run_completed:
        point_source = "deduplicated"
        failure_points: Sequence[Mapping[str, Any]] = truth_points
        if not failure_points and raw_truth_points:
            point_source = "raw_trace_construction_fallback"
            failure_points = raw_truth_points
        retained_points = _endpoint_preserving_trace_sample(
            failure_points,
            FAILURE_TRACE_POINT_LIMIT,
        )
        retained_intervals = _endpoint_preserving_trace_sample(
            raw_truth_intervals,
            FAILURE_TRACE_INTERVAL_LIMIT,
        )
        run_payload["truth_trace_points_eval_only"] = [
            dict(point) for point in retained_points
        ]
        run_payload["truth_trace_intervals_eval_only"] = [
            dict(interval) for interval in retained_intervals
        ]
        run_payload["failure_trace_storage_audit"] = {
            "schema_version": FAILURE_TRACE_STORAGE_SCHEMA_VERSION,
            "selection_policy": "endpoint_preserving_even_index_v1",
            "truth_point_source": point_source,
            "truth_point_limit": FAILURE_TRACE_POINT_LIMIT,
            "truth_point_original_count": len(failure_points),
            "truth_point_retained_count": len(retained_points),
            "truth_point_truncated": len(retained_points) < len(failure_points),
            "truth_interval_limit": FAILURE_TRACE_INTERVAL_LIMIT,
            "truth_interval_original_count": len(raw_truth_intervals),
            "truth_interval_retained_count": len(retained_intervals),
            "truth_interval_truncated": (
                len(retained_intervals) < len(raw_truth_intervals)
            ),
        }
    elif runner_config.persist_high_frequency_trace:
        run_payload["truth_trace_points_eval_only"] = [
            dict(point) for point in truth_points
        ]
        run_payload["truth_trace_intervals_eval_only"] = [
            dict(interval) for interval in raw_truth_intervals
        ]

    if immutable_run_artifact_writer is not None:
        immutable_artifacts = immutable_run_artifact_writer(data, episode_result)
        if not isinstance(immutable_artifacts, Mapping) or not all(
            isinstance(key, str) for key in immutable_artifacts
        ):
            raise TypeError(
                "immutable_run_artifact_writer must return a string-keyed mapping"
            )
        overlap = set(run_payload) & set(immutable_artifacts)
        if overlap:
            raise ValueError(
                "immutable run artifacts overlap existing payload keys: "
                f"{sorted(overlap)!r}"
            )
        normalized_artifacts = strict_json_value(immutable_artifacts)
        if not isinstance(normalized_artifacts, Mapping):
            raise TypeError("immutable run artifacts must normalize to an object")
        run_payload.update(dict(normalized_artifacts))

    stored = store.save(
        identity,
        episode_result,
        run_payload,
        replace_existing=runner_config.replace_existing,
    )
    return EpisodeRunOutcome(
        identity=identity,
        episode_result=episode_result,
        stored_run=stored,
        resumed=False,
        evaluation_data=data,
    )


__all__ = [
    "ControllerRecordsGetter",
    "EpisodeEvaluationData",
    "EpisodeEvaluator",
    "EpisodeRunOutcome",
    "EpisodeRunnerConfig",
    "EvaluationContribution",
    "FAILURE_TRACE_INTERVAL_LIMIT",
    "FAILURE_TRACE_POINT_LIMIT",
    "FAILURE_TRACE_STORAGE_SCHEMA_VERSION",
    "ImmutableRunArtifactWriter",
    "MetricFunction",
    "OracleActionCallback",
    "TruthProvider",
    "controller_step_records",
    "oracle_action_from_truth",
    "run_closed_loop_episode",
    "scenario_truth_provider",
    "settling_reference_time",
]
