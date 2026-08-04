"""True rolling Disturbance-Capability-Separated Viability MPC."""

from __future__ import annotations

from dataclasses import dataclass
import time

import cvxpy as cp
import numpy as np
from scipy.signal import cont2discrete

from direction5freq.controllers.domain_supervisor import DomainDecision
from direction5freq.controllers.feasibility_restoration import RestorationPolicy, SolverDiagnostics
from direction5freq.estimation.deliverability_set_mhe import DeliverabilitySetSnapshot
from direction5freq.models.capability_contract import CapabilityContract
from direction5freq.models.plant_a_full import PlantAFull, PlantAParameters, PublicObservation


@dataclass(frozen=True, slots=True)
class DCSVInput:
    observation: PublicObservation
    load_estimate_pu: np.ndarray
    deliverability_set: DeliverabilitySetSnapshot
    domain: DomainDecision
    contract_violation_status: str = "NO_DETECTED_VIOLATION"


@dataclass(frozen=True, slots=True)
class DCSVResult:
    proposed_action_pu: np.ndarray
    slow_reserve_request_pu: np.ndarray
    predicted_state_sequence: np.ndarray
    predicted_input_sequence: np.ndarray
    predicted_energy_sequence_mwh: np.ndarray
    predicted_slow_reserve_sequence_pu: np.ndarray
    delay_vertices_s: np.ndarray
    domain: str
    bridge_remaining_s: float
    diagnostics: SolverDiagnostics


class DisturbanceCapabilitySeparatedViabilityMPC:
    """Rolling QP with common controls across contract-delay vertices.

    `use_online_performance=False` instantiates the fair true rolling
    contract-robust MPC baseline. Both variants retain identical hard constraints
    and differ only in the revocable performance allocation weight.
    """

    is_true_rolling_mpc = True

    def __init__(
        self,
        period_s: float,
        horizon_steps: int = 8,
        use_online_performance: bool = True,
        name: str = "dcsv_mpc",
        plant_parameters: PlantAParameters | None = None,
    ) -> None:
        self.period_s = float(period_s)
        self.horizon_steps = int(horizon_steps)
        self.use_online_performance = bool(use_online_performance)
        self.name = name
        self.plant = PlantAFull(parameters=plant_parameters, dt_s=0.02)
        self.contract: CapabilityContract = self.plant.parameters.bess.contract
        self.restoration = RestorationPolicy()
        self._last_committed_action = np.zeros(4)
        self._last_actual_bess = np.zeros(2)
        self._bridge_remaining_s: float | None = None
        self._build_discrete_model()

    def _build_discrete_model(self) -> None:
        a, b, c, e = self.plant.linear_continuous_model_separate()
        h = np.asarray(self.plant.parameters.inertia_s)
        b_reserve = np.zeros((9, 2))
        b_reserve[0, 0] = 1.0 / (2.0 * h[0])
        b_reserve[1, 1] = 1.0 / (2.0 * h[1])
        combined = np.c_[b, e, b_reserve]
        ad, combined_d, _, _, _ = cont2discrete((a, combined, np.eye(9), np.zeros((9, 8))), self.period_s)
        self.ad = ad
        self.bd = combined_d[:, :4]
        self.ed = combined_d[:, 4:6]
        self.rd = combined_d[:, 6:8]
        self.ace_matrix = c

    def commit(self, applied_action_pu: np.ndarray, measured_actual_bess_pu: np.ndarray) -> None:
        action = np.asarray(applied_action_pu, dtype=float)
        actual = np.asarray(measured_actual_bess_pu, dtype=float)
        if action.shape != (4,) or actual.shape != (2,):
            raise ValueError("commit requires actual applied action and measured BESS power")
        self._last_committed_action = action.copy()
        self._last_actual_bess = actual.copy()

    def _state_from_observation(self, observation: PublicObservation) -> np.ndarray:
        return np.r_[
            observation.frequency_deviation_hz / self.plant.parameters.nominal_frequency_hz,
            observation.tie_line_pu,
            observation.valve_pu,
            observation.sg_mechanical_power_pu,
            observation.bess_actual_power_pu,
        ]

    def _delayed_bess_expression(self, u: cp.Variable, step: int, delay_s: float, area: int):
        fraction = min(max(delay_s / self.period_s, 0.0), 1.0)
        column = 1 if area == 0 else 3
        previous = self._last_committed_action[column] if step == 0 else u[column, step - 1]
        return (1.0 - fraction) * u[column, step] + fraction * previous

    def _solve(self, inputs: DCSVInput, restoration: bool) -> tuple[DCSVResult | None, str, float, int, float]:
        n, m, areas, horizon = 9, 4, 2, self.horizon_steps
        delay_vertices = np.array((0.0, max(self.contract.maximum_delay_s)))
        vertices = len(delay_vertices)
        u = cp.Variable((m, horizon))
        reserve = cp.Variable((areas, horizon + 1))
        reserve_request = cp.Variable((areas, horizon))
        x = [cp.Variable((n, horizon + 1)) for _ in range(vertices)]
        energy = [cp.Variable((areas, horizon + 1)) for _ in range(vertices)]
        discharge = [cp.Variable((areas, horizon)) for _ in range(vertices)]
        charge = [cp.Variable((areas, horizon)) for _ in range(vertices)]
        terminal_frequency_slack = cp.Variable(nonneg=True) if restoration else None
        terminal_ace_slack = cp.Variable(nonneg=True) if restoration else None
        constraints: list[cp.Constraint] = []
        x0 = self._state_from_observation(inputs.observation)
        energy0 = inputs.observation.measured_soc * self.plant.parameters.bess.energy_mwh
        reserve0 = inputs.observation.slow_reserve_power_pu
        constraints += [reserve[:, 0] == reserve0]
        reserve_upper = np.asarray(self.plant.parameters.slow_reserve.upper_pu)
        reserve_ramp_up = np.asarray(self.plant.parameters.slow_reserve.ramp_up_pu_per_s)
        reserve_ramp_down = np.asarray(self.plant.parameters.slow_reserve.ramp_down_pu_per_s)
        reserve_tau = np.asarray(self.plant.parameters.slow_reserve.time_constant_s)
        constraints += [reserve_request >= 0.0, reserve_request <= reserve_upper[:, None]]
        constraints += [reserve >= 0.0, reserve <= reserve_upper[:, None]]
        for k in range(horizon):
            raw_next = reserve[:, k] + self.period_s * (reserve_request[:, k] - reserve[:, k]) / reserve_tau
            constraints += [reserve[:, k + 1] == raw_next]
            constraints += [
                reserve[:, k + 1] - reserve[:, k] <= reserve_ramp_up * self.period_s,
                reserve[:, k] - reserve[:, k + 1] <= reserve_ramp_down * self.period_s,
            ]

        sg_lower = np.asarray(self.plant.parameters.valve_lower_pu)
        sg_upper = np.asarray(self.plant.parameters.valve_upper_pu)
        bess_lower = np.asarray(self.contract.lower_power_pu)
        bess_upper = np.asarray(self.contract.upper_power_pu)
        constraints += [u[[0, 2], :] >= sg_lower[:, None], u[[0, 2], :] <= sg_upper[:, None]]
        constraints += [u[[1, 3], :] >= bess_lower[:, None], u[[1, 3], :] <= bess_upper[:, None]]
        previous_sg = self._last_committed_action[[0, 2]]
        previous_bess = self._last_actual_bess
        for k in range(horizon):
            sg_prev = previous_sg if k == 0 else u[[0, 2], k - 1]
            constraints += [cp.abs(u[[0, 2], k] - sg_prev) <= 0.04 * self.period_s]
            bess_command_prev = self._last_committed_action[[1, 3]] if k == 0 else u[[1, 3], k - 1]
            constraints += [
                u[[1, 3], k] - bess_command_prev <= np.asarray(self.contract.ramp_up_pu_per_s) * self.period_s,
                bess_command_prev - u[[1, 3], k] <= np.asarray(self.contract.ramp_down_pu_per_s) * self.period_s,
            ]
        load = np.asarray(inputs.load_estimate_pu, dtype=float)
        energy_factor = self.period_s * self.plant.parameters.system_base_mva / 3600.0
        e_min = self.plant.parameters.bess.soc_min * self.plant.parameters.bess.energy_mwh
        e_max = self.plant.parameters.bess.soc_max * self.plant.parameters.bess.energy_mwh
        objective = 0.0
        for vertex, delay_s in enumerate(delay_vertices):
            constraints += [x[vertex][:, 0] == x0, energy[vertex][:, 0] == energy0]
            constraints += [energy[vertex] >= e_min, energy[vertex] <= e_max]
            constraints += [discharge[vertex] >= 0.0, charge[vertex] >= 0.0]
            for k in range(horizon):
                effective = cp.hstack((
                    u[0, k], self._delayed_bess_expression(u, k, delay_s, 0),
                    u[2, k], self._delayed_bess_expression(u, k, delay_s, 1),
                ))
                constraints += [
                    x[vertex][:, k + 1]
                    == self.ad @ x[vertex][:, k] + self.bd @ effective + self.ed @ load + self.rd @ reserve[:, k]
                ]
                constraints += [x[vertex][7:9, k] == discharge[vertex][:, k] - charge[vertex][:, k]]
                constraints += [
                    energy[vertex][:, k + 1]
                    == energy[vertex][:, k]
                    - energy_factor * (
                        discharge[vertex][:, k] / self.plant.parameters.bess.eta_discharge
                        - self.plant.parameters.bess.eta_charge * charge[vertex][:, k]
                    )
                ]
                # The contract is a guaranteed command-following floor, not a
                # physical upper rating. Actual POI power can legitimately be
                # above the floor due to PFR or verified online surplus.
                physical_rating = self.plant.parameters.bess.rating_pu
                constraints += [x[vertex][7:9, k] >= -physical_rating, x[vertex][7:9, k] <= physical_rating]
                prior_pb = previous_bess if k == 0 else x[vertex][7:9, k - 1]
                constraints += [
                    x[vertex][7:9, k] - prior_pb <= 0.10 * self.period_s,
                    prior_pb - x[vertex][7:9, k] <= 0.10 * self.period_s,
                ]
                constraints += [
                    x[vertex][3:5, k] >= np.asarray(self.plant.parameters.valve_lower_pu),
                    x[vertex][3:5, k] <= np.asarray(self.plant.parameters.valve_upper_pu),
                    x[vertex][5:7, k] >= np.asarray(self.plant.parameters.sg_power_lower_pu),
                    x[vertex][5:7, k] <= np.asarray(self.plant.parameters.sg_power_upper_pu),
                ]
                ace = self.ace_matrix @ x[vertex][:, k]
                objective += 30.0 * cp.sum_squares(ace) + 12.0 * cp.sum_squares(x[vertex][0:2, k])
                objective += 1e-3 * cp.sum(discharge[vertex][:, k] + charge[vertex][:, k])
            terminal_frequency_limit = 0.0025
            terminal_ace_limit = 0.025
            if inputs.domain.domain == "SUSTAINABLE":
                f_slack = 0.0 if not restoration else terminal_frequency_slack
                a_slack = 0.0 if not restoration else terminal_ace_slack
                constraints += [cp.abs(x[vertex][0:2, horizon]) <= terminal_frequency_limit + f_slack]
                constraints += [cp.abs(self.ace_matrix @ x[vertex][:, horizon]) <= terminal_ace_limit + a_slack]
            elif inputs.domain.domain == "BRIDGE":
                # Finite-horizon bridge: energy remains physical and slow reserve
                # must make monotone progress toward the load equilibrium.
                constraints += [reserve[:, horizon] >= reserve[:, 0]]

        objective += 0.05 * cp.sum_squares(u) + 0.20 * cp.sum_squares(u[:, 1:] - u[:, :-1])
        objective += 0.02 * cp.sum_squares(reserve_request)
        if self.use_online_performance:
            online = np.maximum(inputs.deliverability_set.performance_power_pu, np.asarray(self.contract.upper_power_pu))
            surplus_weight = np.clip(online / np.asarray(self.contract.upper_power_pu), 1.0, 2.2)
            objective += cp.sum(cp.multiply((0.035 / surplus_weight)[:, None], cp.square(u[[1, 3], :])))
        else:
            objective += 0.035 * cp.sum_squares(u[[1, 3], :])
        if restoration:
            objective += self.restoration.frequency_terminal_slack_penalty * terminal_frequency_slack
            objective += self.restoration.ace_terminal_slack_penalty * terminal_ace_slack

        problem = cp.Problem(cp.Minimize(objective), constraints)
        started = time.perf_counter()
        try:
            problem.solve(
                solver=cp.CLARABEL,
                warm_start=True,
                max_iter=300,
                tol_gap_abs=1e-7,
                tol_feas=1e-7,
                verbose=False,
            )
            solve_time = time.perf_counter() - started
        except Exception:
            return None, "NUMERICAL_EXCEPTION", time.perf_counter() - started, 0, np.inf
        status = str(problem.status)
        iterations = int(getattr(problem.solver_stats, "num_iters", 0) or 0)
        if status not in {"optimal", "optimal_inaccurate"} or u.value is None:
            return None, status, solve_time, iterations, np.inf
        violations = []
        for constraint in constraints:
            value = constraint.violation()
            if value is not None:
                violations.append(float(np.max(np.abs(value))))
        residual = max(violations, default=0.0)
        predicted_states = np.stack([value.value for value in x])
        predicted_energy = np.stack([value.value for value in energy])
        physical_rating = self.plant.parameters.bess.rating_pu
        state_margin = physical_rating - np.max(np.abs(predicted_states[:, 7:9, :-1]))
        command_margin = np.min(np.asarray(self.contract.upper_power_pu)[:, None] - np.abs(u.value[[1, 3], :]))
        hard_margin = float(min(state_margin, command_margin))
        energy_margin = float(min(np.min(predicted_energy - e_min), np.min(e_max - predicted_energy)))
        diagnostics = SolverDiagnostics(
            status=status,
            objective=float(problem.value),
            solve_time_s=solve_time,
            iterations=iterations,
            maximum_constraint_residual=residual,
            vertex_count=vertices,
            hard_margin_pu=hard_margin,
            energy_margin_mwh=energy_margin,
            restoration_used=restoration,
            fallback_used=False,
            mathematical_infeasibility=False,
            numerical_failure=status == "optimal_inaccurate",
        )
        result = DCSVResult(
            proposed_action_pu=np.asarray(u.value[:, 0]).ravel(),
            slow_reserve_request_pu=np.asarray(reserve_request.value[:, 0]).ravel(),
            predicted_state_sequence=predicted_states,
            predicted_input_sequence=np.asarray(u.value),
            predicted_energy_sequence_mwh=predicted_energy,
            predicted_slow_reserve_sequence_pu=np.asarray(reserve.value),
            delay_vertices_s=delay_vertices,
            domain=inputs.domain.domain,
            bridge_remaining_s=float(max(self._bridge_remaining_s or inputs.domain.bridge_remaining_s, 0.0)),
            diagnostics=diagnostics,
        )
        return result, status, solve_time, iterations, residual

    def _safe_fallback(self, inputs: DCSVInput, mathematical: bool, numerical: bool) -> DCSVResult:
        ace = inputs.observation.ace_pu
        total = np.clip(-0.35 * ace, -0.10, 0.10)
        action = np.array((0.75 * total[0], 0.25 * total[0], 0.75 * total[1], 0.25 * total[1]))
        action[[1, 3]] = np.clip(action[[1, 3]], self.contract.lower_power_pu, self.contract.upper_power_pu)
        reserve_request = np.asarray(inputs.domain.equilibrium_slow_reserve_pu)
        diagnostics = SolverDiagnostics(
            status="PHYSICAL_INFEASIBILITY_CERTIFICATE" if inputs.domain.domain == "PHYSICALLY_INFEASIBLE" else "SAFE_FALLBACK",
            objective=np.nan,
            solve_time_s=0.0,
            iterations=0,
            maximum_constraint_residual=0.0,
            vertex_count=2,
            hard_margin_pu=float(np.min(np.asarray(self.contract.upper_power_pu) - np.abs(action[[1, 3]]))),
            energy_margin_mwh=float(np.min(
                inputs.observation.measured_soc * self.plant.parameters.bess.energy_mwh
                - self.plant.parameters.bess.soc_min * self.plant.parameters.bess.energy_mwh
            )),
            restoration_used=False,
            fallback_used=inputs.domain.domain != "PHYSICALLY_INFEASIBLE",
            mathematical_infeasibility=mathematical,
            numerical_failure=numerical,
        )
        return DCSVResult(
            proposed_action_pu=action,
            slow_reserve_request_pu=reserve_request,
            predicted_state_sequence=np.empty((0, 9, 0)),
            predicted_input_sequence=np.empty((4, 0)),
            predicted_energy_sequence_mwh=np.empty((0, 2, 0)),
            predicted_slow_reserve_sequence_pu=np.empty((2, 0)),
            delay_vertices_s=np.array((0.0, max(self.contract.maximum_delay_s))),
            domain=inputs.domain.domain,
            bridge_remaining_s=float(max(self._bridge_remaining_s or inputs.domain.bridge_remaining_s, 0.0)),
            diagnostics=diagnostics,
        )

    def propose(self, inputs: DCSVInput) -> DCSVResult:
        if self._bridge_remaining_s is None or inputs.domain.domain != "BRIDGE":
            self._bridge_remaining_s = inputs.domain.bridge_remaining_s
        elif inputs.domain.domain == "BRIDGE":
            self._bridge_remaining_s = max(self._bridge_remaining_s - self.period_s, 0.0)
        if inputs.domain.domain == "PHYSICALLY_INFEASIBLE":
            return self._safe_fallback(inputs, mathematical=False, numerical=False)
        primary, status, _, _, _ = self._solve(inputs, restoration=False)
        if primary is not None:
            return primary
        restored, restored_status, _, _, _ = self._solve(inputs, restoration=True)
        if restored is not None:
            return restored
        mathematical = "infeasible" in status.lower() or "infeasible" in restored_status.lower()
        numerical = not mathematical
        return self._safe_fallback(inputs, mathematical=mathematical, numerical=numerical)


class RollingContractMPC(DisturbanceCapabilitySeparatedViabilityMPC):
    def __init__(
        self, period_s: float, horizon_steps: int = 8,
        plant_parameters: PlantAParameters | None = None,
    ) -> None:
        super().__init__(
            period_s=period_s,
            horizon_steps=horizon_steps,
            use_online_performance=False,
            name="rolling_contract_mpc",
            plant_parameters=plant_parameters,
        )
