from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from d5freq.evaluation.closed_loop_metrics import ClosedLoopMetricConfig
from d5freq.evaluation.closed_loop_metrics import compute_closed_loop_metrics
from d5freq.evaluation.closed_loop_scenarios import load_experiment_protocol
from d5freq.evaluation.closed_loop_runner import (
    EpisodeRunnerConfig,
    EvaluationContribution,
    FAILURE_TRACE_INTERVAL_LIMIT,
    FAILURE_TRACE_POINT_LIMIT,
    _deduplicate_truth_points,
    oracle_action_from_truth,
    run_closed_loop_episode,
    scenario_truth_provider,
    settling_reference_time,
)
from d5freq.evaluation.experiment_store import PerRunExperimentStore, RunIdentity
from d5freq.evaluation.experiment_store import RunIntegrityError
from d5freq.interfaces import ControlAction, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.simulation.disturbances import LoadDisturbanceSpec, LoadEvent
from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator, Scenario
from d5freq.simulation.mode_schedules import PiecewiseConstantModeSchedule


@dataclass(frozen=True)
class _Scenario:
    duration_s: float
    mode_schedule: PiecewiseConstantModeSchedule
    disturbance: LoadDisturbanceSpec = LoadDisturbanceSpec()


class _TraceSimulator:
    def __init__(
        self,
        *,
        step_s: float = 0.1,
        delta_hz: Callable[[float], float] = lambda _time: 0.0,
        fail_step: int | None = None,
    ) -> None:
        self.step_s = step_s
        self.delta_hz = delta_hz
        self.fail_step = fail_step
        self.reset_calls = 0
        self.step_calls = 0
        self.time_s = 0.0
        self.scenario: _Scenario | None = None

    def _measurement(self) -> Measurement:
        return Measurement(
            time_s=self.time_s,
            omega_pu=self.delta_hz(self.time_s) / 50.0,
            p_mech_pu=0.0,
            p_ibr_pu=0.0,
            u_sg_prev_pu=0.0,
            u_ibr_prev_pu=0.0,
        )

    def reset(self, seed: int, scenario: _Scenario) -> Measurement:
        assert isinstance(seed, int)
        self.reset_calls += 1
        self.step_calls = 0
        self.time_s = 0.0
        self.scenario = scenario
        return self._measurement()

    def _point(self, time_s: float) -> dict[str, float | str]:
        assert self.scenario is not None
        return {
            "time_s": time_s,
            "omega_true_pu": self.delta_hz(time_s) / 50.0,
            "p_mech_true_pu": 0.0,
            "p_ibr_true_pu": 0.0,
            "load_disturbance_pu": 0.0,
            "true_mode_eval_only": self.scenario.mode_schedule.mode_at(time_s),
        }

    def step(self, action: ControlAction) -> tuple[Measurement, dict[str, object]]:
        assert isinstance(action, ControlAction)
        if self.fail_step is not None and self.step_calls == self.fail_step:
            raise RuntimeError("injected simulator failure")
        assert self.scenario is not None
        start = self.time_s
        self.time_s = min(start + self.step_s, self.scenario.duration_s)
        self.step_calls += 1
        return self._measurement(), {
            "time_s": self.time_s,
            "true_mode_eval_only": self.scenario.mode_schedule.mode_at(self.time_s),
            "true_trace_points_eval_only": [self._point(start), self._point(self.time_s)],
            "true_trace_intervals_eval_only": [
                {
                    "start_time_s": start,
                    "end_time_s": self.time_s,
                    "true_mode_start_eval_only": self.scenario.mode_schedule.mode_at(start),
                    "true_mode_end_eval_only": self.scenario.mode_schedule.mode_at(self.time_s),
                }
            ],
            "done": self.time_s == self.scenario.duration_s,
        }


class _MeasurementOnlyController:
    def __init__(self, *, fail_act: int | None = None) -> None:
        self.fail_act = fail_act
        self.reset_calls = 0
        self.measurements: list[Measurement] = []

    def reset(self, initial_measurement: Measurement) -> None:
        assert type(initial_measurement) is Measurement
        self.reset_calls += 1
        self.measurements.clear()

    def act(self, measurement: Measurement) -> ControlAction:
        # This signature intentionally cannot receive a truth/scenario argument.
        assert type(measurement) is Measurement
        if self.fail_act is not None and len(self.measurements) == self.fail_act:
            raise RuntimeError("injected controller failure")
        self.measurements.append(measurement)
        return ControlAction(0.0, 0.0, controller_state="NORMAL", solver_status="optimal")


class _NonSolverController(_MeasurementOnlyController):
    def __init__(self, solver_status: str) -> None:
        super().__init__()
        self.solver_status = solver_status

    def act(self, measurement: Measurement) -> ControlAction:
        assert type(measurement) is Measurement
        self.measurements.append(measurement)
        return ControlAction(
            0.0,
            0.0,
            controller_state="B0_LQI",
            solver_status=self.solver_status,
        )


class _OracleController:
    def __init__(self) -> None:
        self.labels: list[str] = []
        self.inner_controller = SimpleNamespace(step_records=[])

    def reset(self, initial_measurement: Measurement) -> None:
        assert isinstance(initial_measurement, Measurement)
        self.labels.clear()
        self.inner_controller.step_records.clear()

    def act(self, measurement: Measurement) -> ControlAction:
        raise AssertionError("ordinary act must never be used for explicit Oracle")

    def act_evaluation_only(
        self,
        measurement: Measurement,
        *,
        true_mode_eval_only: str,
    ) -> ControlAction:
        self.labels.append(true_mode_eval_only)
        self.inner_controller.step_records.append(
            {
                "time_s": measurement.time_s,
                "controller_state": "ORACLE_ARX_MPC_EVALUATION_ONLY",
                "diagnostic_state": "KNOWN",
                "belief_0": 1.0,
                "map_mode": 0,
                "belief_entropy": 0.0,
                "ood_pvalue": 1.0,
                "solver_status": "optimal",
                "solver_outcome": "success",
                "solve_time_s": 0.01,
                "max_freq_slack_hz": 0.0,
                "max_rocof_slack_hz_per_s": 0.0,
                "max_power_slack_pu": 0.0,
            }
        )
        return ControlAction(
            0.0,
            0.0,
            controller_state="ORACLE_ARX_MPC_EVALUATION_ONLY",
            solver_status="optimal",
            solve_time_s=0.01,
        )


def _run_config(duration_s: float, **overrides: object) -> EpisodeRunnerConfig:
    values: dict[str, object] = {
        "expected_duration_s": duration_s,
        "persist_high_frequency_trace": True,
    }
    values.update(overrides)
    return EpisodeRunnerConfig(**values)


def test_nearby_truth_points_preserve_a_real_discontinuity() -> None:
    left = {"time_s": 1.0 - 1e-14, "load_disturbance_pu": 0.1}
    right = {"time_s": 1.0, "load_disturbance_pu": 0.2}

    retained = _deduplicate_truth_points((left, right))

    assert retained == (left, right)
    with pytest.raises(ValueError, match="inconsistent"):
        _deduplicate_truth_points((right, {**right, "load_disturbance_pu": 0.3}))


def test_ordinary_controller_receives_measurement_only_and_endpoint_closes_integral(tmp_path) -> None:
    duration = 0.25
    scenario = _Scenario(duration, PiecewiseConstantModeSchedule("nominal"))
    simulator = _TraceSimulator(delta_hz=lambda time: time)
    controller = _MeasurementOnlyController()
    identity = RunIdentity("endpoint", "scenario", "P", 3)

    outcome = run_closed_loop_episode(
        identity=identity,
        simulator=simulator,
        scenario=scenario,
        controller=controller,
        metric_config=ClosedLoopMetricConfig(
            settling_band_hz=1.0,
            safety_frequency_limit_hz=2.0,
        ),
        store=PerRunExperimentStore(tmp_path),
        runner_config=_run_config(duration),
    )

    assert outcome.episode_result.run_completed
    assert outcome.episode_result.freq_iae == pytest.approx(duration**2 / 2.0)
    assert outcome.episode_result.sg_command_violation_count == 0
    assert outcome.episode_result.ibr_command_violation_count == 0
    assert len(controller.measurements) == 3
    assert outcome.evaluation_data is not None
    assert outcome.evaluation_data.high_frequency_truth is not None
    assert outcome.evaluation_data.high_frequency_truth.time_s.tolist() == [
        0.0,
        0.1,
        0.2,
        0.25,
    ]
    assert outcome.evaluation_data.control_trace is not None
    assert outcome.evaluation_data.control_trace.time_s[-1] == 0.25
    trajectory = outcome.stored_run.run_payload["control_trajectory"]
    assert trajectory[-1]["terminal_endpoint"] is True
    assert trajectory[-1]["solver_outcome"] == "not_run"


def test_oracle_truth_requires_explicit_callbacks_and_reads_inner_step_records(tmp_path) -> None:
    scenario = _Scenario(
        0.3,
        PiecewiseConstantModeSchedule.from_pairs("nominal", [(0.2, "weak")]),
    )
    oracle = _OracleController()
    seen_by_evaluator: list[tuple[str, ...]] = []

    def evaluator(data: object) -> EvaluationContribution:
        labels = tuple(
            str(point["true_mode_eval_only"])
            for point in data.truth_points_eval_only  # type: ignore[attr-defined]
        )
        seen_by_evaluator.append(labels)
        return EvaluationContribution(
            metric_overrides={"mode_accuracy": 1.0},
            artifacts={"truth_labels": labels},
        )

    def guarded_oracle_action(
        controller: object,
        measurement: Measurement,
        truth: dict[str, object],
    ) -> ControlAction:
        assert set(truth) == {"time_s", "true_mode_eval_only"}
        return oracle_action_from_truth(controller, measurement, truth)

    outcome = run_closed_loop_episode(
        identity=RunIdentity("oracle", "scenario", "B4", 1),
        simulator=_TraceSimulator(),
        scenario=scenario,
        controller=oracle,
        metric_config=ClosedLoopMetricConfig(),
        store=PerRunExperimentStore(tmp_path),
        runner_config=_run_config(0.3),
        oracle_action_callback=guarded_oracle_action,
        truth_provider=scenario_truth_provider,
        evaluators=(evaluator,),
    )

    assert oracle.labels == ["nominal", "nominal", "weak"]
    assert outcome.episode_result.mode_accuracy == 1.0
    assert outcome.episode_result.solver_attempt_count == 3
    assert seen_by_evaluator and "weak" in seen_by_evaluator[0]
    assert outcome.stored_run.run_payload["control_trajectory"][0]["mode_belief"] == [1.0]

    with pytest.raises(ValueError, match="supplied together"):
        run_closed_loop_episode(
            identity=RunIdentity("bad-oracle", "scenario", "B4", 1),
            simulator=_TraceSimulator(),
            scenario=scenario,
            controller=oracle,
            metric_config=ClosedLoopMetricConfig(),
            store=PerRunExperimentStore(tmp_path / "bad"),
            runner_config=_run_config(0.3),
            truth_provider=scenario_truth_provider,
        )


@pytest.mark.parametrize(
    ("kind", "expected_stage", "completed"),
    [
        ("controller", "controller_act", False),
        ("simulator", "simulator_step", False),
        ("metrics", "metrics", True),
    ],
)
def test_any_episode_stage_exception_is_atomically_retained(
    tmp_path,
    kind: str,
    expected_stage: str,
    completed: bool,
) -> None:
    scenario = _Scenario(0.3, PiecewiseConstantModeSchedule("nominal"))
    simulator = _TraceSimulator(fail_step=1 if kind == "simulator" else None)
    controller = _MeasurementOnlyController(fail_act=1 if kind == "controller" else None)

    def metric_failure(*_args: object, **_kwargs: object) -> object:
        raise FloatingPointError("injected non-finite metric")

    identity = RunIdentity(f"failure-{kind}", "scenario", "P", 4)
    outcome = run_closed_loop_episode(
        identity=identity,
        simulator=simulator,
        scenario=scenario,
        controller=controller,
        metric_config=ClosedLoopMetricConfig(),
        store=PerRunExperimentStore(tmp_path),
        runner_config=_run_config(0.3),
        metric_function=(
            metric_failure if kind == "metrics" else compute_closed_loop_metrics
        ),  # type: ignore[arg-type]
    )

    result = outcome.episode_result
    assert result.run_completed is completed
    assert not result.metrics_complete
    assert not result.scientific_success
    assert result.failure_stage == expected_stage
    stored = PerRunExperimentStore(tmp_path).load(identity)
    assert stored is not None
    assert stored.episode_result == result
    if not completed:
        assert result.catastrophic_not_recovered
        assert result.freq_iae == 0.0
        assert stored.run_payload["truth_trace_points_eval_only"]
    if kind == "metrics":
        assert result.catastrophic_nan_detected


def test_late_incomplete_run_stores_bounded_endpoint_preserving_truth_prefix(
    tmp_path,
) -> None:
    successful_steps = FAILURE_TRACE_POINT_LIMIT + 104
    step_s = 0.001
    scenario = _Scenario(3.0, PiecewiseConstantModeSchedule("nominal"))
    simulator = _TraceSimulator(step_s=step_s, fail_step=successful_steps)
    identity = RunIdentity("late-bounded-failure", "scenario", "P", 8)

    outcome = run_closed_loop_episode(
        identity=identity,
        simulator=simulator,
        scenario=scenario,
        controller=_MeasurementOnlyController(),
        metric_config=ClosedLoopMetricConfig(),
        store=PerRunExperimentStore(tmp_path),
        runner_config=EpisodeRunnerConfig(
            expected_duration_s=scenario.duration_s,
            persist_high_frequency_trace=True,
        ),
    )

    assert not outcome.episode_result.run_completed
    assert outcome.episode_result.failure_stage == "simulator_step"
    payload = outcome.stored_run.run_payload
    points = payload["truth_trace_points_eval_only"]
    intervals = payload["truth_trace_intervals_eval_only"]
    audit = payload["failure_trace_storage_audit"]
    assert len(points) == FAILURE_TRACE_POINT_LIMIT
    assert len(intervals) == FAILURE_TRACE_INTERVAL_LIMIT
    assert points[0]["time_s"] == 0.0
    assert points[-1]["time_s"] == pytest.approx(successful_steps * step_s)
    assert intervals[0]["start_time_s"] == 0.0
    assert intervals[-1]["end_time_s"] == pytest.approx(
        successful_steps * step_s
    )
    assert audit == {
        "schema_version": "d5freq.failure_trace_storage.v1",
        "selection_policy": "endpoint_preserving_even_index_v1",
        "truth_point_source": "deduplicated",
        "truth_point_limit": FAILURE_TRACE_POINT_LIMIT,
        "truth_point_original_count": successful_steps + 1,
        "truth_point_retained_count": FAILURE_TRACE_POINT_LIMIT,
        "truth_point_truncated": True,
        "truth_interval_limit": FAILURE_TRACE_INTERVAL_LIMIT,
        "truth_interval_original_count": successful_steps,
        "truth_interval_retained_count": FAILURE_TRACE_INTERVAL_LIMIT,
        "truth_interval_truncated": True,
    }


def test_verified_resume_skips_controller_and_simulator_reexecution(tmp_path) -> None:
    scenario = _Scenario(0.2, PiecewiseConstantModeSchedule("nominal"))
    simulator = _TraceSimulator()
    controller = _MeasurementOnlyController()
    identity = RunIdentity("resume", "scenario", "P", 9)
    store = PerRunExperimentStore(tmp_path)
    kwargs = dict(
        identity=identity,
        simulator=simulator,
        scenario=scenario,
        controller=controller,
        metric_config=ClosedLoopMetricConfig(),
        store=store,
        runner_config=_run_config(0.2),
    )

    first = run_closed_loop_episode(**kwargs)
    calls = (simulator.reset_calls, simulator.step_calls, controller.reset_calls)
    second = run_closed_loop_episode(**kwargs)

    assert not first.resumed
    assert second.resumed
    assert second.evaluation_data is None
    assert second.episode_result == first.episode_result
    assert (simulator.reset_calls, simulator.step_calls, controller.reset_calls) == calls


@pytest.mark.parametrize("solver_status", ["fallback_lqi", "not_applicable"])
def test_non_solver_statuses_do_not_fabricate_solver_attempts(
    tmp_path, solver_status: str
) -> None:
    scenario = _Scenario(0.2, PiecewiseConstantModeSchedule("nominal"))
    outcome = run_closed_loop_episode(
        identity=RunIdentity(f"non-solver-{solver_status}", "scenario", "B0", 1),
        simulator=_TraceSimulator(),
        scenario=scenario,
        controller=_NonSolverController(solver_status),
        metric_config=ClosedLoopMetricConfig(),
        store=PerRunExperimentStore(tmp_path / solver_status),
        runner_config=_run_config(0.2),
    )

    result = outcome.episode_result
    assert result.solver_attempt_count == 0
    assert result.solver_fail_count == 0
    assert result.solver_timeout_count == 0
    assert result.solver_infeasible_count == 0
    assert result.solver_inaccurate_count == 0
    assert result.solve_time_mean_s is None
    assert result.solve_time_p95_s is None
    assert result.solve_time_max_s is None
    assert result.solver_timeout_rate is None
    assert result.solver_infeasible_rate is None
    assert result.solver_inaccurate_rate is None
    assert result.max_freq_slack_hz is None
    assert result.max_rocof_slack_hz_s is None
    assert result.max_power_slack_pu is None


def test_resume_requires_exact_requested_run_provenance(tmp_path) -> None:
    scenario = _Scenario(0.2, PiecewiseConstantModeSchedule("nominal"))
    simulator = _TraceSimulator()
    controller = _MeasurementOnlyController()
    identity = RunIdentity("provenance-resume", "scenario", "P", 9)
    kwargs = dict(
        identity=identity,
        simulator=simulator,
        scenario=scenario,
        controller=controller,
        metric_config=ClosedLoopMetricConfig(),
        store=PerRunExperimentStore(tmp_path),
        runner_config=_run_config(0.2),
    )
    expected = {
        "artifact_state_sha256": "a" * 64,
        "code_sha256": "b" * 64,
        "configs": {"base": "c" * 64},
    }

    first = run_closed_loop_episode(**kwargs, run_provenance=expected)
    calls = (simulator.reset_calls, simulator.step_calls, controller.reset_calls)
    resumed = run_closed_loop_episode(**kwargs, run_provenance=expected)

    assert first.stored_run.run_payload["provenance"] == expected
    assert resumed.resumed
    assert (simulator.reset_calls, simulator.step_calls, controller.reset_calls) == calls

    changed = {**expected, "code_sha256": "d" * 64}
    with pytest.raises(RunIntegrityError, match="provenance differs"):
        run_closed_loop_episode(**kwargs, run_provenance=changed)
    assert (simulator.reset_calls, simulator.step_calls, controller.reset_calls) == calls


def test_runner_integrates_real_hybrid_simulator_truth_protocol(tmp_path) -> None:
    grid = GridFrequencyModel(
        GridParams(50.0, 8.0, 1.0, 0.5, 0.2, 0.08, 0.1, 0.01)
    )
    mode = IBRModeParams(
        name="nominal",
        command_gain=1.0,
        frequency_gain=4.0,
        command_filter_time_s=0.1,
        power_response_time_s=0.2,
        delay_s=0.0,
        p_max_pos_pu=0.08,
        p_max_neg_pu=0.08,
        ramp_up_pu_per_s=0.05,
        ramp_down_pu_per_s=0.05,
        deadband_pu=0.0005,
    )
    scenario = Scenario(
        PiecewiseConstantModeSchedule("nominal"),
        duration_s=0.2,
    )
    outcome = run_closed_loop_episode(
        identity=RunIdentity("real-sim", "short", "B0", 2),
        simulator=HiddenModeFrequencySimulator(grid, {"nominal": mode}),
        scenario=scenario,
        controller=_MeasurementOnlyController(),
        metric_config=ClosedLoopMetricConfig(),
        store=PerRunExperimentStore(tmp_path),
        runner_config=_run_config(0.2),
    )

    assert outcome.episode_result.run_completed
    assert outcome.episode_result.scientific_success
    assert outcome.evaluation_data is not None
    assert outcome.evaluation_data.high_frequency_truth is not None
    assert outcome.evaluation_data.high_frequency_truth.time_s[0] == 0.0
    assert outcome.evaluation_data.high_frequency_truth.time_s[-1] == 0.2
    assert outcome.evaluation_data.control_trace is not None
    assert outcome.evaluation_data.control_trace.time_s.tolist() == [0.0, 0.1, 0.2]


def test_settling_reference_uses_last_deterministic_load_or_mode_event() -> None:
    scenario = _Scenario(
        180.0,
        PiecewiseConstantModeSchedule.from_pairs(
            "nominal", [(60.0, "weak"), (135.0, "nominal")]
        ),
        LoadDisturbanceSpec(
            events=(LoadEvent(20.0, 0.02, end_time_s=90.0),)
        ),
    )
    no_event = _Scenario(180.0, PiecewiseConstantModeSchedule("nominal"))

    assert settling_reference_time(scenario) == 135.0
    assert settling_reference_time(no_event) == 0.0


def test_frozen_s1_s5_s9_settling_reference_times_match_preregistered_events() -> None:
    root = Path(__file__).resolve().parents[1]
    protocol = load_experiment_protocol(root / "configs" / "experiments.yaml")

    assert settling_reference_time(protocol.build_scenario("S1_step_pos_002")) == 60.0
    assert settling_reference_time(
        protocol.build_scenario("S5_multi_switch_stochastic")
    ) == 135.0
    assert settling_reference_time(
        protocol.build_scenario("S9_compound_unavailable_double_step")
    ) == 90.0
