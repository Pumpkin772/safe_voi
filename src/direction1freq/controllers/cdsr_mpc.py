"""Capability-and-Delay-Set Robust MPC with feasibility restoration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter

import cvxpy as cp
import numpy as np

from direction1freq.controllers.ace_pi_aw import ACEPIAntiWindup, design_stable_pi
from direction1freq.controllers.cdsr_supervisor import CDSRFeasibilitySupervisor
from direction1freq.controllers.mpc_transaction import (
    SolverAttempt,
    SolverOutcome,
    assert_applied_action,
    classify_solver_attempt,
)
from direction1freq.models.delay_augmented_prediction import (
    DelayAugmentedVertex,
    build_registered_delay_vertices,
)
from direction1freq.models.guaranteed_capability_envelope import (
    GuaranteedCapabilityEnvelope,
)
from direction1freq.models.plant_a_v2 import PublicObservationV2, TwoAreaPlantAV2


@dataclass(frozen=True, slots=True)
class CDSRDiagnostics:
    solved: bool
    solver_status: str
    primary_status: str
    secondary_status: str
    primary_primal_residual: float
    primary_dual_residual: float
    secondary_primal_residual: float
    secondary_dual_residual: float
    mathematical_infeasible: bool
    numerical_failure: bool
    terminal_reject: bool
    restoration_used: bool
    restoration_stage1_status: str
    restoration_stage2_status: str
    backup_used: bool
    fallback_reason: str
    previous_applied_action: np.ndarray
    previous_model_action: np.ndarray
    applied_action_pu: np.ndarray
    history_match: bool
    consecutive_backup_count: int
    scenario_count: int
    prediction_horizon: int
    solve_time_s: float
    objective: float
    primal_residual: float
    dual_residual: float
    hard_constraint_residual: float
    performance_slack_l1: float
    first_action_pu: np.ndarray
    predicted_states: np.ndarray
    predicted_actions: np.ndarray
    predicted_energy_mwh: np.ndarray


class CapabilityDelaySetRobustMPC:
    """True receding finite-horizon robust optimizer over registered sets."""

    method_name = "CDSR-MPC"

    def __init__(
        self,
        period_s: float = 4.0,
        horizon: int | None = None,
        *,
        accepted_solution_residual: float = 1e-5,
    ) -> None:
        self.period_s = float(period_s)
        self.horizon = int(
            (8 if self.period_s == 2.0 else 6) if horizon is None else horizon
        )
        self.accepted_solution_residual = float(accepted_solution_residual)
        self.envelope = GuaranteedCapabilityEnvelope.phase_f_registered()
        self.plant = TwoAreaPlantAV2()
        _a, _b, self.c_ace, _e = self.plant.linear_continuous_model_separate()
        self.vertices: tuple[DelayAugmentedVertex, ...] = build_registered_delay_vertices(
            self.period_s, self.envelope.delay_vertices_s
        )
        self.previous_action = np.zeros(4)
        self.energy_estimate_mwh = self.envelope.energy_midpoint_mwh.copy()
        self._consecutive_backup_count = 0
        self._has_solution = False
        kp, ki, _ = design_stable_pi(self.plant, self.period_s)
        self.reference = ACEPIAntiWindup(
            self.period_s, kp, ki, sg_fraction=0.70
        )
        self.supervisor = CDSRFeasibilitySupervisor(self.period_s)
        self._load_uncertainty_radii()
        self._build_problem()

    def _load_uncertainty_radii(self) -> None:
        path = (
            Path(__file__).resolve().parents[3]
            / "results_phase_f"
            / "F3"
            / "RESIDUAL_UNCERTAINTY_SET.npz"
        )
        if path.is_file():
            payload = np.load(path)
            source_horizons = payload["horizons"].astype(int)
            source_radii = payload["component_radii"]
        else:  # package/source-only safe default; never calibrated from final
            source_horizons = np.array([1, 2, 4, 6])
            source_radii = np.tile(
                np.array([0.0085, 0.0085, 0.105, 0.07, 0.07, 0.065, 0.045, 0.105, 0.105]),
                (4, 1),
            )
        radii = []
        for stage in range(self.horizon + 1):
            if stage == 0:
                radii.append(np.zeros(9))
                continue
            index = int(np.flatnonzero(source_horizons >= stage)[0]) if np.any(
                source_horizons >= stage
            ) else len(source_horizons) - 1
            radii.append(source_radii[index])
        self.state_error_radii = np.asarray(radii)

    def reset(self) -> None:
        self.previous_action = np.zeros(4)
        self.energy_estimate_mwh = self.envelope.energy_midpoint_mwh.copy()
        self._consecutive_backup_count = 0
        self._has_solution = False
        self.reference.reset()
        self.supervisor.reset()
        for variable in self._all_variables:
            variable.value = None

    def commit_applied_action(
        self, applied_action: np.ndarray, estimated_omega_pu: np.ndarray
    ) -> None:
        action = assert_applied_action(applied_action, 4)
        total = self.envelope.total_bess_power(
            action[[1, 3]], estimated_omega_pu
        )
        discharge = np.maximum(total, 0.0)
        charge = np.maximum(-total, 0.0)
        self.energy_estimate_mwh = self.envelope.next_energy_mwh(
            self.energy_estimate_mwh,
            discharge,
            charge,
            self.period_s,
        )
        self.previous_action = action

    def _build_problem(self) -> None:
        n, m, areas, horizon = 9, 4, 2, self.horizon
        q_count = len(self.vertices)
        self.x = [
            cp.Variable((n, horizon + 1), name=f"x_delay_{q}")
            for q in range(q_count)
        ]
        self.energy = [
            cp.Variable((areas, horizon + 1), name=f"energy_delay_{q}")
            for q in range(q_count)
        ]
        self.discharge = [
            cp.Variable((areas, horizon), nonneg=True, name=f"discharge_{q}")
            for q in range(q_count)
        ]
        self.charge = [
            cp.Variable((areas, horizon), nonneg=True, name=f"charge_{q}")
            for q in range(q_count)
        ]
        # A single command sequence enforces non-anticipativity across all q.
        self.u = cp.Variable((m, horizon), name="common_control_sequence")
        self.slack_f = [
            cp.Variable((areas, horizon + 1), nonneg=True, name=f"slack_f_{q}")
            for q in range(q_count)
        ]
        self.slack_ace = [
            cp.Variable((areas, horizon + 1), nonneg=True, name=f"slack_ace_{q}")
            for q in range(q_count)
        ]
        self.slack_tie = [
            cp.Variable(horizon + 1, nonneg=True, name=f"slack_tie_{q}")
            for q in range(q_count)
        ]
        self.abs_frequency = [
            cp.Variable((areas, horizon + 1), nonneg=True, name=f"abs_f_{q}")
            for q in range(q_count)
        ]
        self.abs_ace = [
            cp.Variable((areas, horizon + 1), nonneg=True, name=f"abs_ace_{q}")
            for q in range(q_count)
        ]
        self.abs_tie = [
            cp.Variable(horizon + 1, nonneg=True, name=f"abs_tie_{q}")
            for q in range(q_count)
        ]
        self.worst_cost = cp.Variable(nonneg=True, name="worst_scenario_cost")
        self.x0 = cp.Parameter(n, name="estimated_state")
        self.load_estimate = cp.Parameter(2, name="causal_load_estimate")
        self.previous = cp.Parameter(m, name="previous_applied_action")
        self.energy0 = cp.Parameter(areas, name="public_or_causal_energy")
        self.sg_reserve = cp.Parameter(nonneg=True, name="sg_reserve")
        self.reference_action = cp.Parameter(m, name="pi_reference")
        self.performance_slack_cap = cp.Parameter(
            3, nonneg=True, name="performance_slack_cap"
        )
        self.restoration_slack_bound = cp.Parameter(
            nonneg=True, name="restoration_slack_bound"
        )
        constraints: list[cp.Constraint] = []
        frequency_gain = self.plant.parameters.nominal_frequency_hz
        pfr_gain = self.plant.parameters.bess.pfr_gain_pu_power_per_pu_frequency
        scenario_costs = []
        total_slack = 0.0
        split_penalty = 0.0
        for q, vertex in enumerate(self.vertices):
            constraints.extend([self.x[q][:, 0] == self.x0, self.energy[q][:, 0] == self.energy0])
            previous_total = self.previous[[1, 3]] - pfr_gain * self.x0[:2]
            scenario_cost = 0.0
            for stage in range(horizon):
                previous_action = self.previous if stage == 0 else self.u[:, stage - 1]
                constraints.append(
                    self.x[q][:, stage + 1]
                    == vertex.ad @ self.x[q][:, stage]
                    + vertex.b_current @ self.u[:, stage]
                    + vertex.b_previous @ previous_action
                    + vertex.ed @ self.load_estimate
                )
                constraints.extend(
                    [
                        self.u[[0, 2], stage] >= -self.sg_reserve,
                        self.u[[0, 2], stage] <= self.sg_reserve,
                        cp.abs(self.u[[0, 2], stage] - previous_action[[0, 2]]) <= 0.04,
                        cp.abs(self.u[[1, 3], stage] - previous_action[[1, 3]]) <= 0.06,
                    ]
                )
                total_bess = self.u[[1, 3], stage] - pfr_gain * self.x[q][:2, stage]
                # Frequency-model error can change local PFR request; account
                # for it without pretending the full state box is a tube.
                request_margin = np.minimum(
                    0.8 * self.envelope.power_upper_pu,
                    pfr_gain * self.state_error_radii[stage, :2],
                )
                constraints.extend(
                    [
                        total_bess >= self.envelope.power_lower_pu + request_margin,
                        total_bess <= self.envelope.power_upper_pu - request_margin,
                        total_bess == self.discharge[q][:, stage] - self.charge[q][:, stage],
                        cp.abs(total_bess - previous_total)
                        <= self.period_s * self.envelope.ramp_up_pu_per_s,
                    ]
                )
                constraints.append(
                    self.energy[q][:, stage + 1]
                    == self.energy[q][:, stage]
                    - self.period_s
                    * self.envelope.system_base_mva
                    / 3600.0
                    * (
                        self.discharge[q][:, stage] / self.envelope.eta_discharge
                        - self.envelope.eta_charge * self.charge[q][:, stage]
                    )
                )
                constraints.extend(
                    [
                        self.energy[q][:, stage + 1] >= self.envelope.energy_lower_mwh,
                        self.energy[q][:, stage + 1] <= self.envelope.energy_upper_mwh,
                        self.x[q][5:7, stage + 1]
                        >= np.asarray(self.plant.parameters.sg_power_lower_pu),
                        self.x[q][5:7, stage + 1]
                        <= np.asarray(self.plant.parameters.sg_power_upper_pu),
                    ]
                )
                previous_total = total_bess
                split_penalty += cp.sum(self.discharge[q][:, stage] + self.charge[q][:, stage])
            for stage in range(horizon + 1):
                frequency = frequency_gain * self.x[q][:2, stage]
                ace = self.c_ace @ self.x[q][:, stage]
                frequency_margin = frequency_gain * self.state_error_radii[stage, :2]
                ace_margin = np.abs(self.c_ace) @ self.state_error_radii[stage]
                tie_margin = self.state_error_radii[stage, 2]
                constraints.extend(
                    [
                        self.abs_frequency[q][:, stage] >= frequency,
                        self.abs_frequency[q][:, stage] >= -frequency,
                        self.abs_ace[q][:, stage] >= ace,
                        self.abs_ace[q][:, stage] >= -ace,
                        self.abs_tie[q][stage] >= self.x[q][2, stage],
                        self.abs_tie[q][stage] >= -self.x[q][2, stage],
                        cp.abs(frequency) + frequency_margin
                        <= 0.80 + self.slack_f[q][:, stage],
                        cp.abs(ace) + ace_margin
                        <= 0.30 + self.slack_ace[q][:, stage],
                        cp.abs(self.x[q][2, stage]) + tie_margin
                        <= 0.15 + self.slack_tie[q][stage],
                        self.slack_f[q][:, stage] <= self.performance_slack_cap[0],
                        self.slack_ace[q][:, stage] <= self.performance_slack_cap[1],
                        self.slack_tie[q][stage] <= self.performance_slack_cap[2],
                    ]
                )
                scenario_cost += (
                    1.2 * cp.sum(self.abs_frequency[q][:, stage])
                    + 4.0 * cp.sum(self.abs_ace[q][:, stage])
                    + 1.8 * self.abs_tie[q][stage]
                )
                total_slack += (
                    cp.sum(self.slack_f[q][:, stage])
                    + cp.sum(self.slack_ace[q][:, stage])
                    + self.slack_tie[q][stage]
                )
            # Empirical SG terminal-admissibility box.  F5 determines whether
            # it is invariant; until then no recursive claim is made.
            terminal = self.x[q][:, horizon]
            constraints.extend(
                [
                    cp.abs(frequency_gain * terminal[:2]) <= 0.30,
                    cp.abs(self.c_ace @ terminal) <= 0.15,
                    cp.abs(terminal[2]) <= 0.08,
                    cp.abs(terminal[5:7]) <= 0.10,
                ]
            )
            scenario_costs.append(scenario_cost)
            constraints.append(scenario_cost <= self.worst_cost)
        constraints.append(total_slack <= self.restoration_slack_bound)
        normal_objective = (
            self.worst_cost
            + 1e3 * total_slack
            + 0.02 * cp.sum_squares(self.u - self.reference_action[:, None])
            + 0.001 * split_penalty
        )
        self.total_slack = total_slack
        self.constraints = constraints
        self.primary_problem = cp.Problem(cp.Minimize(normal_objective), constraints)
        self.restoration_stage1_problem = cp.Problem(
            cp.Minimize(total_slack + 1e-4 * split_penalty), constraints
        )
        self.restoration_stage2_problem = cp.Problem(
            cp.Minimize(normal_objective), constraints
        )
        self._all_variables = [
            *self.x,
            *self.energy,
            *self.discharge,
            *self.charge,
            self.u,
            *self.slack_f,
            *self.slack_ace,
            *self.slack_tie,
            *self.abs_frequency,
            *self.abs_ace,
            *self.abs_tie,
            self.worst_cost,
        ]

    def _constraint_residual(self) -> float:
        residuals = []
        for constraint in self.constraints:
            try:
                value = np.asarray(constraint.violation(), dtype=float)
            except (ValueError, TypeError):
                continue
            if value.size and np.all(np.isfinite(value)):
                residuals.append(float(np.max(np.abs(value))))
        return max(residuals, default=float("inf"))

    def _attempt(
        self,
        problem: cp.Problem,
        solver: str,
        *,
        osqp: bool,
    ) -> SolverAttempt:
        error_text = ""
        try:
            if osqp:
                objective = problem.solve(
                    solver=cp.OSQP,
                    warm_start=True,
                    eps_abs=1e-6,
                    eps_rel=1e-6,
                    max_iter=3_000,
                    polishing=True,
                    verbose=False,
                )
            else:
                objective = problem.solve(
                    solver=cp.CLARABEL,
                    warm_start=True,
                    tol_gap_abs=1e-7,
                    tol_gap_rel=1e-7,
                    tol_feas=1e-7,
                    max_iter=1000,
                    verbose=False,
                )
            raw = str(problem.status)
        except Exception as error:
            objective = float("nan")
            raw = f"exception:{type(error).__name__}"
            error_text = str(error)
        primal = self._constraint_residual() if not error_text else float("inf")
        dual = float("nan")
        iterations = int(problem.solver_stats.num_iters or 0) if problem.solver_stats else 0
        if problem.solver_stats is not None:
            info = getattr(problem.solver_stats.extra_stats, "info", None)
            if info is not None:
                native_primal = float(getattr(info, "prim_res", float("nan")))
                native_dual = float(getattr(info, "dual_res", float("nan")))
                if np.isfinite(native_primal):
                    primal = max(primal, native_primal)
                dual = native_dual
        outcome, accepted = classify_solver_attempt(
            raw, primal, dual, self.accepted_solution_residual
        )
        if error_text:
            outcome, accepted = SolverOutcome.NUMERICAL_FAILURE, False
        return SolverAttempt(
            solver,
            raw,
            outcome,
            accepted,
            float(objective) if objective is not None else float("nan"),
            primal,
            dual,
            iterations,
            error_text,
        )

    def propose(
        self,
        observation: PublicObservationV2,
        estimated_state: np.ndarray,
        causal_load_estimate: np.ndarray,
        sg_reserve_pu: float,
        *,
        public_energy_mwh: np.ndarray | None = None,
        force_primary_failure: bool = False,
        force_primary_secondary_failure: bool = False,
        force_all_solver_failure: bool = False,
    ) -> tuple[np.ndarray, CDSRDiagnostics]:
        """Propose a common robust action without changing physical history."""

        model_previous = self.previous_action.copy()
        if public_energy_mwh is not None:
            measured = np.asarray(public_energy_mwh, dtype=float)
            # Energy telemetry is public state, not a capability or mode label.
            self.energy_estimate_mwh = np.clip(
                measured,
                self.envelope.energy_lower_mwh,
                self.envelope.energy_upper_mwh,
            )
        reference, _ = self.reference.update(observation)
        reference[[0, 2]] = np.clip(
            reference[[0, 2]], -sg_reserve_pu, sg_reserve_pu
        )
        self.x0.value = np.asarray(estimated_state, dtype=float)
        self.load_estimate.value = np.asarray(causal_load_estimate, dtype=float)
        self.previous.value = model_previous
        self.energy0.value = self.energy_estimate_mwh
        self.sg_reserve.value = float(sg_reserve_pu)
        self.reference_action.value = reference
        self.performance_slack_cap.value = np.array([0.20, 0.10, 0.05])
        self.restoration_slack_bound.value = 1e6
        started = perf_counter()
        primary = (
            SolverAttempt(
                "OSQP",
                "forced_primary_failure",
                SolverOutcome.NUMERICAL_FAILURE,
                False,
                float("nan"),
                float("inf"),
                float("inf"),
                0,
                "forced_primary_failure",
            )
            if force_primary_failure
            or force_primary_secondary_failure
            or force_all_solver_failure
            else self._attempt(self.primary_problem, "OSQP", osqp=True)
        )
        secondary = SolverAttempt(
            "CLARABEL",
            "not_run",
            SolverOutcome.NOT_RUN,
            False,
            float("nan"),
            float("nan"),
            float("nan"),
            0,
        )
        if not primary.accepted and not force_all_solver_failure:
            secondary = (
                SolverAttempt(
                    "CLARABEL",
                    "forced_secondary_failure",
                    SolverOutcome.NUMERICAL_FAILURE,
                    False,
                    float("nan"),
                    float("inf"),
                    float("inf"),
                    0,
                    "forced_secondary_failure",
                )
                if force_primary_secondary_failure
                else self._attempt(self.primary_problem, "CLARABEL", osqp=False)
            )
        restoration_used = False
        restoration_stage1 = SolverAttempt(
            "CLARABEL",
            "not_run",
            SolverOutcome.NOT_RUN,
            False,
            float("nan"),
            float("nan"),
            float("nan"),
            0,
        )
        restoration_stage2 = restoration_stage1
        accepted = primary if primary.accepted else secondary
        if not accepted.accepted and not force_all_solver_failure:
            restoration_used = True
            self.performance_slack_cap.value = np.array([10.0, 10.0, 10.0])
            self.restoration_slack_bound.value = 1e6
            restoration_stage1 = self._attempt(
                self.restoration_stage1_problem, "CLARABEL", osqp=False
            )
            if restoration_stage1.accepted and self.total_slack.value is not None:
                minimum_slack = float(self.total_slack.value)
                self.restoration_slack_bound.value = minimum_slack + 1e-6
                restoration_stage2 = self._attempt(
                    self.restoration_stage2_problem, "CLARABEL", osqp=False
                )
                accepted = restoration_stage2
        solved = bool(accepted.accepted and self.u.value is not None)
        candidate = (
            np.asarray(self.u.value[:, 0]).ravel().copy()
            if solved
            else np.zeros(4)
        )
        states = (
            np.stack([np.asarray(variable.value) for variable in self.x])
            if solved
            else np.full((len(self.vertices), 9, self.horizon + 1), np.nan)
        )
        energies = (
            np.stack([np.asarray(variable.value) for variable in self.energy])
            if solved
            else np.full((len(self.vertices), 2, self.horizon + 1), np.nan)
        )
        actions = (
            np.asarray(self.u.value).copy()
            if solved
            else np.full((4, self.horizon), np.nan)
        )
        if solved:
            self._has_solution = True
        attempts = [primary]
        if secondary.outcome is not SolverOutcome.NOT_RUN:
            attempts.append(secondary)
        if restoration_used:
            attempts.extend([restoration_stage1, restoration_stage2])
        elapsed = perf_counter() - started
        diagnostic = CDSRDiagnostics(
            solved=solved,
            solver_status=str(accepted.outcome),
            primary_status=str(primary.outcome),
            secondary_status=str(secondary.outcome),
            primary_primal_residual=primary.primal_residual,
            primary_dual_residual=primary.dual_residual,
            secondary_primal_residual=secondary.primal_residual,
            secondary_dual_residual=secondary.dual_residual,
            mathematical_infeasible=bool(
                not solved and any(item.mathematical_infeasible for item in attempts)
            ),
            numerical_failure=bool(
                not solved and any(item.numerical_failure for item in attempts)
            ),
            terminal_reject=False,
            restoration_used=restoration_used,
            restoration_stage1_status=str(restoration_stage1.outcome),
            restoration_stage2_status=str(restoration_stage2.outcome),
            backup_used=False,
            fallback_reason="" if solved else ";".join(
                f"{item.solver}:{item.outcome}" for item in attempts
            ),
            previous_applied_action=model_previous.copy(),
            previous_model_action=model_previous.copy(),
            applied_action_pu=np.full(4, np.nan),
            history_match=True,
            consecutive_backup_count=self._consecutive_backup_count,
            scenario_count=len(self.vertices),
            prediction_horizon=self.horizon,
            solve_time_s=elapsed,
            objective=accepted.objective,
            primal_residual=accepted.primal_residual,
            dual_residual=accepted.dual_residual,
            hard_constraint_residual=accepted.primal_residual,
            performance_slack_l1=(
                float(self.total_slack.value)
                if solved and self.total_slack.value is not None
                else float("inf")
            ),
            first_action_pu=candidate.copy(),
            predicted_states=states,
            predicted_actions=actions,
            predicted_energy_mwh=energies,
        )
        if not np.array_equal(model_previous, self.previous_action):
            raise AssertionError("CDSR propose mutated applied-action history")
        return candidate, diagnostic

    def update(
        self,
        observation: PublicObservationV2,
        estimated_state: np.ndarray,
        causal_load_estimate: np.ndarray,
        sg_reserve_pu: float,
        *,
        public_energy_mwh: np.ndarray | None = None,
        force_primary_failure: bool = False,
        force_primary_secondary_failure: bool = False,
        force_all_solver_failure: bool = False,
    ) -> tuple[np.ndarray, CDSRDiagnostics]:
        candidate, diagnostic = self.propose(
            observation,
            estimated_state,
            causal_load_estimate,
            sg_reserve_pu,
            public_energy_mwh=public_energy_mwh,
            force_primary_failure=force_primary_failure,
            force_primary_secondary_failure=force_primary_secondary_failure,
            force_all_solver_failure=force_all_solver_failure,
        )
        applied, decision = self.supervisor.select(
            candidate,
            solver_accepted=diagnostic.solved,
            predicted_states=diagnostic.predicted_states,
            c_ace=self.c_ace,
            hard_constraint_residual=diagnostic.hard_constraint_residual,
            observation=observation,
            sg_reserve_pu=sg_reserve_pu,
        )
        self.commit_applied_action(applied, np.asarray(estimated_state)[:2])
        self._consecutive_backup_count = (
            self._consecutive_backup_count + 1 if decision.backup_used else 0
        )
        diagnostic = replace(
            diagnostic,
            solved=bool(diagnostic.solved and decision.accepted_proposal),
            terminal_reject=decision.terminal_reject,
            backup_used=decision.backup_used,
            fallback_reason=(
                diagnostic.fallback_reason
                if not decision.backup_used
                else decision.reason
            ),
            applied_action_pu=applied.copy(),
            history_match=bool(
                np.allclose(
                    diagnostic.previous_applied_action,
                    diagnostic.previous_model_action,
                    atol=1e-12,
                )
            ),
            consecutive_backup_count=self._consecutive_backup_count,
        )
        return applied, diagnostic
