from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from typing import Any

import cvxpy as cp
import numpy as np
import pytest

from d5freq.controllers.sd_bmpc import (
    SDBMPCController,
    SDBMPCControllerConfig,
    SDControllerState,
)
from d5freq.interfaces import Measurement
from d5freq.identification.model_library import ModeLibrary
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.optimization.joint_prediction import JointARXPredictionModel
from d5freq.optimization.mpc_problem import (
    SDBMPCBounds,
    SDBMPCConfig,
    SDBMPCMode,
)
from d5freq.optimization.solver_utils import (
    SolverOutcome,
    SolverResult,
    solve_cvxpy_problem,
)
from d5freq.utils.config import config_sha256, load_yaml
from d5freq.utils.hashing import sha256_file, sha256_json


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _grid() -> GridFrequencyModel:
    return GridFrequencyModel(
        GridParams(
            f0_hz=50.0,
            M_s=8.0,
            D_pu=1.0,
            T_t_s=0.5,
            T_g_s=0.2,
            R_pu=0.08,
            control_period_s=0.5,
            integration_step_s=0.02,
        )
    )


def _modes(count: int = 2, horizon: int = 3) -> tuple[SDBMPCMode, ...]:
    A = np.eye(10)
    B = np.zeros((10, 2))
    model = JointARXPredictionModel(A=A, B=B)
    quantiles = {lead: 0.0 for lead in range(1, horizon + 1)}
    return tuple(
        SDBMPCMode(
            component_id=index,
            prediction_model=model,
            frequency_q95_hz=quantiles,
            rocof_q95_hz_per_s=quantiles,
            power_q95_pu=quantiles,
            p_output_min_pu=-0.08,
            p_output_max_pu=0.08,
            ramp_down_pu_per_s=0.04,
            ramp_up_pu_per_s=0.04,
        )
        for index in range(count)
    )


def _mpc_config(horizon: int = 3) -> SDBMPCConfig:
    return SDBMPCConfig(
        horizon_steps=horizon,
        sample_time_s=0.5,
        f0_hz=50.0,
        bounds=SDBMPCBounds(
            u_min_pu=(-0.12, -0.08),
            u_max_pu=(0.12, 0.08),
            ramp_pu_per_s=(0.02, 0.04),
            freq_limit_hz=0.5,
            rocof_limit_hz_per_s=0.5,
        ),
    )


@dataclass
class FakeDiagnosticOutput:
    mode_belief: np.ndarray
    belief_entropy: float
    ood_pvalue: float
    diagnostic_state: str

    @property
    def map_mode(self) -> int:
        return int(np.argmax(self.mode_belief))


def _diagnostic_output(
    state: str = "KNOWN",
    *,
    belief: tuple[float, float] = (0.9, 0.1),
    entropy: float = 0.2,
    pvalue: float = 0.5,
) -> FakeDiagnosticOutput:
    return FakeDiagnosticOutput(
        mode_belief=np.asarray(belief, dtype=float),
        belief_entropy=entropy,
        ood_pvalue=pvalue,
        diagnostic_state=state,
    )


class FakeDiagnostic:
    def __init__(self, outputs: list[FakeDiagnosticOutput]) -> None:
        self.outputs = outputs
        self.index = 0
        self.reset_calls = 0
        self.step_calls = 0

    def reset(self) -> None:
        self.reset_calls += 1
        self.index = 0

    def step(self, measurement: Measurement) -> Any:
        self.step_calls += 1
        if self.index >= len(self.outputs):
            raise AssertionError("diagnostic queue exhausted")
        output = self.outputs[self.index]
        self.index += 1
        return output


class FakeEstimator:
    def __init__(self, states: list[np.ndarray] | None = None) -> None:
        self.states = [np.zeros(5)] if states is None else states
        self.reset_calls = 0
        self.update_calls = 0

    def reset_from_measurement(self, measurement: Measurement) -> np.ndarray:
        self.reset_calls += 1
        return np.asarray(self.states[0], dtype=float).copy()

    def update_from_measurement(self, measurement: Measurement) -> np.ndarray:
        self.update_calls += 1
        index = min(self.update_calls, len(self.states) - 1)
        return np.asarray(self.states[index], dtype=float).copy()


class FakeBundle:
    def __init__(self) -> None:
        self.problem = object()
        self.risk_component_ids: tuple[int, ...] = ()
        self.warm_starts: list[np.ndarray | None] = []
        self.precompile_calls: list[str] = []

    def solution_variables(self) -> dict[str, object]:
        return {}

    def set_warm_start(self, value: np.ndarray | None) -> None:
        self.warm_starts.append(None if value is None else np.asarray(value).copy())

    def precompile(self, solver: str) -> float:
        self.precompile_calls.append(solver)
        return 0.001


class FakeCache:
    def __init__(self) -> None:
        self.bundle = FakeBundle()
        self.calls: list[dict[str, object]] = []
        self.clear_calls = 0

    def clear(self) -> None:
        self.clear_calls += 1

    def prepare(
        self,
        initial_state: np.ndarray,
        belief: np.ndarray,
        previous_input: np.ndarray,
        *,
        entropy_normalized: float,
        ood_suspect: bool,
        diagnostic_numerical_issue: bool = False,
    ) -> FakeBundle:
        self.calls.append(
            {
                "initial_state": np.asarray(initial_state).copy(),
                "belief": np.asarray(belief).copy(),
                "previous_input": np.asarray(previous_input).copy(),
                "entropy": entropy_normalized,
                "ood_suspect": ood_suspect,
                "diagnostic_numerical_issue": diagnostic_numerical_issue,
            }
        )
        if ood_suspect or entropy_normalized >= 0.7:
            self.bundle.risk_component_ids = tuple(range(len(belief)))
        else:
            self.bundle.risk_component_ids = (int(np.argmax(belief)),)
        return self.bundle


def _success(
    *,
    horizon: int = 3,
    first: tuple[float, float] = (0.005, 0.01),
    freq_slack: float = 0.0,
    rocof_slack: float = 0.0,
    power_slack: float = 0.0,
) -> SolverResult:
    sequence = np.tile(np.asarray(first, dtype=float)[:, None], (1, horizon))
    return SolverResult(
        status=cp.OPTIMAL,
        outcome=SolverOutcome.SUCCESS,
        solver="FAKE",
        solver_version="1.0",
        total_wall_time_s=0.01,
        objective=1.0,
        values={
            "shared_input": sequence,
            "freq_slack_hz": np.full(horizon, freq_slack),
            "rocof_slack_hz_per_s": np.full(horizon, rocof_slack),
            "power_slack_pu": np.full(horizon, power_slack),
        },
        attempts=(),
        iterations=4,
    )


def _failure(outcome: SolverOutcome) -> SolverResult:
    status = {
        SolverOutcome.TIMEOUT: "timeout",
        SolverOutcome.INACCURATE: cp.OPTIMAL_INACCURATE,
        SolverOutcome.NONFINITE: "nonfinite_solution",
        SolverOutcome.INFEASIBLE: cp.INFEASIBLE,
    }[outcome]
    return SolverResult(
        status=status,
        outcome=outcome,
        solver="FAKE",
        solver_version="1.0",
        total_wall_time_s=0.02,
        objective=None,
        values={},
        attempts=(),
        error_type="InjectedFailure",
        error_message=outcome.value,
    )


class QueuedSolver:
    def __init__(self, results: list[SolverResult]) -> None:
        self.results = results
        self.calls = 0
        self.kwargs: list[dict[str, object]] = []

    def __call__(self, problem: object, **kwargs: object) -> SolverResult:
        self.kwargs.append(dict(kwargs))
        if self.calls >= len(self.results):
            raise AssertionError("solver queue exhausted")
        result = self.results[self.calls]
        self.calls += 1
        return result


class DeadlineAdapterSolver:
    """Drive the real solver adapter with a controlled optimal return delay."""

    def __init__(self, delay_s: float, horizon: int = 3) -> None:
        self.delay_s = delay_s
        self.shared_input = cp.Variable((2, horizon), name="deadline_shared_input")
        self.freq_slack = cp.Variable(horizon, name="deadline_freq_slack")
        self.rocof_slack = cp.Variable(horizon, name="deadline_rocof_slack")
        self.power_slack = cp.Variable(horizon, name="deadline_power_slack")
        self.problem = cp.Problem(
            cp.Minimize(
                cp.sum_squares(self.shared_input)
                + cp.sum_squares(self.freq_slack)
                + cp.sum_squares(self.rocof_slack)
                + cp.sum_squares(self.power_slack)
            )
        )
        self.last_result: SolverResult | None = None

        def controlled_optimal(**_kwargs: object) -> float:
            time.sleep(self.delay_s)
            self.problem._status = cp.OPTIMAL
            self.problem._value = 1.0
            self.problem._solver_stats = type(
                "Stats",
                (),
                {
                    "solver_name": "CLARABEL",
                    "solve_time": self.delay_s,
                    "setup_time": 0.0,
                    "num_iters": 4,
                },
            )()
            self.shared_input.value = np.tile(
                np.asarray((0.005, 0.01))[:, None], (1, horizon)
            )
            self.freq_slack.value = np.zeros(horizon)
            self.rocof_slack.value = np.zeros(horizon)
            self.power_slack.value = np.zeros(horizon)
            return 1.0

        self.problem.solve = controlled_optimal  # type: ignore[method-assign]

    def __call__(self, _problem: object, **kwargs: object) -> SolverResult:
        self.last_result = solve_cvxpy_problem(
            self.problem,
            solution_variables={
                "shared_input": self.shared_input,
                "freq_slack_hz": self.freq_slack,
                "rocof_slack_hz_per_s": self.rocof_slack,
                "power_slack_pu": self.power_slack,
            },
            solver_priority=("CLARABEL",),
            installed_solvers=("CLARABEL",),
            timeout_s=float(kwargs["timeout_s"]),
            warm_start=False,
        )
        return self.last_result


def _measurement(
    time_s: float,
    *,
    previous_action: Any | None = None,
    omega_pu: float = 0.0,
    p_ibr_pu: float = 0.0,
    u_sg_prev_pu: float = 0.0,
    u_ibr_prev_pu: float = 0.0,
) -> Measurement:
    if previous_action is not None:
        u_sg_prev_pu = previous_action.u_sg_pu
        u_ibr_prev_pu = previous_action.u_ibr_pu
    return Measurement(
        time_s=time_s,
        omega_pu=omega_pu,
        p_mech_pu=0.0,
        p_ibr_pu=p_ibr_pu,
        u_sg_prev_pu=u_sg_prev_pu,
        u_ibr_prev_pu=u_ibr_prev_pu,
    )


def _controller(
    diagnostic: FakeDiagnostic,
    solver: QueuedSolver,
    *,
    cache: FakeCache | None = None,
    estimator: FakeEstimator | None = None,
    hold: int = 1,
    blend: int = 2,
    precompile: bool = False,
    solve_timeout_s: float = 0.2,
) -> tuple[SDBMPCController, FakeCache, FakeEstimator]:
    resolved_cache = FakeCache() if cache is None else cache
    resolved_estimator = FakeEstimator() if estimator is None else estimator
    controller = SDBMPCController(
        _grid(),
        _modes(),
        diagnostic,
        mpc_config=_mpc_config(),
        controller_config=SDBMPCControllerConfig(
            recovery_hold_steps=hold,
            return_blend_steps=blend,
            precompile_on_reset=precompile,
            solver_priority=("SCS",),
            solve_timeout_s=solve_timeout_s,
        ),
        estimator=resolved_estimator,
        problem_cache=resolved_cache,
        solve_function=solver,
    )
    return controller, resolved_cache, resolved_estimator


def test_one_diagnostic_and_kalman_update_per_distinct_timestamp() -> None:
    diagnostic = FakeDiagnostic([_diagnostic_output(), _diagnostic_output()])
    solver = QueuedSolver([_success(), _success(first=(0.006, 0.012))])
    controller, _, estimator = _controller(diagnostic, solver)
    initial = _measurement(0.0)
    controller.reset(initial)

    first = controller.act(initial)
    repeated = controller.act(initial)
    assert repeated is first
    assert diagnostic.reset_calls == 1
    assert diagnostic.step_calls == 1
    assert estimator.reset_calls == 1
    assert estimator.update_calls == 0
    assert solver.calls == 1

    controller.act(_measurement(0.5, previous_action=first))
    assert diagnostic.step_calls == 2
    assert estimator.update_calls == 1
    assert solver.calls == 2
    assert len(controller.step_records) == 2


def test_joint_state_uses_current_and_previous_visible_history() -> None:
    estimator = FakeEstimator(
        [
            np.array([0.01, 0.02, 0.03, 0.04, 0.05]),
            np.array([0.11, 0.12, 0.13, 0.14, 0.15]),
        ]
    )
    diagnostic = FakeDiagnostic([_diagnostic_output(), _diagnostic_output()])
    solver = QueuedSolver([_success(), _success(first=(0.006, 0.01))])
    controller, cache, _ = _controller(
        diagnostic, solver, estimator=estimator
    )
    initial = _measurement(
        0.0,
        omega_pu=0.01,
        p_ibr_pu=0.02,
        u_ibr_prev_pu=0.005,
    )
    controller.reset(initial)
    first = controller.act(initial)
    controller.act(
        _measurement(
            0.5,
            previous_action=first,
            omega_pu=0.21,
            p_ibr_pu=0.03,
        )
    )

    state = np.asarray(cache.calls[-1]["initial_state"])
    np.testing.assert_allclose(state[:5], estimator.states[1])
    np.testing.assert_allclose(
        state[5:],
        [0.03, 0.02, first.u_ibr_pu, initial.omega_pu, 1.0],
    )


def test_suspect_selects_robust_mpc_and_all_components() -> None:
    diagnostic = FakeDiagnostic(
        [_diagnostic_output("SUSPECT", belief=(0.99, 0.01), entropy=0.1, pvalue=0.005)]
    )
    solver = QueuedSolver([_success()])
    controller, cache, _ = _controller(diagnostic, solver)
    initial = _measurement(0.0)
    controller.reset(initial)
    action = controller.act(initial)

    assert action.controller_state == SDControllerState.ROBUST_BELIEF_MPC.value
    assert cache.calls[-1]["ood_suspect"] is True
    assert controller.last_step_record.risk_component_ids == (0, 1)
    assert controller.fallback_events == ()


@pytest.mark.parametrize(
    "outcome",
    [
        SolverOutcome.INACCURATE,
        SolverOutcome.TIMEOUT,
        SolverOutcome.NONFINITE,
        SolverOutcome.INFEASIBLE,
    ],
)
def test_every_nonexact_solver_outcome_executes_fresh_lqi_fallback(
    outcome: SolverOutcome,
) -> None:
    diagnostic = FakeDiagnostic([_diagnostic_output()])
    solver = QueuedSolver([_failure(outcome)])
    controller, _, _ = _controller(diagnostic, solver)
    initial = _measurement(0.0, u_ibr_prev_pu=0.04)
    controller.reset(initial)
    action = controller.act(initial)

    assert action.controller_state == SDControllerState.FALLBACK.value
    assert action.u_ibr_pu == pytest.approx(0.02)
    expected = "solver_timeout" if outcome is SolverOutcome.TIMEOUT else f"solver_{outcome.value}"
    assert controller.last_step_record.trigger_reasons == (expected,)
    assert controller.fallback_events[0].fallback_steps == 1


@pytest.mark.parametrize(
    ("delay_s", "timeout_s", "expected_outcome", "expected_state"),
    [
        (0.0, 0.1, SolverOutcome.SUCCESS, SDControllerState.NORMAL_BELIEF_MPC),
        (0.02, 0.005, SolverOutcome.TIMEOUT, SDControllerState.FALLBACK),
    ],
)
def test_solver_deadline_side_controls_mpc_execution_or_fresh_fallback(
    delay_s: float,
    timeout_s: float,
    expected_outcome: SolverOutcome,
    expected_state: SDControllerState,
) -> None:
    adapter = DeadlineAdapterSolver(delay_s)
    diagnostic = FakeDiagnostic([_diagnostic_output()])
    controller, _, _ = _controller(
        diagnostic,
        adapter,  # type: ignore[arg-type]
        solve_timeout_s=timeout_s,
    )
    initial = _measurement(0.0)
    controller.reset(initial)

    action = controller.act(initial)

    assert adapter.last_result is not None
    assert adapter.last_result.outcome is expected_outcome
    assert action.controller_state == expected_state.value
    if expected_outcome is SolverOutcome.SUCCESS:
        assert action.u_sg_pu == pytest.approx(0.005)
        assert action.u_ibr_pu == pytest.approx(0.01)
        assert controller.last_step_record.trigger_reasons == ()
        assert adapter.shared_input.value is not None
    else:
        assert adapter.last_result.status == "timeout"
        assert not adapter.last_result.values
        assert adapter.shared_input.value is None
        assert controller.last_step_record.solver_outcome == "timeout"
        assert controller.last_step_record.trigger_reasons == ("solver_timeout",)
        assert action.u_ibr_pu == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"freq_slack": 0.021}, "frequency_slack"),
        ({"rocof_slack": 0.021}, "rocof_slack"),
        ({"power_slack": 0.021}, "power_slack"),
        ({"first": (0.05, 0.01)}, "solution_constraint_violation"),
    ],
)
def test_optimal_solution_is_rejected_for_slack_or_constraint_violation(
    kwargs: dict[str, object], reason: str
) -> None:
    diagnostic = FakeDiagnostic([_diagnostic_output()])
    solver = QueuedSolver([_success(**kwargs)])  # type: ignore[arg-type]
    controller, _, _ = _controller(diagnostic, solver)
    initial = _measurement(0.0)
    controller.reset(initial)
    action = controller.act(initial)

    assert action.controller_state == SDControllerState.FALLBACK.value
    assert reason in controller.last_step_record.trigger_reasons
    assert action.solver_status == "optimal_rejected"


def test_ood_recovery_hold_blend_and_recurrence_reset_are_exact() -> None:
    diagnostic = FakeDiagnostic(
        [
            _diagnostic_output("OOD_ACTIVE", pvalue=0.001),
            _diagnostic_output("RECOVERY", pvalue=0.2),
            _diagnostic_output("KNOWN"),
            _diagnostic_output("KNOWN"),
            _diagnostic_output("SUSPECT", pvalue=0.005),
            _diagnostic_output("KNOWN"),
            _diagnostic_output("KNOWN"),
            _diagnostic_output("KNOWN"),
        ]
    )
    solver = QueuedSolver(
        [
            _success(first=(0.004, 0.01)),
            _success(first=(0.006, 0.012)),
            _success(first=(0.008, 0.014)),
        ]
    )
    controller, _, _ = _controller(diagnostic, solver, hold=1, blend=2)
    measurement = _measurement(0.0, u_ibr_prev_pu=0.04)
    controller.reset(measurement)

    actions = []
    for index in range(8):
        action = controller.act(measurement)
        actions.append(action)
        if index < 7:
            measurement = _measurement(
                0.5 * (index + 1), previous_action=action
            )

    records = controller.step_records
    assert records[0].trigger_reasons == ("ood_active",)
    assert records[1].trigger_reasons == ("ood_recovery",)
    assert records[2].recovery_hold_count == 1
    assert records[3].recovery_blend_alpha == pytest.approx(0.5)
    assert records[3].controller_state == SDControllerState.FALLBACK.value
    assert records[4].trigger_reasons == ("diagnostic_not_known",)
    assert records[4].recovery_hold_count == 0
    assert records[4].recovery_blend_alpha == 0.0
    assert records[5].recovery_hold_count == 1
    assert records[6].recovery_blend_alpha == pytest.approx(0.5)
    assert records[7].recovery_blend_alpha == pytest.approx(1.0)
    assert records[7].controller_state == SDControllerState.NORMAL_BELIEF_MPC.value
    assert solver.calls == 3

    events = controller.fallback_events
    assert len(events) == 1
    assert events[0].active is False
    assert events[0].started_time_s == 0.0
    assert events[0].ended_time_s == pytest.approx(3.5)
    assert events[0].fallback_steps == 7
    assert "ood_active" in events[0].reasons
    assert "ood_recovery" in events[0].reasons
    assert "diagnostic_not_known" in events[0].reasons
    # Equation (71) is applied at each fallback/blend timestamp, never by a jump.
    assert actions[0].u_ibr_pu == pytest.approx(0.02)
    assert actions[1].u_ibr_pu == pytest.approx(0.0)


def test_runtime_records_and_fallback_events_are_deeply_immutable() -> None:
    diagnostic = FakeDiagnostic([_diagnostic_output("OOD_ACTIVE")])
    controller, _, _ = _controller(diagnostic, QueuedSolver([]))
    initial = _measurement(0.0, u_ibr_prev_pu=-0.04)
    controller.reset(initial)
    controller.act(initial)

    record = controller.last_step_record
    event = controller.fallback_events[0]
    with pytest.raises(ValueError):
        record.mode_belief[0] = 0.0
    with pytest.raises(FrozenInstanceError):
        record.controller_state = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        event.fallback_steps = 99  # type: ignore[misc]
    assert record.to_log_record()["belief_0"] == pytest.approx(0.9)
    assert event.to_log_record()["active"] is True


def test_reset_precompiles_one_all_component_template_outside_act() -> None:
    diagnostic = FakeDiagnostic([_diagnostic_output()])
    solver = QueuedSolver([_success()])
    controller, cache, _ = _controller(
        diagnostic, solver, precompile=True
    )
    initial = _measurement(0.0)
    controller.reset(initial)

    assert cache.clear_calls == 1
    assert cache.calls[0]["ood_suspect"] is True
    np.testing.assert_allclose(cache.calls[0]["belief"], [0.5, 0.5])
    assert cache.bundle.precompile_calls == ["SCS"]
    assert controller.precompile_records[0].success is True
    assert solver.calls == 0

    controller.act(initial)
    assert solver.calls == 1


def test_changed_signals_at_an_already_executed_timestamp_are_rejected() -> None:
    diagnostic = FakeDiagnostic([_diagnostic_output()])
    controller, _, _ = _controller(diagnostic, QueuedSolver([_success()]))
    initial = _measurement(0.0)
    controller.reset(initial)
    controller.act(initial)
    with pytest.raises(ValueError, match="reused"):
        controller.act(_measurement(0.0, omega_pu=0.001))


def test_changed_signals_at_reset_timestamp_are_rejected_before_first_action() -> None:
    diagnostic = FakeDiagnostic([_diagnostic_output()])
    solver = QueuedSolver([_success()])
    controller, _, estimator = _controller(diagnostic, solver)
    initial = _measurement(0.0)
    controller.reset(initial)

    with pytest.raises(ValueError, match="reset timestamp.*reused"):
        controller.act(_measurement(0.0, omega_pu=0.001))

    assert diagnostic.step_calls == 1
    assert estimator.reset_calls == 1
    assert estimator.update_calls == 0
    assert solver.calls == 0


def test_failed_solve_clears_a_previously_bound_warm_start() -> None:
    diagnostic = FakeDiagnostic([_diagnostic_output(), _diagnostic_output()])
    solver = QueuedSolver([_success(first=(0.004, 0.008)), _failure(SolverOutcome.TIMEOUT)])
    controller, cache, _ = _controller(diagnostic, solver)
    initial = _measurement(0.0)
    controller.reset(initial)

    first = controller.act(initial)
    controller.act(_measurement(0.5, previous_action=first))

    assert any(value is not None for value in cache.bundle.warm_starts)
    assert cache.bundle.warm_starts[-1] is None
    assert controller.last_step_record.trigger_reasons == ("solver_timeout",)


def test_project_factory_builds_from_frozen_k6_artifacts_and_binds_hashes() -> None:
    base_path = PROJECT_ROOT / "configs" / "base.yaml"
    mpc_path = PROJECT_ROOT / "configs" / "mpc.yaml"
    library_path = PROJECT_ROOT / "artifacts" / "mode_discovery" / "mode_library.json"
    calibration_path = (
        PROJECT_ROOT
        / "artifacts"
        / "online_diagnosis"
        / "ood_calibration_artifact.json"
    )

    controller = SDBMPCController.from_project_files(
        base_config_path=base_path,
        mpc_config_path=mpc_path,
        mode_library_path=library_path,
        ood_calibration_path=calibration_path,
    )

    provenance = controller.provenance
    assert provenance is not None
    assert tuple(mode.component_id for mode in controller.modes) == tuple(range(6))
    assert controller.mpc_config.horizon_steps == 20
    assert controller.controller_config.solve_timeout_s == pytest.approx(0.2)
    assert provenance.base_config_sha256 == config_sha256(load_yaml(base_path))
    assert provenance.mpc_config_sha256 == config_sha256(load_yaml(mpc_path))
    assert provenance.mode_library_file_sha256 == sha256_file(library_path)
    assert provenance.mode_library_logical_sha256 == sha256_json(
        ModeLibrary.load_json(library_path).to_dict()
    )
    assert provenance.ood_calibration_file_sha256 == sha256_file(calibration_path)


@pytest.mark.parametrize(
    ("hash_field", "message"),
    [
        ("mode_library_sha256", "file SHA-256 mismatch"),
        ("mode_library_logical_sha256", "logical SHA-256 mismatch"),
    ],
)
def test_project_factory_rejects_each_model_library_hash_mismatch(
    hash_field: str,
    message: str,
) -> None:
    calibration_path = (
        PROJECT_ROOT
        / "artifacts"
        / "online_diagnosis"
        / "ood_calibration_artifact.json"
    )
    payload = json.loads(calibration_path.read_text(encoding="utf-8"))
    payload[hash_field] = "0" * 64
    with TemporaryDirectory(prefix="d5freq_controller_test_") as temp_directory:
        tampered_path = Path(temp_directory) / "ood_calibration_tampered.json"
        tampered_path.write_text(
            json.dumps(payload, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match=message):
            SDBMPCController.from_project_files(
                base_config_path=PROJECT_ROOT / "configs" / "base.yaml",
                mpc_config_path=PROJECT_ROOT / "configs" / "mpc.yaml",
                mode_library_path=(
                    PROJECT_ROOT
                    / "artifacts"
                    / "mode_discovery"
                    / "mode_library.json"
                ),
                ood_calibration_path=tampered_path,
            )


def test_controller_package_exports_sd_bmpc_runtime_surface() -> None:
    import d5freq.controllers as controllers

    assert controllers.SDBMPCController is SDBMPCController
    assert controllers.SDControllerState is SDControllerState
    assert controllers.SDBMPCControllerConfig is SDBMPCControllerConfig


def test_controller_module_has_no_evaluation_dependency() -> None:
    import inspect
    import d5freq.controllers.sd_bmpc as module

    source = inspect.getsource(module)
    assert "d5freq.evaluation" not in source
    assert "true_mode" not in source
