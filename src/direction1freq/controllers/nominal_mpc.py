"""True rolling finite-horizon nominal MPC for Phase E."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import cvxpy as cp
import numpy as np
from scipy.signal import cont2discrete

from direction1freq.models.plant_a_v2 import PublicObservationV2, TwoAreaPlantAV2


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
        secondary_solver: str | None = None,
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
        self.x0.value = np.asarray(estimated_state, dtype=float)
        self.previous.value = self.previous_action
        self.load_estimate.value = np.asarray(causal_load_estimate, dtype=float)
        self.input_lower.value = np.asarray(input_lower, dtype=float)
        self.input_upper.value = np.asarray(input_upper, dtype=float)
        self.bess_lower.value = np.asarray(bess_lower, dtype=float)
        self.bess_upper.value = np.asarray(bess_upper, dtype=float)
        self.command_slew.value = np.asarray(command_slew, dtype=float)
        self.action_reference.value = (
            np.zeros(4) if action_reference is None
            else np.asarray(action_reference, dtype=float)
        )
        if delay_s is not None and abs(float(delay_s) - self.nominal_delay_s) > 1e-9:
            raise ValueError("construct a delay-specific optimizer instead of changing delay online")
        started = perf_counter()
        fallback = ""
        try:
            objective = self.problem.solve(
                solver=cp.OSQP, warm_start=True, eps_abs=self.solver_tolerance,
                eps_rel=self.solver_tolerance, max_iter=20_000, polish=True, verbose=False,
            )
            status = str(self.problem.status)
            if (
                status not in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE}
                and self.secondary_solver == "CLARABEL"
            ):
                objective = self.problem.solve(
                    solver=cp.CLARABEL, warm_start=True,
                    tol_gap_abs=self.solver_tolerance,
                    tol_gap_rel=self.solver_tolerance,
                    tol_feas=self.solver_tolerance,
                    max_iter=1000, verbose=False,
                )
                status = f"secondary_clarabel:{self.problem.status}"
        except Exception as error:  # solver errors are evidence, never hidden
            objective = float("nan")
            status = f"exception:{type(error).__name__}"
            fallback = str(error)
        elapsed = perf_counter() - started
        solved = status in {
            cp.OPTIMAL, cp.OPTIMAL_INACCURATE,
            f"secondary_clarabel:{cp.OPTIMAL}",
            f"secondary_clarabel:{cp.OPTIMAL_INACCURATE}",
        } and self.u.value is not None
        action = np.asarray(self.u.value[:, 0]).ravel() if solved else np.zeros(4)
        predicted_states = np.asarray(self.x.value) if solved else np.full((9, self.horizon + 1), np.nan)
        predicted_actions = np.asarray(self.u.value) if solved else np.full((4, self.horizon), np.nan)
        primal = float("inf")
        dual = float("inf")
        iterations = 0
        if solved:
            violations = [
                float(np.max(np.asarray(constraint.violation())))
                for constraint in self.problem.constraints
                if np.asarray(constraint.violation()).size
            ]
            primal = max(violations, default=0.0)
            extra = self.problem.solver_stats.extra_stats
            info = getattr(extra, "info", None)
            if info is not None:
                primal = max(primal, float(getattr(info, "prim_res", 0.0)))
                dual = float(getattr(info, "dual_res", 0.0))
                iterations = int(getattr(info, "iter", 0))
            else:
                dual = float("nan")
        else:
            fallback = fallback or status
        warm_started = self._has_solution
        if solved:
            self.previous_action = action.copy()
            self._has_solution = True
        diagnostics = MPCDiagnostics(
            solver_status=status, solved=solved, solve_time_s=elapsed,
            objective=float(objective) if objective is not None else float("nan"),
            primal_residual=primal, dual_residual=dual, iterations=iterations,
            warm_started=warm_started, fallback_reason=fallback,
            prediction_horizon=self.horizon, first_action_pu=action.copy(),
            predicted_states=predicted_states, predicted_actions=predicted_actions,
        )
        return action, diagnostics


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
