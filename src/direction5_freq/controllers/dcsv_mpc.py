"""Disturbance--Capability-Separated Viability MPC."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import cvxpy as cp
import numpy as np

from direction1freq.models.delay_augmented_prediction import exact_fractional_delay_vertex
from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2
from direction5_freq.controllers.bridge_viability_mpc import BridgeState
from direction5_freq.controllers.domain_supervisor import DomainDecision, DomainSupervisor
from direction5_freq.controllers.feasibility_restoration import RestorationPolicy
from direction5_freq.models.sustainability_classifier import CapabilityContract


@dataclass(frozen=True, slots=True)
class DCSVInput:
    state_estimate_pu: np.ndarray
    load_estimate_pu: np.ndarray
    previous_actual_action_pu: np.ndarray
    actual_bess_power_pu: np.ndarray
    energy_state_mwh: np.ndarray
    power_discharge_guaranteed_pu: np.ndarray
    power_charge_guaranteed_pu: np.ndarray
    ramp_up_guaranteed_pu_per_s: np.ndarray
    ramp_down_guaranteed_pu_per_s: np.ndarray
    delay_interval_s: np.ndarray
    energy_available_guaranteed_mwh: np.ndarray
    availability_interval: np.ndarray
    time_to_slow_reserve_s: float = 60.0

    def validate(self) -> None:
        vector_shapes = {
            "state_estimate_pu": (self.state_estimate_pu, (9,)),
            "load_estimate_pu": (self.load_estimate_pu, (2,)),
            "previous_actual_action_pu": (self.previous_actual_action_pu, (4,)),
            "actual_bess_power_pu": (self.actual_bess_power_pu, (2,)),
            "energy_state_mwh": (self.energy_state_mwh, (2,)),
            "power_discharge_guaranteed_pu": (
                self.power_discharge_guaranteed_pu,
                (2,),
            ),
            "power_charge_guaranteed_pu": (self.power_charge_guaranteed_pu, (2,)),
            "ramp_up_guaranteed_pu_per_s": (
                self.ramp_up_guaranteed_pu_per_s,
                (2,),
            ),
            "ramp_down_guaranteed_pu_per_s": (
                self.ramp_down_guaranteed_pu_per_s,
                (2,),
            ),
            "delay_interval_s": (self.delay_interval_s, (2, 2)),
            "energy_available_guaranteed_mwh": (
                self.energy_available_guaranteed_mwh,
                (2,),
            ),
            "availability_interval": (self.availability_interval, (2, 2)),
        }
        for name, (value, shape) in vector_shapes.items():
            if np.asarray(value).shape != shape:
                raise ValueError(f"{name} must have shape {shape}")
        if not all(np.all(np.isfinite(value)) for value, _shape in vector_shapes.values()):
            raise ValueError("DCSV inputs must be finite")


@dataclass(frozen=True, slots=True)
class DCSVDiagnostics:
    method: str
    domain: str
    domain_certificate_kind: str
    solved: bool
    primary_status: str
    restoration_status: str
    restoration_used: bool
    fallback_used: bool
    physical_infeasibility_preclassified: bool
    solver_name: str
    solve_time_s: float
    objective: float
    hard_constraint_residual: float
    performance_slack: float
    terminal_slack: float
    scenario_count: int
    prediction_horizon: int
    common_control_sequence: bool
    predicted_states: np.ndarray
    predicted_actions: np.ndarray
    predicted_energy_used_mwh: np.ndarray
    previous_actual_action_pu: np.ndarray
    applied_action_pu: np.ndarray
    first_predicted_action_pu: np.ndarray
    action_history_match: bool
    physical_hard_violation: bool
    finite_horizon_only: bool
    recursive_feasibility_claimed: bool
    failure_reason: str


@dataclass(slots=True)
class _SolveResult:
    accepted: bool
    status: str
    objective: float
    residual: float
    performance_slack: float
    terminal_slack: float
    actions: np.ndarray
    states: np.ndarray
    energy_used: np.ndarray
    scenario_count: int


class DisturbanceCapabilitySeparatedViabilityMPC:
    """True receding-horizon robust MPC with one common control sequence."""

    method_name = "DCSV-MPC"
    evaluation_only = False

    def __init__(
        self,
        period_s: float = 4.0,
        horizon: int = 6,
        plant: str = "A",
        sg_reserve_pu: float = 0.10,
        slow_reserve_arrival_s: float | None = 60.0,
    ) -> None:
        self.period_s = float(period_s)
        self.horizon = int(horizon)
        self.plant_name = str(plant)
        self.sg_reserve = float(sg_reserve_pu)
        self.supervisor = DomainSupervisor(
            period_s, plant, sg_reserve_pu, slow_reserve_arrival_s
        )
        self.restoration_policy = RestorationPolicy()
        self.plant = TwoAreaPlantAV2()
        _a, _b, self.c_ace, _e = self.plant.linear_continuous_model_separate()
        self.nominal_frequency_hz = 50.0 if plant == "A" else 60.0
        self.pfr_gain = self.plant.parameters.bess.pfr_gain_pu_power_per_pu_frequency
        self.previous_applied_action = np.zeros(4)
        self.bridge_state: BridgeState | None = None
        self._terminal_radius = self._load_terminal_radius()
        self.terminal_generator_matrix = self._load_certified_terminal_object()

    def _load_certified_terminal_object(self) -> np.ndarray | None:
        path = (
            Path(__file__).resolve().parents[3]
            / "research_outputs_phase_h/05_THEORY/SUSTAINABLE_TERMINAL_SET.npz"
        )
        if not path.is_file():
            return None
        data = np.load(path)
        matches = np.flatnonzero(
            (data["plants"].astype(str) == self.plant_name)
            & np.isclose(data["periods_s"].astype(float), self.period_s)
        )
        if len(matches) != 1:
            return None
        index = int(matches[0])
        if not bool(
            data["invariant"][index]
            and data["admissible"][index]
            and data["terminal_radius_compatible"][index]
        ):
            return None
        columns = int(data["generator_columns"][index])
        return np.asarray(
            data["generator_matrices_padded"][index, :, :columns], dtype=float
        )

    def _load_terminal_radius(self) -> np.ndarray:
        path = (
            Path(__file__).resolve().parents[3]
            / "research_outputs_phase_h/03_MODEL/LOCAL_TERMINAL_SET.npz"
        )
        neighborhood = np.array(
            [0.003, 0.003, 0.020, 0.025, 0.025, 0.025, 0.025, 0.015, 0.015]
        )
        if not path.is_file():
            return neighborhood
        data = np.load(path)
        plant_index = int(np.flatnonzero(data["plants"] == self.plant_name)[0])
        period_index = int(np.flatnonzero(data["periods_s"] == self.period_s)[0])
        horizons = data["horizons_steps"].astype(int)
        horizon_index = (
            int(np.flatnonzero(horizons >= self.horizon)[0])
            if np.any(horizons >= self.horizon)
            else len(horizons) - 1
        )
        return neighborhood + data["state_prediction_radii"][
            plant_index, period_index, horizon_index
        ]

    def reset(self) -> None:
        self.previous_applied_action = np.zeros(4)
        self.bridge_state = None

    def _capability_contract(self, data: DCSVInput) -> CapabilityContract:
        # Power/ramp bounds are composite delivered-capability guarantees; the
        # availability interval is retained for audit and must not be multiplied
        # a second time into the same delivered-power bound.
        service_possible = (data.availability_interval[:, 1] > 0.0).astype(float)
        return CapabilityContract(
            "online_public_io_guaranteed_set",
            "online",
            -np.asarray(data.power_charge_guaranteed_pu) * service_possible,
            np.asarray(data.power_discharge_guaranteed_pu) * service_possible,
            np.asarray(data.ramp_down_guaranteed_pu_per_s) * service_possible,
            np.asarray(data.ramp_up_guaranteed_pu_per_s) * service_possible,
            np.max(np.asarray(data.delay_interval_s), axis=1),
            np.asarray(data.energy_available_guaranteed_mwh),
            service_possible,
        )

    def _delay_points(self, data: DCSVInput) -> np.ndarray:
        lower = float(np.min(data.delay_interval_s[:, 0]))
        upper = float(np.max(data.delay_interval_s[:, 1]))
        upper = min(upper, self.period_s - 1e-5)
        lower = min(max(lower, 0.0), upper)
        return np.unique(np.array([lower, 0.5 * (lower + upper), upper]))

    def _guaranteed_limits(self, data: DCSVInput) -> tuple[np.ndarray, ...]:
        return (
            np.asarray(data.power_discharge_guaranteed_pu, dtype=float),
            np.asarray(data.power_charge_guaranteed_pu, dtype=float),
            np.asarray(data.ramp_up_guaranteed_pu_per_s, dtype=float),
            np.asarray(data.ramp_down_guaranteed_pu_per_s, dtype=float),
            np.asarray(data.energy_available_guaranteed_mwh, dtype=float),
        )

    @staticmethod
    def _maximum_violation(constraints: list[cp.Constraint]) -> float:
        residual = 0.0
        for constraint in constraints:
            try:
                value = np.asarray(constraint.violation(), dtype=float)
            except (TypeError, ValueError):
                return float("inf")
            if value.size and np.all(np.isfinite(value)):
                residual = max(residual, float(np.max(np.abs(value))))
        return residual

    def _solve_problem(
        self,
        data: DCSVInput,
        decision: DomainDecision,
        restoration: bool,
    ) -> _SolveResult:
        horizon = self.horizon
        delays = self._delay_points(data)
        vertices = [
            exact_fractional_delay_vertex(self.period_s, float(delay))
            for delay in delays
        ]
        p_dis, p_chg, ramp_up, ramp_down, energy_available = self._guaranteed_limits(data)
        u = cp.Variable((4, horizon), name="common_control_sequence")
        states = [cp.Variable((9, horizon + 1), name=f"x_delay_{i}") for i in range(len(vertices))]
        discharge = [cp.Variable((2, horizon), nonneg=True) for _ in vertices]
        charge = [cp.Variable((2, horizon), nonneg=True) for _ in vertices]
        energy_used = [cp.Variable((2, horizon + 1), nonneg=True) for _ in vertices]
        performance_slack = cp.Variable(nonneg=True, name="performance_restoration")
        terminal_slack = cp.Variable(nonneg=True, name="settling_restoration")
        if not restoration:
            slack_constraints = [performance_slack == 0.0, terminal_slack == 0.0]
        else:
            slack_constraints = [performance_slack <= 0.50, terminal_slack <= 0.05]
        constraints: list[cp.Constraint] = list(slack_constraints)
        common_cost = 0.02 * cp.sum_squares(u)
        reference = (
            decision.result.equilibrium.state_pu
            if decision.result.equilibrium.feasible
            else decision.result.slow_reserve_equilibrium.state_pu
        )
        if not np.all(np.isfinite(reference)):
            reference = np.zeros(9)
        previous_action = np.asarray(data.previous_actual_action_pu, dtype=float)
        for scenario, vertex in enumerate(vertices):
            constraints.extend(
                [
                    states[scenario][:, 0] == data.state_estimate_pu,
                    energy_used[scenario][:, 0] == 0.0,
                ]
            )
            previous_total = np.asarray(data.actual_bess_power_pu, dtype=float)
            for stage in range(horizon):
                prior = previous_action if stage == 0 else u[:, stage - 1]
                constraints.append(
                    states[scenario][:, stage + 1]
                    == vertex.ad @ states[scenario][:, stage]
                    + vertex.b_current @ u[:, stage]
                    + vertex.b_previous @ prior
                    + vertex.ed @ data.load_estimate_pu
                )
                total_bess = u[[1, 3], stage] - self.pfr_gain * states[scenario][:2, stage]
                constraints.extend(
                    [
                        u[[0, 2], stage] >= -self.sg_reserve,
                        u[[0, 2], stage] <= self.sg_reserve,
                        total_bess == discharge[scenario][:, stage] - charge[scenario][:, stage],
                        total_bess <= p_dis,
                        total_bess >= -p_chg,
                        total_bess - previous_total <= self.period_s * ramp_up,
                        previous_total - total_bess <= self.period_s * ramp_down,
                        states[scenario][5:7, stage + 1] >= -self.sg_reserve,
                        states[scenario][5:7, stage + 1] <= self.sg_reserve,
                    ]
                )
                constraints.append(
                    energy_used[scenario][:, stage + 1]
                    == energy_used[scenario][:, stage]
                    + self.period_s
                    * 1000.0
                    / 3600.0
                    * (
                        discharge[scenario][:, stage] / 0.95
                        + 0.95 * charge[scenario][:, stage]
                    )
                )
                constraints.append(
                    energy_used[scenario][:, stage + 1] <= energy_available
                )
                frequency = self.nominal_frequency_hz * states[scenario][:2, stage + 1]
                ace = self.c_ace @ states[scenario][:, stage + 1]
                constraints.extend(
                    [
                        cp.abs(frequency) <= 0.80 + performance_slack,
                        cp.abs(ace) <= 0.30 + performance_slack,
                        cp.abs(states[scenario][2, stage + 1])
                        <= 0.15 + performance_slack,
                    ]
                )
                common_cost += (
                    300.0 * cp.sum_squares(states[scenario][:2, stage + 1])
                    + 80.0 * cp.sum_squares(self.c_ace @ states[scenario][:, stage + 1])
                    + 2.0 * cp.sum(discharge[scenario][:, stage] + charge[scenario][:, stage])
                )
                previous_total = total_bess
            terminal = states[scenario][:, horizon]
            if decision.classification == "SUSTAINABLE":
                if self.terminal_generator_matrix is not None and not restoration:
                    coefficient = cp.Variable(
                        self.terminal_generator_matrix.shape[1],
                        name=f"terminal_zonotope_coefficient_{scenario}",
                    )
                    terminal_augmented = cp.hstack(
                        [
                            terminal - reference,
                            u[[0, 2], horizon - 1] - reference[5:7],
                        ]
                    )
                    constraints.extend(
                        [
                            terminal_augmented
                            == self.terminal_generator_matrix @ coefficient,
                            cp.norm_inf(coefficient) <= 1.0,
                        ]
                    )
                else:
                    constraints.append(
                        cp.abs(terminal - reference)
                        <= self._terminal_radius + terminal_slack
                    )
                # The certified shift policy is SG-only; a residual issued BESS
                # command would leave an unmodelled delay-pipeline input.
                constraints.append(u[[1, 3], horizon - 1] == 0.0)
            else:
                remaining = max(
                    min(float(data.time_to_slow_reserve_s), horizon * self.period_s),
                    self.period_s,
                )
                required = np.asarray(decision.result.bridge_bess_power_pu, dtype=float)
                constraints.append(
                    cp.abs(u[[1, 3], horizon - 1] - required)
                    <= 0.03 + terminal_slack
                )
                constraints.append(
                    energy_used[scenario][:, horizon]
                    <= energy_available
                    * min(horizon * self.period_s / remaining, 1.0)
                    + 1e-9
                )
        objective = cp.Minimize(
            common_cost
            + 1e5 * performance_slack
            + 2e5 * terminal_slack
        )
        problem = cp.Problem(objective, constraints)
        try:
            value = problem.solve(
                solver=cp.CLARABEL,
                warm_start=True,
                tol_gap_abs=1e-7,
                tol_gap_rel=1e-7,
                tol_feas=1e-7,
                max_iter=1000,
                verbose=False,
            )
            status = str(problem.status)
        except Exception as error:
            value = float("nan")
            status = f"exception:{type(error).__name__}"
        residual = self._maximum_violation(constraints)
        accepted = bool(
            status in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE}
            and np.isfinite(value)
            and residual <= 1e-5
            and u.value is not None
        )
        if not accepted:
            return _SolveResult(
                False,
                status,
                float(value) if np.isfinite(value) else float("nan"),
                residual,
                float("nan"),
                float("nan"),
                np.full((horizon, 4), np.nan),
                np.full((len(vertices), horizon + 1, 9), np.nan),
                np.full((len(vertices), horizon + 1, 2), np.nan),
                len(vertices),
            )
        return _SolveResult(
            True,
            status,
            float(value),
            residual,
            float(performance_slack.value),
            float(terminal_slack.value),
            np.asarray(u.value).T,
            np.asarray([np.asarray(item.value).T for item in states]),
            np.asarray([np.asarray(item.value).T for item in energy_used]),
            len(vertices),
        )

    def _emergency_action(self, load_estimate: np.ndarray) -> np.ndarray:
        sg = np.clip(np.asarray(load_estimate, dtype=float), -self.sg_reserve, self.sg_reserve)
        return np.array([sg[0], 0.0, sg[1], 0.0])

    def control(self, data: DCSVInput) -> tuple[np.ndarray, DCSVDiagnostics]:
        data.validate()
        started = perf_counter()
        contract = self._capability_contract(data)
        decision = self.supervisor.classify(data.load_estimate_pu, contract)
        expected_previous = self.previous_applied_action.copy()
        prior = np.asarray(data.previous_actual_action_pu, dtype=float).copy()
        if decision.classification.startswith("PHYSICALLY_INFEASIBLE"):
            action = self._emergency_action(data.load_estimate_pu)
            horizon_actions = np.tile(action, (self.horizon, 1))
            horizon_states = np.tile(
                np.asarray(data.state_estimate_pu), (1, self.horizon + 1, 1)
            )
            result = _SolveResult(
                False,
                "NOT_SOLVED_PRECLASSIFIED_PHYSICAL_INFEASIBILITY",
                float("nan"),
                0.0,
                0.0,
                0.0,
                horizon_actions,
                horizon_states,
                np.zeros((1, self.horizon + 1, 2)),
                0,
            )
            primary_status = result.status
            restoration_status = "NOT_ATTEMPTED"
            restoration_used = False
            fallback = False
            reason = decision.result.reason
        else:
            primary = self._solve_problem(data, decision, restoration=False)
            primary_status = primary.status
            restoration_status = "NOT_ATTEMPTED"
            restoration_used = False
            fallback = False
            reason = ""
            result = primary
            if not primary.accepted:
                restored = self._solve_problem(data, decision, restoration=True)
                restoration_status = restored.status
                restoration_used = restored.accepted
                result = restored if restored.accepted else primary
            if result.accepted:
                action = result.actions[0].copy()
            else:
                action = self._emergency_action(data.load_estimate_pu)
                fallback = True
                reason = "primary_and_registered_restoration_not_accepted"
        self.previous_applied_action = action.copy()
        if decision.classification == "BRIDGE_ONLY":
            required = np.asarray(decision.result.bridge_bess_power_pu, dtype=float)
            self.bridge_state = BridgeState(
                float(data.time_to_slow_reserve_s),
                np.asarray(data.energy_available_guaranteed_mwh, dtype=float),
                required,
                self.supervisor.slow_reserve_arrival_s is not None,
            ).advance(data.actual_bess_power_pu, self.period_s)
        solved = result.accepted
        first = result.actions[0].copy() if solved else action.copy()
        history_match = bool(np.allclose(expected_previous, prior, atol=1e-12))
        physical_violation = bool(solved and result.residual > 1e-5)
        diagnostics = DCSVDiagnostics(
            self.method_name,
            decision.classification,
            decision.certificate_kind,
            solved,
            primary_status,
            restoration_status,
            restoration_used,
            fallback,
            decision.classification.startswith("PHYSICALLY_INFEASIBLE"),
            "CLARABEL",
            perf_counter() - started,
            result.objective,
            result.residual,
            result.performance_slack,
            result.terminal_slack,
            result.scenario_count,
            self.horizon,
            True,
            result.states,
            result.actions,
            result.energy_used,
            prior,
            action.copy(),
            first,
            history_match,
            physical_violation,
            decision.classification != "SUSTAINABLE"
            or restoration_used
            or fallback,
            False,
            reason,
        )
        return action, diagnostics
