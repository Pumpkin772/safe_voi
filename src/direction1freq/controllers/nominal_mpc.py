"""True rolling finite-horizon nominal MPC for Phase E."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from time import perf_counter

import cvxpy as cp
import numpy as np
from scipy.signal import cont2discrete

from direction1freq.models.plant_a_v2 import PublicObservationV2, TwoAreaPlantAV2
from direction1freq.controllers.mpc_transaction import (
    SolverAttempt,
    SolverOutcome,
    assert_applied_action,
    classify_solver_attempt,
)


@dataclass(frozen=True, slots=True)
class MPCDiagnostics:
    solver_status: str
    solved: bool
    solve_time_s: float
    objective: float
    primal_residual: float
    dual_residual: float
    iterations: int
    warm_started: bool
    fallback_reason: str
    prediction_horizon: int
    first_action_pu: np.ndarray
    predicted_states: np.ndarray
    predicted_actions: np.ndarray
    primary_status: str = "not_run"
    secondary_status: str = "not_run"
    primary_primal_residual: float = float("nan")
    primary_dual_residual: float = float("nan")
    secondary_primal_residual: float = float("nan")
    secondary_dual_residual: float = float("nan")
    mathematical_infeasible: bool = False
    numerical_failure: bool = False
    terminal_reject: bool = False
    restoration_used: bool = False
    backup_used: bool = False
    previous_applied_action: np.ndarray = field(
        default_factory=lambda: np.zeros(4)
    )
    previous_model_action: np.ndarray = field(default_factory=lambda: np.zeros(4))
    applied_action_pu: np.ndarray = field(default_factory=lambda: np.zeros(4))
    history_match: bool = True
    consecutive_backup_count: int = 0
    accepted_inaccurate: bool = False
    hard_constraint_residual: float = float("nan")


def _zoh(
    a: np.ndarray, b: np.ndarray, e: np.ndarray, period_s: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    combined = np.column_stack((b, e))
    dummy_c = np.zeros((1, a.shape[0]))
    dummy_d = np.zeros((1, combined.shape[1]))
    ad, combined_d, _, _, _ = cont2discrete(
        (a, combined, dummy_c, dummy_d), period_s, method="zoh"
    )
    return np.asarray(ad), np.asarray(combined_d[:, : b.shape[1]]), np.asarray(combined_d[:, b.shape[1] :])


class FiniteHorizonMPC:
    """Parameterised QP with explicit state/action sequences and dynamics."""

    def __init__(
        self,
        period_s: float = 4.0,
        horizon: int = 6,
        nominal_delay_s: float = 0.2,
        solver_tolerance: float = 1e-6,
        reference_weight: float = 0.0,
        resource_constraint_start_stage: int = 0,
        frequency_limit_hz: float = 0.80,
        ace_limit_pu: float = 0.30,
        tie_limit_pu: float = 0.15,
        secondary_solver: str | None = "CLARABEL",
        accepted_solution_residual: float = 1e-5,
    ) -> None:
        self.period_s = float(period_s)
        self.horizon = int(horizon)
        self.nominal_delay_s = float(nominal_delay_s)
        self.solver_tolerance = float(solver_tolerance)
        self.reference_weight = float(reference_weight)
        self.resource_constraint_start_stage = int(resource_constraint_start_stage)
        self.frequency_limit_hz = float(frequency_limit_hz)
        self.ace_limit_pu = float(ace_limit_pu)
        self.tie_limit_pu = float(tie_limit_pu)
        self.secondary_solver = secondary_solver
        self.accepted_solution_residual = float(accepted_solution_residual)
        self.plant = TwoAreaPlantAV2()
        a, b, self.c_ace, e = self.plant.linear_continuous_model_separate()
        self.ad, self.bd, self.ed = _zoh(a, b, e, self.period_s)
        _, self.b_current_default, _ = _zoh(a, b, e, self.period_s - self.nominal_delay_s)
        self.b_previous_default = self.bd - self.b_current_default
        self.previous_action = np.zeros(4)
        self._has_solution = False
        self._build_problem()

    def delayed_input_matrices(self, delay_s: float) -> tuple[np.ndarray, np.ndarray]:
        if not 0.0 <= delay_s < self.period_s:
            raise ValueError("delay must be shorter than the control period")
        a, b, _c, e = self.plant.linear_continuous_model_separate()
        _, current, _ = _zoh(a, b, e, self.period_s - delay_s)
        return current, self.bd - current

    def _build_problem(self) -> None:
        n, m, horizon = 9, 4, self.horizon
        self.x = cp.Variable((n, horizon + 1), name="predicted_state")
        self.u = cp.Variable((m, horizon), name="decision_action")
        self.slack_f = cp.Variable((2, horizon + 1), nonneg=True, name="frequency_slack")
        self.slack_ace = cp.Variable((2, horizon + 1), nonneg=True, name="ace_slack")
        self.slack_tie = cp.Variable(horizon + 1, nonneg=True, name="tie_slack")
        self.x0 = cp.Parameter(n, name="current_state")
        self.previous = cp.Parameter(m, name="previous_action")
        self.load_estimate = cp.Parameter(2, name="causal_load_estimate")
        self.input_lower = cp.Parameter(m, name="input_lower")
        self.input_upper = cp.Parameter(m, name="input_upper")
        self.bess_lower = cp.Parameter(2, name="bess_total_lower")
        self.bess_upper = cp.Parameter(2, name="bess_total_upper")
        self.command_slew = cp.Parameter(m, nonneg=True, name="command_slew")
        self.action_reference = cp.Parameter(m, name="safe_action_reference")
        # Delay is fixed when an optimizer instance is constructed.  Keeping
        # these matrices constant makes the online QP DPP-compliant; Oracle
        # caches one optimizer per observed current delay.
        self.b_current = cp.Constant(self.b_current_default)
        self.b_previous = cp.Constant(self.b_previous_default)

        constraints: list[cp.Constraint] = [self.x[:, 0] == self.x0]
        objective = 0.0
        frequency_gain = self.plant.parameters.nominal_frequency_hz
        pfr_gain = self.plant.parameters.bess.pfr_gain_pu_power_per_pu_frequency
        for stage in range(horizon):
            previous = self.previous if stage == 0 else self.u[:, stage - 1]
            constraints.append(
                self.x[:, stage + 1]
                == self.ad @ self.x[:, stage]
                + self.b_current @ self.u[:, stage]
                + self.b_previous @ previous
                + self.ed @ self.load_estimate
            )
            constraints.extend([
                self.u[:, stage] >= self.input_lower,
                self.u[:, stage] <= self.input_upper,
                cp.abs(self.u[:, stage] - previous) <= self.command_slew,
            ])
            total_bess = cp.hstack([
                self.u[1, stage] - pfr_gain * self.x[0, stage],
                self.u[3, stage] - pfr_gain * self.x[1, stage],
            ])
            constraints.extend([total_bess >= self.bess_lower, total_bess <= self.bess_upper])
            objective += self._stage_cost(self.x[:, stage], self.u[:, stage], previous)
            objective += self.reference_weight * cp.sum_squares(
                self.u[:, stage] - self.action_reference
            )
        objective += 8.0 * self._state_cost(self.x[:, horizon])
        for stage in range(horizon + 1):
            frequency_hz = frequency_gain * self.x[:2, stage]
            ace = self.c_ace @ self.x[:, stage]
            constraints.extend([
                cp.abs(frequency_hz) <= self.frequency_limit_hz + self.slack_f[:, stage],
                cp.abs(ace) <= self.ace_limit_pu + self.slack_ace[:, stage],
                cp.abs(self.x[2, stage]) <= self.tie_limit_pu + self.slack_tie[stage],
                self.x[5:7, stage] >= np.asarray(self.plant.parameters.sg_power_lower_pu),
                self.x[5:7, stage] <= np.asarray(self.plant.parameters.sg_power_upper_pu),
            ])
            if stage >= self.resource_constraint_start_stage:
                constraints.extend([
                    self.x[7:9, stage] >= self.bess_lower,
                    self.x[7:9, stage] <= self.bess_upper,
                ])
        objective += 1e5 * (
            cp.sum_squares(self.slack_f) + cp.sum_squares(self.slack_ace) + cp.sum_squares(self.slack_tie)
        )
        # Terminal BESS-independent SG backup neighborhood.
        constraints.extend([
            cp.abs(frequency_gain * self.x[:2, horizon]) <= 0.30 + self.slack_f[:, horizon],
            cp.abs(self.c_ace @ self.x[:, horizon]) <= 0.15 + self.slack_ace[:, horizon],
        ])
        self.problem = cp.Problem(cp.Minimize(objective), constraints)

    def _state_cost(self, state) -> cp.Expression:
        frequency_hz = self.plant.parameters.nominal_frequency_hz * state[:2]
        ace = self.c_ace @ state
        return (
            120.0 * cp.sum_squares(frequency_hz)
            + 400.0 * cp.sum_squares(ace)
            + 180.0 * cp.square(state[2])
            + 2.0 * cp.sum_squares(state[5:9])
        )

    def _stage_cost(self, state, action, previous) -> cp.Expression:
        return self._state_cost(state) + 0.8 * cp.sum_squares(action) + 2.0 * cp.sum_squares(action - previous)

    def reset(self) -> None:
        self.previous_action = np.zeros(4)
        self._has_solution = False
        self.x.value = None
        self.u.value = None

    def commit_applied_action(self, applied_action: np.ndarray) -> None:
        """Commit the command selected by the supervisor, never a proposal."""

        self.previous_action = assert_applied_action(applied_action, 4)

    def _constraint_residual(self) -> float:
        violations: list[float] = []
        for constraint in self.problem.constraints:
            try:
                violation = np.asarray(constraint.violation(), dtype=float)
            except (ValueError, TypeError):
                continue
            if violation.size and np.all(np.isfinite(violation)):
                violations.append(float(np.max(np.abs(violation))))
        return max(violations, default=float("inf"))

    def _attempt_from_current_problem(
        self,
        solver: str,
        raw_status: str,
        objective: float | None,
        error: str = "",
    ) -> SolverAttempt:
        primal = self._constraint_residual() if not error else float("inf")
        dual = float("nan")
        iterations = 0
        stats = self.problem.solver_stats
        if stats is not None:
            iterations = int(stats.num_iters or 0)
            extra = stats.extra_stats
            info = getattr(extra, "info", None)
            if info is not None:
                native_primal = float(getattr(info, "prim_res", float("nan")))
                native_dual = float(getattr(info, "dual_res", float("nan")))
                if np.isfinite(native_primal):
                    primal = max(primal, native_primal)
                dual = native_dual
        outcome, accepted = classify_solver_attempt(
            raw_status, primal, dual, self.accepted_solution_residual
        )
        if error:
            outcome, accepted = SolverOutcome.NUMERICAL_FAILURE, False
        return SolverAttempt(
            solver=solver,
            raw_status=raw_status,
            outcome=outcome,
            accepted=accepted,
            objective=float(objective) if objective is not None else float("nan"),
            primal_residual=primal,
            dual_residual=dual,
            iterations=iterations,
            error=error,
        )

    def propose(
        self,
        estimated_state: np.ndarray,
        causal_load_estimate: np.ndarray,
        input_lower: np.ndarray,
        input_upper: np.ndarray,
        bess_lower: np.ndarray,
        bess_upper: np.ndarray,
        command_slew: np.ndarray,
        delay_s: float | None = None,
        action_reference: np.ndarray | None = None,
    ) -> tuple[np.ndarray, MPCDiagnostics]:
        """Solve without mutating the applied-action or delay history."""

        model_previous = self.previous_action.copy()
        self.x0.value = np.asarray(estimated_state, dtype=float)
        self.previous.value = model_previous
        self.load_estimate.value = np.asarray(causal_load_estimate, dtype=float)
        self.input_lower.value = np.asarray(input_lower, dtype=float)
        self.input_upper.value = np.asarray(input_upper, dtype=float)
        self.bess_lower.value = np.asarray(bess_lower, dtype=float)
        self.bess_upper.value = np.asarray(bess_upper, dtype=float)
        self.command_slew.value = np.asarray(command_slew, dtype=float)
        self.action_reference.value = (
            np.zeros(4)
            if action_reference is None
            else np.asarray(action_reference, dtype=float)
        )
        if delay_s is not None and abs(float(delay_s) - self.nominal_delay_s) > 1e-9:
            raise ValueError(
                "construct a delay-specific optimizer instead of changing delay online"
            )
        started = perf_counter()
        warm_started = self._has_solution
        primary_error = ""
        try:
            primary_objective = self.problem.solve(
                solver=cp.OSQP,
                warm_start=True,
                eps_abs=self.solver_tolerance,
                eps_rel=self.solver_tolerance,
                max_iter=20_000,
                polishing=True,
                verbose=False,
            )
            primary_status = str(self.problem.status)
        except Exception as error:  # retained as structured evidence
            primary_objective = float("nan")
            primary_status = f"exception:{type(error).__name__}"
            primary_error = str(error)
        primary = self._attempt_from_current_problem(
            "OSQP", primary_status, primary_objective, primary_error
        )

        secondary = SolverAttempt(
            solver=self.secondary_solver or "none",
            raw_status="not_run",
            outcome=SolverOutcome.NOT_RUN,
            accepted=False,
            objective=float("nan"),
            primal_residual=float("nan"),
            dual_residual=float("nan"),
            iterations=0,
        )
        if not primary.accepted and self.secondary_solver == "CLARABEL":
            secondary_error = ""
            try:
                secondary_objective = self.problem.solve(
                    solver=cp.CLARABEL,
                    warm_start=True,
                    tol_gap_abs=self.solver_tolerance,
                    tol_gap_rel=self.solver_tolerance,
                    tol_feas=self.solver_tolerance,
                    max_iter=1000,
                    verbose=False,
                )
                secondary_status = str(self.problem.status)
            except Exception as error:
                secondary_objective = float("nan")
                secondary_status = f"exception:{type(error).__name__}"
                secondary_error = str(error)
            secondary = self._attempt_from_current_problem(
                "CLARABEL",
                secondary_status,
                secondary_objective,
                secondary_error,
            )

        accepted_attempt = (
            primary
            if primary.accepted or secondary.outcome is SolverOutcome.NOT_RUN
            else secondary
        )
        solved = bool(accepted_attempt.accepted and self.u.value is not None)
        action = (
            np.asarray(self.u.value[:, 0]).ravel().copy()
            if solved
            else np.zeros(4)
        )
        predicted_states = (
            np.asarray(self.x.value).copy()
            if solved
            else np.full((9, self.horizon + 1), np.nan)
        )
        predicted_actions = (
            np.asarray(self.u.value).copy()
            if solved
            else np.full((4, self.horizon), np.nan)
        )
        elapsed = perf_counter() - started
        if solved:
            self._has_solution = True
        final_status = (
            str(accepted_attempt.outcome)
            if solved
            else (
                f"secondary_{secondary.outcome}"
                if secondary.outcome is not SolverOutcome.NOT_RUN
                else str(primary.outcome)
            )
        )
        attempts = [primary]
        if secondary.outcome is not SolverOutcome.NOT_RUN:
            attempts.append(secondary)
        mathematical_infeasible = bool(
            not solved and any(item.mathematical_infeasible for item in attempts)
        )
        numerical_failure = bool(
            not solved and any(item.numerical_failure for item in attempts)
        )
        fallback_reason = "" if solved else ";".join(
            f"{item.solver}:{item.outcome}:{item.error}" for item in attempts
        )
        diagnostic = MPCDiagnostics(
            solver_status=final_status,
            solved=solved,
            solve_time_s=elapsed,
            objective=accepted_attempt.objective,
            primal_residual=accepted_attempt.primal_residual,
            dual_residual=accepted_attempt.dual_residual,
            iterations=accepted_attempt.iterations,
            warm_started=warm_started,
            fallback_reason=fallback_reason,
            prediction_horizon=self.horizon,
            first_action_pu=action.copy(),
            predicted_states=predicted_states,
            predicted_actions=predicted_actions,
            primary_status=str(primary.outcome),
            secondary_status=str(secondary.outcome),
            primary_primal_residual=primary.primal_residual,
            primary_dual_residual=primary.dual_residual,
            secondary_primal_residual=secondary.primal_residual,
            secondary_dual_residual=secondary.dual_residual,
            mathematical_infeasible=mathematical_infeasible,
            numerical_failure=numerical_failure,
            previous_applied_action=model_previous.copy(),
            previous_model_action=model_previous.copy(),
            applied_action_pu=np.full(4, np.nan),
            history_match=True,
            accepted_inaccurate=(
                accepted_attempt.outcome
                is SolverOutcome.OPTIMAL_INACCURATE_ACCEPTED
            ),
            hard_constraint_residual=accepted_attempt.primal_residual,
        )
        if not np.array_equal(model_previous, self.previous_action):
            raise AssertionError("propose mutated applied-action history")
        return action, diagnostic

    def solve(
        self,
        estimated_state: np.ndarray,
        causal_load_estimate: np.ndarray,
        input_lower: np.ndarray,
        input_upper: np.ndarray,
        bess_lower: np.ndarray,
        bess_upper: np.ndarray,
        command_slew: np.ndarray,
        delay_s: float | None = None,
        action_reference: np.ndarray | None = None,
    ) -> tuple[np.ndarray, MPCDiagnostics]:
        action, diagnostics = self.propose(
            estimated_state,
            causal_load_estimate,
            input_lower,
            input_upper,
            bess_lower,
            bess_upper,
            command_slew,
            delay_s,
            action_reference,
        )
        applied = action if diagnostics.solved else np.zeros(4)
        self.commit_applied_action(applied)
        return applied, replace(
            diagnostics,
            applied_action_pu=applied.copy(),
            backup_used=not diagnostics.solved,
        )


class NominalModelMPC:
    """Deployable fixed-capability rolling MPC."""

    def __init__(self, period_s: float = 4.0, horizon: int = 6) -> None:
        self.optimizer = FiniteHorizonMPC(period_s, horizon, nominal_delay_s=0.2)
        self.nominal_bess_limit = 0.10

    def reset(self) -> None:
        self.optimizer.reset()

    def update(
        self,
        observation: PublicObservationV2,
        estimated_state: np.ndarray,
        causal_load_estimate: np.ndarray,
        sg_reserve_pu: float,
    ) -> tuple[np.ndarray, MPCDiagnostics]:
        del observation  # state/estimator already comes from the shared public history
        lower = np.array([-sg_reserve_pu, -self.nominal_bess_limit, -sg_reserve_pu, -self.nominal_bess_limit])
        upper = -lower
        return self.optimizer.solve(
            estimated_state, causal_load_estimate, lower, upper,
            np.array([-self.nominal_bess_limit] * 2), np.array([self.nominal_bess_limit] * 2),
            np.array([0.06, 0.10, 0.06, 0.10]), delay_s=0.2,
        )
