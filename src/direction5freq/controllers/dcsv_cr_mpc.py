"""Disturbance-Capability-Separated Contract-Recourse rolling MPC."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time

import cvxpy as cp
import numpy as np
from scipy.signal import cont2discrete

from direction5freq.controllers.dcsv_mpc_final import DCSVInput
from direction5freq.controllers.recourse_tree import RecourseTree
from direction5freq.models.capability_contract import CapabilityContract
from direction5freq.models.plant_a_full import PlantAFull, PlantAParameters, PublicObservation


@dataclass(frozen=True, slots=True)
class DCSVCRSolverDiagnostics:
    status: str
    objective: float
    solve_time_s: float
    iterations: int
    maximum_constraint_residual: float
    branch_count: int
    delay_vertex_count: int
    hard_margin_pu: float
    energy_margin_mwh: float
    restoration_used: bool
    fallback_used: bool
    mathematical_infeasibility: bool
    numerical_failure: bool
    attempted_optimization_calls: int
    primary_status: str
    restoration_status: str


@dataclass(frozen=True, slots=True)
class DCSVCRResult:
    proposed_action_pu: np.ndarray
    guaranteed_bess_command_pu: np.ndarray
    surplus_bess_command_pu: np.ndarray
    slow_reserve_request_pu: np.ndarray
    predicted_state_sequence: np.ndarray
    predicted_input_sequence: np.ndarray
    predicted_guaranteed_bess_sequence_pu: np.ndarray
    predicted_surplus_bess_sequence_pu: np.ndarray
    predicted_energy_sequence_mwh: np.ndarray
    predicted_slow_reserve_sequence_pu: np.ndarray
    branch_names: tuple[str, ...]
    delay_vertices_s: np.ndarray
    shared_current_action_verified: bool
    surplus_loss_branch_verified: bool
    domain: str
    bridge_remaining_s: float
    diagnostics: DCSVCRSolverDiagnostics


class DCSVContractRecourseMPC:
    """Two-stage rolling MPC with a hard contract floor and future recourse.

    The current SG, guaranteed BESS, surplus BESS and reserve-request decisions
    are shared by every branch. From the next control period onward, SG and
    slow-reserve decisions can branch. The hard loss branch assumes zero
    surplus delivery; hence online performance evidence cannot shrink the
    contract-safe prediction set.
    """

    name = "dcsv_cr_mpc"
    is_true_rolling_mpc = True

    def __init__(
        self,
        period_s: float,
        horizon_steps: int = 6,
        plant_parameters: PlantAParameters | None = None,
    ) -> None:
        self.period_s = float(period_s)
        self.horizon_steps = int(horizon_steps)
        if self.period_s <= 0.0 or self.horizon_steps < 2:
            raise ValueError("DCSV-CR requires a positive period and horizon >= 2")
        self.plant = PlantAFull(parameters=plant_parameters, dt_s=0.02)
        self.contract: CapabilityContract = self.plant.parameters.bess.contract
        self.tree = RecourseTree.registered(max(self.contract.maximum_delay_s))
        self.tree.validate()
        history_length = int(np.ceil(max(self.contract.maximum_delay_s) / self.period_s)) + 4
        self._guaranteed_history: deque[np.ndarray] = deque(
            (np.zeros(2) for _ in range(history_length)), maxlen=history_length
        )
        self._surplus_history: deque[np.ndarray] = deque(
            (np.zeros(2) for _ in range(history_length)), maxlen=history_length
        )
        self._last_committed_action = np.zeros(4)
        self._last_actual_bess = np.zeros(2)
        self._bridge_remaining_s: float | None = None
        self._build_discrete_model()

    def _build_discrete_model(self) -> None:
        a, b, c, e = self.plant.linear_continuous_model_separate()
        inertia = np.asarray(self.plant.parameters.inertia_s)
        b_reserve = np.zeros((9, 2))
        b_reserve[0, 0] = 1.0 / (2.0 * inertia[0])
        b_reserve[1, 1] = 1.0 / (2.0 * inertia[1])
        combined = np.c_[b, e, b_reserve]
        ad, combined_d, _, _, _ = cont2discrete(
            (a, combined, np.eye(9), np.zeros((9, 8))), self.period_s
        )
        self.ad = ad
        self.bd = combined_d[:, :4]
        self.ed = combined_d[:, 4:6]
        self.rd = combined_d[:, 6:8]
        self.ace_matrix = c

    @property
    def last_committed_action(self) -> np.ndarray:
        return self._last_committed_action.copy()

    def commit(
        self,
        applied_action_pu: np.ndarray,
        measured_actual_bess_pu: np.ndarray,
        applied_guaranteed_bess_pu: np.ndarray | None = None,
    ) -> None:
        """Commit the action actually applied after supervision/restoration."""

        action = np.asarray(applied_action_pu, dtype=float)
        actual = np.asarray(measured_actual_bess_pu, dtype=float)
        if action.shape != (4,) or actual.shape != (2,):
            raise ValueError("commit requires four applied commands and two POI measurements")
        total = action[[1, 3]]
        if applied_guaranteed_bess_pu is None:
            guaranteed = np.clip(
                total,
                np.asarray(self.contract.lower_power_pu),
                np.asarray(self.contract.upper_power_pu),
            )
        else:
            guaranteed = np.asarray(applied_guaranteed_bess_pu, dtype=float)
            if guaranteed.shape != (2,):
                raise ValueError("applied guaranteed command must contain two areas")
        surplus = total - guaranteed
        self._last_committed_action = action.copy()
        self._last_actual_bess = actual.copy()
        self._guaranteed_history.append(guaranteed.copy())
        self._surplus_history.append(surplus.copy())

    def _state_from_observation(self, observation: PublicObservation) -> np.ndarray:
        return np.r_[
            observation.frequency_deviation_hz / self.plant.parameters.nominal_frequency_hz,
            observation.tie_line_pu,
            observation.valve_pu,
            observation.sg_mechanical_power_pu,
            observation.bess_actual_power_pu,
        ]

    def _pipeline_expression(
        self,
        sequence: cp.Variable,
        step: int,
        delay_s: float,
        area: int,
        history: deque[np.ndarray],
    ):
        delay_steps = max(float(delay_s) / self.period_s, 0.0)
        whole = int(np.floor(delay_steps))
        fraction = delay_steps - whole

        def sample(index: int):
            if index >= 0:
                return sequence[area, index]
            values = list(history)
            history_index = max(-len(values), index)
            return float(values[history_index][area])

        newest = step - whole
        return (1.0 - fraction) * sample(newest) + fraction * sample(newest - 1)

    def _solve(self, inputs: DCSVInput, restoration: bool):
        n, areas, horizon = 9, 2, self.horizon_steps
        branch_count = len(self.tree.branches)
        online_delay = float(np.max(inputs.deliverability_set.delay_interval_s[:, 1]))
        delay_vertices = np.unique(np.array((
            0.0,
            min(max(max(self.contract.maximum_delay_s), online_delay),
                self.plant.parameters.bess.maximum_physical_delay_s),
        )))
        vertex_count = len(delay_vertices)
        guaranteed = cp.Variable((areas, horizon))
        surplus = cp.Variable((areas, horizon))
        sg = [cp.Variable((areas, horizon)) for _ in range(branch_count)]
        reserve = [cp.Variable((areas, horizon + 1)) for _ in range(branch_count)]
        reserve_request = [cp.Variable((areas, horizon)) for _ in range(branch_count)]
        x = [[cp.Variable((n, horizon + 1)) for _ in delay_vertices] for _ in range(branch_count)]
        energy = [[cp.Variable((areas, horizon + 1)) for _ in delay_vertices] for _ in range(branch_count)]
        discharge = [[cp.Variable((areas, horizon)) for _ in delay_vertices] for _ in range(branch_count)]
        charge = [[cp.Variable((areas, horizon)) for _ in delay_vertices] for _ in range(branch_count)]
        worst_cost = cp.Variable()
        terminal_f_slack = cp.Variable(nonneg=True) if restoration else 0.0
        terminal_ace_slack = cp.Variable(nonneg=True) if restoration else 0.0
        terminal_tie_slack = cp.Variable(nonneg=True) if restoration else 0.0
        constraints: list[cp.Constraint] = []
        x0 = self._state_from_observation(inputs.observation)
        energy0 = np.asarray(inputs.observation.measured_soc) * self.plant.parameters.bess.energy_mwh
        load = np.asarray(inputs.load_estimate_pu, dtype=float)

        contract_upper = np.asarray(self.contract.upper_power_pu)
        contract_lower = np.asarray(self.contract.lower_power_pu)
        contract_ramp_up = np.asarray(self.contract.ramp_up_pu_per_s)
        contract_ramp_down = np.asarray(self.contract.ramp_down_pu_per_s)
        online_power = np.maximum(
            np.asarray(inputs.deliverability_set.performance_power_pu), contract_upper
        )
        online_ramp = np.maximum(
            np.asarray(inputs.deliverability_set.performance_ramp_pu_per_s), contract_ramp_up
        )
        surplus_limit = np.maximum(online_power - contract_upper, 0.0)
        if inputs.contract_violation_status != "NO_DETECTED_VIOLATION":
            surplus_limit[:] = 0.0
        total_bess = guaranteed + surplus
        constraints += [
            guaranteed >= contract_lower[:, None],
            guaranteed <= contract_upper[:, None],
            surplus >= -surplus_limit[:, None],
            surplus <= surplus_limit[:, None],
            total_bess >= -online_power[:, None],
            total_bess <= online_power[:, None],
        ]
        previous_guaranteed = np.asarray(self._guaranteed_history[-1])
        previous_total = self._last_committed_action[[1, 3]]
        for k in range(horizon):
            prior_g = previous_guaranteed if k == 0 else guaranteed[:, k - 1]
            prior_total = previous_total if k == 0 else total_bess[:, k - 1]
            constraints += [
                guaranteed[:, k] - prior_g <= contract_ramp_up * self.period_s,
                prior_g - guaranteed[:, k] <= contract_ramp_down * self.period_s,
                total_bess[:, k] - prior_total <= online_ramp * self.period_s,
                prior_total - total_bess[:, k] <= online_ramp * self.period_s,
            ]

        # The complete current action is non-anticipative. Future SG and reserve
        # decisions are allowed to differ between delivered and loss branches.
        for branch in range(1, branch_count):
            constraints += [
                sg[branch][:, 0] == sg[0][:, 0],
                reserve_request[branch][:, 0] == reserve_request[0][:, 0],
            ]

        valve_lower = np.asarray(self.plant.parameters.valve_lower_pu)
        valve_upper = np.asarray(self.plant.parameters.valve_upper_pu)
        reserve_upper = np.asarray(self.plant.parameters.slow_reserve.upper_pu)
        reserve_ramp_up = np.asarray(self.plant.parameters.slow_reserve.ramp_up_pu_per_s)
        reserve_ramp_down = np.asarray(self.plant.parameters.slow_reserve.ramp_down_pu_per_s)
        reserve_tau = np.asarray(self.plant.parameters.slow_reserve.time_constant_s)
        previous_sg = self._last_committed_action[[0, 2]]
        for branch in range(branch_count):
            constraints += [
                sg[branch] >= valve_lower[:, None],
                sg[branch] <= valve_upper[:, None],
                reserve[branch][:, 0] == inputs.observation.slow_reserve_power_pu,
                reserve_request[branch] >= 0.0,
                reserve_request[branch] <= reserve_upper[:, None],
                reserve[branch] >= 0.0,
                reserve[branch] <= reserve_upper[:, None],
            ]
            for k in range(horizon):
                prior_sg = previous_sg if k == 0 else sg[branch][:, k - 1]
                constraints += [cp.abs(sg[branch][:, k] - prior_sg) <= 0.04 * self.period_s]
                raw_reserve_next = reserve[branch][:, k] + self.period_s * (
                    reserve_request[branch][:, k] - reserve[branch][:, k]
                ) / reserve_tau
                constraints += [
                    reserve[branch][:, k + 1] == raw_reserve_next,
                    reserve[branch][:, k + 1] - reserve[branch][:, k]
                    <= reserve_ramp_up * self.period_s,
                    reserve[branch][:, k] - reserve[branch][:, k + 1]
                    <= reserve_ramp_down * self.period_s,
                ]

        e_min = self.plant.parameters.bess.soc_min * self.plant.parameters.bess.energy_mwh
        e_max = self.plant.parameters.bess.soc_max * self.plant.parameters.bess.energy_mwh
        energy_factor = self.period_s * self.plant.parameters.system_base_mva / 3600.0
        branch_costs = []
        for branch_index, branch in enumerate(self.tree.branches):
            branch_cost = 0.0
            for vertex_index, delay_s in enumerate(delay_vertices):
                state = x[branch_index][vertex_index]
                stored_energy = energy[branch_index][vertex_index]
                constraints += [state[:, 0] == x0, stored_energy[:, 0] == energy0]
                constraints += [stored_energy >= e_min, stored_energy <= e_max]
                constraints += [
                    discharge[branch_index][vertex_index] >= 0.0,
                    charge[branch_index][vertex_index] >= 0.0,
                ]
                for k in range(horizon):
                    delivered_g = cp.hstack([
                        self._pipeline_expression(
                            guaranteed, k, float(delay_s), area, self._guaranteed_history
                        ) for area in range(areas)
                    ])
                    delivered_s = cp.hstack([
                        self._pipeline_expression(
                            surplus,
                            k,
                            float(delay_s + branch.extra_surplus_delay_s),
                            area,
                            self._surplus_history,
                        ) for area in range(areas)
                    ])
                    actual_bess = delivered_g + branch.surplus_delivery_fraction * delivered_s
                    effective = cp.hstack((
                        sg[branch_index][0, k], actual_bess[0],
                        sg[branch_index][1, k], actual_bess[1],
                    ))
                    constraints += [
                        state[:, k + 1]
                        == self.ad @ state[:, k] + self.bd @ effective
                        + self.ed @ load + self.rd @ reserve[branch_index][:, k]
                    ]
                    constraints += [
                        state[7:9, k] == discharge[branch_index][vertex_index][:, k]
                        - charge[branch_index][vertex_index][:, k],
                        stored_energy[:, k + 1] == stored_energy[:, k] - energy_factor * (
                            discharge[branch_index][vertex_index][:, k]
                            / self.plant.parameters.bess.eta_discharge
                            - self.plant.parameters.bess.eta_charge
                            * charge[branch_index][vertex_index][:, k]
                        ),
                    ]
                    rating = self.plant.parameters.bess.rating_pu
                    constraints += [state[7:9, k] >= -rating, state[7:9, k] <= rating]
                    prior_pb = self._last_actual_bess if k == 0 else state[7:9, k - 1]
                    constraints += [cp.abs(state[7:9, k] - prior_pb) <= 0.10 * self.period_s]
                    constraints += [
                        state[3:5, k] >= valve_lower,
                        state[3:5, k] <= valve_upper,
                        state[5:7, k] >= self.plant.parameters.sg_power_lower_pu,
                        state[5:7, k] <= self.plant.parameters.sg_power_upper_pu,
                        cp.abs(state[0:2, k + 1]) <= 0.030,
                        cp.abs(state[2, k + 1]) <= 0.12,
                        cp.abs(self.ace_matrix @ state[:, k + 1]) <= 0.45,
                    ]
                    ace = self.ace_matrix @ state[:, k + 1]
                    branch_cost += (
                        35.0 * cp.sum_squares(ace)
                        + 15.0 * cp.sum_squares(state[0:2, k + 1])
                        + 5.0 * cp.square(state[2, k + 1])
                    ) / vertex_count
                if inputs.domain.domain == "SUSTAINABLE":
                    constraints += [
                        cp.abs(state[0:2, horizon]) <= 0.004 + terminal_f_slack,
                        cp.abs(self.ace_matrix @ state[:, horizon]) <= 0.05 + terminal_ace_slack,
                        cp.abs(state[2, horizon]) <= 0.025 + terminal_tie_slack,
                    ]
                elif inputs.domain.domain == "BRIDGE":
                    constraints += [
                        reserve[branch_index][:, horizon] >= reserve[branch_index][:, 0]
                    ]
            branch_costs.append(branch_cost)
            constraints += [branch_cost <= worst_cost]

        shared_effort = (
            0.04 * cp.sum_squares(guaranteed)
            + 0.0001 * cp.sum_squares(surplus)
            + 0.06 * sum(cp.sum_squares(value) for value in sg)
            + 0.015 * sum(cp.sum_squares(value) for value in reserve_request)
        )
        # A small secondary delivered-branch term allocates verified surplus
        # when it does not worsen the loss-branch epigraph. Its coefficient is
        # deliberately subordinate to the unit-weight worst-branch risk.
        expected_delivered_performance = 0.05 * branch_costs[0]
        slack_penalty = 0.0
        if restoration:
            slack_penalty = (
                1.0e6 * terminal_f_slack
                + 5.0e5 * terminal_ace_slack
                + 5.0e5 * terminal_tie_slack
            )
        problem = cp.Problem(
            cp.Minimize(worst_cost + expected_delivered_performance + shared_effort + slack_penalty),
            constraints,
        )
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
        except Exception:
            return None, "NUMERICAL_EXCEPTION", time.perf_counter() - started, 0, np.inf
        solve_time = time.perf_counter() - started
        status = str(problem.status)
        iterations = int(getattr(problem.solver_stats, "num_iters", 0) or 0)
        if status not in {"optimal", "optimal_inaccurate"} or guaranteed.value is None:
            return None, status, solve_time, iterations, np.inf
        residual = max(
            (float(np.max(np.abs(value))) for constraint in constraints
             if (value := constraint.violation()) is not None),
            default=0.0,
        )
        solution = {
            "status": status,
            "objective": float(problem.value),
            "solve_time": solve_time,
            "iterations": iterations,
            "residual": residual,
            "guaranteed": np.asarray(guaranteed.value),
            "surplus": np.asarray(surplus.value),
            "sg": np.stack([np.asarray(value.value) for value in sg]),
            "reserve": np.stack([np.asarray(value.value) for value in reserve]),
            "reserve_request": np.stack([np.asarray(value.value) for value in reserve_request]),
            "states": np.stack([[np.asarray(value.value) for value in branch] for branch in x]),
            "energy": np.stack([[np.asarray(value.value) for value in branch] for branch in energy]),
            "delay_vertices": delay_vertices,
            "e_min": e_min,
            "e_max": e_max,
        }
        return solution, status, solve_time, iterations, residual

    def _result_from_solution(
        self,
        inputs: DCSVInput,
        solution: dict,
        *,
        restoration_used: bool,
        attempted_calls: int,
        primary_status: str,
        restoration_status: str,
    ) -> DCSVCRResult:
        guaranteed = solution["guaranteed"]
        surplus = solution["surplus"]
        sg = solution["sg"]
        total = guaranteed + surplus
        action = np.array((sg[0, 0, 0], total[0, 0], sg[0, 1, 0], total[1, 0]))
        states = solution["states"]
        energy = solution["energy"]
        predicted_inputs = np.empty((len(self.tree.branches), 4, self.horizon_steps))
        predicted_inputs[:, 0, :] = sg[:, 0, :]
        predicted_inputs[:, 1, :] = total[None, 0, :]
        predicted_inputs[:, 2, :] = sg[:, 1, :]
        predicted_inputs[:, 3, :] = total[None, 1, :]
        hard_margin = min(
            float(np.min(np.asarray(self.contract.upper_power_pu)[:, None] - np.abs(guaranteed))),
            float(self.plant.parameters.bess.rating_pu - np.max(np.abs(states[..., 7:9, :-1]))),
        )
        energy_margin = min(
            float(np.min(energy - solution["e_min"])),
            float(np.min(solution["e_max"] - energy)),
        )
        diagnostics = DCSVCRSolverDiagnostics(
            status=solution["status"],
            objective=solution["objective"],
            solve_time_s=solution["solve_time"],
            iterations=solution["iterations"],
            maximum_constraint_residual=solution["residual"],
            branch_count=len(self.tree.branches),
            delay_vertex_count=len(solution["delay_vertices"]),
            hard_margin_pu=hard_margin,
            energy_margin_mwh=energy_margin,
            restoration_used=restoration_used,
            fallback_used=False,
            mathematical_infeasibility=False,
            numerical_failure=solution["status"] == "optimal_inaccurate",
            attempted_optimization_calls=attempted_calls,
            primary_status=primary_status,
            restoration_status=restoration_status,
        )
        return DCSVCRResult(
            proposed_action_pu=action,
            guaranteed_bess_command_pu=guaranteed[:, 0].copy(),
            surplus_bess_command_pu=surplus[:, 0].copy(),
            slow_reserve_request_pu=solution["reserve_request"][0, :, 0].copy(),
            predicted_state_sequence=states,
            predicted_input_sequence=predicted_inputs,
            predicted_guaranteed_bess_sequence_pu=guaranteed.copy(),
            predicted_surplus_bess_sequence_pu=surplus.copy(),
            predicted_energy_sequence_mwh=energy,
            predicted_slow_reserve_sequence_pu=solution["reserve"],
            branch_names=tuple(branch.name for branch in self.tree.branches),
            delay_vertices_s=solution["delay_vertices"],
            shared_current_action_verified=bool(
                np.max(np.abs(sg[:, :, 0] - sg[0, :, 0])) <= 1e-7
            ),
            surplus_loss_branch_verified=True,
            domain=inputs.domain.domain,
            bridge_remaining_s=float(max(self._bridge_remaining_s or 0.0, 0.0)),
            diagnostics=diagnostics,
        )

    def _fallback(
        self,
        inputs: DCSVInput,
        attempted_calls: int,
        primary_status: str,
        restoration_status: str,
    ) -> DCSVCRResult:
        ace = np.asarray(inputs.observation.ace_pu)
        total = np.clip(-0.32 * ace, -0.08, 0.08)
        guaranteed = np.clip(
            0.25 * total,
            np.asarray(self.contract.lower_power_pu),
            np.asarray(self.contract.upper_power_pu),
        )
        sg = total - guaranteed
        action = np.array((sg[0], guaranteed[0], sg[1], guaranteed[1]))
        mathematical = "infeasible" in (primary_status + restoration_status).lower()
        diagnostics = DCSVCRSolverDiagnostics(
            status=("PHYSICAL_INFEASIBILITY_CERTIFICATE" if inputs.domain.domain == "PHYSICALLY_INFEASIBLE" else "CONTRACT_SAFE_FALLBACK"),
            objective=np.nan,
            solve_time_s=0.0,
            iterations=0,
            maximum_constraint_residual=0.0,
            branch_count=len(self.tree.branches),
            delay_vertex_count=2,
            hard_margin_pu=float(np.min(np.asarray(self.contract.upper_power_pu) - np.abs(guaranteed))),
            energy_margin_mwh=float(np.min(
                inputs.observation.measured_soc * self.plant.parameters.bess.energy_mwh
                - self.plant.parameters.bess.soc_min * self.plant.parameters.bess.energy_mwh
            )),
            restoration_used=False,
            fallback_used=inputs.domain.domain != "PHYSICALLY_INFEASIBLE",
            mathematical_infeasibility=mathematical,
            numerical_failure=not mathematical and attempted_calls > 0,
            attempted_optimization_calls=attempted_calls,
            primary_status=primary_status,
            restoration_status=restoration_status,
        )
        horizon = self.horizon_steps
        x0 = self._state_from_observation(inputs.observation)
        energy0 = inputs.observation.measured_soc * self.plant.parameters.bess.energy_mwh
        return DCSVCRResult(
            proposed_action_pu=action,
            guaranteed_bess_command_pu=guaranteed,
            surplus_bess_command_pu=np.zeros(2),
            slow_reserve_request_pu=np.asarray(inputs.domain.equilibrium_slow_reserve_pu),
            predicted_state_sequence=np.tile(x0, (2, 2, horizon + 1, 1)).transpose(0, 1, 3, 2),
            predicted_input_sequence=np.zeros((2, 4, horizon)),
            predicted_guaranteed_bess_sequence_pu=np.tile(guaranteed[:, None], (1, horizon)),
            predicted_surplus_bess_sequence_pu=np.zeros((2, horizon)),
            predicted_energy_sequence_mwh=np.tile(energy0, (2, 2, horizon + 1, 1)).transpose(0, 1, 3, 2),
            predicted_slow_reserve_sequence_pu=np.zeros((2, 2, horizon + 1)),
            branch_names=tuple(branch.name for branch in self.tree.branches),
            delay_vertices_s=np.array((0.0, max(self.contract.maximum_delay_s))),
            shared_current_action_verified=True,
            surplus_loss_branch_verified=True,
            domain=inputs.domain.domain,
            bridge_remaining_s=float(max(self._bridge_remaining_s or 0.0, 0.0)),
            diagnostics=diagnostics,
        )

    def propose(self, inputs: DCSVInput) -> DCSVCRResult:
        if self._bridge_remaining_s is None or inputs.domain.domain != "BRIDGE":
            self._bridge_remaining_s = float(inputs.domain.bridge_remaining_s)
        else:
            self._bridge_remaining_s = max(self._bridge_remaining_s - self.period_s, 0.0)
        if inputs.domain.domain == "PHYSICALLY_INFEASIBLE":
            return self._fallback(inputs, 0, "NOT_ATTEMPTED", "NOT_ATTEMPTED")
        primary, primary_status, _, _, _ = self._solve(inputs, restoration=False)
        if primary is not None:
            return self._result_from_solution(
                inputs,
                primary,
                restoration_used=False,
                attempted_calls=1,
                primary_status=primary_status,
                restoration_status="NOT_ATTEMPTED",
            )
        restored, restoration_status, _, _, _ = self._solve(inputs, restoration=True)
        if restored is not None:
            return self._result_from_solution(
                inputs,
                restored,
                restoration_used=True,
                attempted_calls=2,
                primary_status=primary_status,
                restoration_status=restoration_status,
            )
        return self._fallback(inputs, 2, primary_status, restoration_status)


__all__ = ["DCSVCRResult", "DCSVCRSolverDiagnostics", "DCSVContractRecourseMPC"]
