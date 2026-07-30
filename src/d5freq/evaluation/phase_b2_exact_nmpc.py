"""Evaluation-only multi-action nonlinear NMPC for Phase B2.

O2 knows the current simulator state and current physical regime parameters,
but it does not know future load or future regime. O3 may receive a fixed
future load/regime schedule and is explicitly clairvoyant. Both use IPOPT and
multiple shooting. A successful local solve is never labelled globally
optimal.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

from d5freq.models.two_area_plant_b import (
    PlantBParameters,
    PlantBStateIndex,
    TwoAreaPlantB,
    UpperCommand,
)


FloatArray = NDArray[np.float64]
_CASADI_DLL_HANDLE: Any | None = None


def _load_casadi() -> Any:
    """Load CasADi while retaining Conda's Windows DLL search handle."""

    global _CASADI_DLL_HANDLE
    if os.name == "nt" and _CASADI_DLL_HANDLE is None:
        library_bin = Path(sys.prefix) / "Library" / "bin"
        if library_bin.is_dir() and hasattr(os, "add_dll_directory"):
            _CASADI_DLL_HANDLE = os.add_dll_directory(str(library_bin))
            existing_path = os.environ.get("PATH", "")
            path_parts = existing_path.split(os.pathsep)
            if str(library_bin) not in path_parts:
                os.environ["PATH"] = str(library_bin) + os.pathsep + existing_path
    import casadi as ca

    return ca


@dataclass(frozen=True, slots=True)
class ExactNMPCConfig:
    horizon_s: float = 8.0
    command_interval_s: float = 2.0
    integration_step_s: float = 0.10
    q_frequency: float = 8000.0
    q_ace: float = 4000.0
    q_tie_line: float = 1000.0
    r_sg: float = 5.0
    r_ibr: float = 8.0
    s_sg: float = 2.0
    s_ibr: float = 3.0
    terminal_multiplier: float = 5.0
    frequency_bound_hz: float = 0.50
    tie_line_bound_pu: float = 0.20
    ibr_command_delta_bound_pu: float = 0.08
    ipopt_tolerance: float = 1.0e-6
    ipopt_acceptable_tolerance: float = 1.0e-1
    solver_constraint_qualification_tolerance: float = 1.0e-4
    solver_kkt_qualification_tolerance: float = 1.0e-1
    ipopt_max_iterations: int = 500

    def __post_init__(self) -> None:
        positive_fields = (
            "horizon_s",
            "command_interval_s",
            "integration_step_s",
            "q_frequency",
            "q_ace",
            "q_tie_line",
            "r_sg",
            "r_ibr",
            "s_sg",
            "s_ibr",
            "terminal_multiplier",
            "frequency_bound_hz",
            "tie_line_bound_pu",
            "ibr_command_delta_bound_pu",
            "ipopt_tolerance",
            "ipopt_acceptable_tolerance",
            "solver_constraint_qualification_tolerance",
            "solver_kkt_qualification_tolerance",
        )
        for name in positive_fields:
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
            object.__setattr__(self, name, value)
        if int(self.ipopt_max_iterations) <= 0:
            raise ValueError("ipopt_max_iterations must be positive")
        object.__setattr__(self, "ipopt_max_iterations", int(self.ipopt_max_iterations))
        blocks = self.horizon_s / self.command_interval_s
        substeps = self.command_interval_s / self.integration_step_s
        if not math.isclose(blocks, round(blocks), abs_tol=1.0e-12):
            raise ValueError("horizon must contain an integer number of commands")
        if not math.isclose(substeps, round(substeps), abs_tol=1.0e-12):
            raise ValueError("command interval must contain integer integration steps")

    @property
    def number_of_control_blocks(self) -> int:
        return round(self.horizon_s / self.command_interval_s)

    @property
    def integration_steps_per_block(self) -> int:
        return round(self.command_interval_s / self.integration_step_s)


@dataclass(frozen=True, slots=True)
class OracleSolveRecord:
    oracle_level: str
    solver_status: str
    success: bool
    local_optimum_only: bool
    global_optimality_claim: bool
    objective: float
    iterations: int
    kkt_residual_inf: float
    raw_stationarity_inf: float
    max_constraint_residual: float
    wall_time_s: float
    horizon_s: float
    control_blocks: int
    independent_actions: int
    initializations_attempted: int
    selected_initialization: str
    command: UpperCommand
    action_sequence: FloatArray
    state_nodes: FloatArray


def _numeric_clip(value: FloatArray, lower: FloatArray, upper: FloatArray) -> FloatArray:
    return np.minimum(np.maximum(value, lower), upper)


class ExactMultipleShootingNMPC:
    """Parametric O2/O3 nonlinear program with one action per control block."""

    evaluation_only = True
    uses_true_internal_state = True
    uses_true_regime = True
    global_optimality_claim = False

    def __init__(
        self,
        plant_parameters: PlantBParameters,
        *,
        regime_schedule: Sequence[Sequence[str]],
        config: ExactNMPCConfig | None = None,
        oracle_level: str = "O2",
    ) -> None:
        self.params = plant_parameters
        self.config = ExactNMPCConfig() if config is None else config
        self.oracle_level = str(oracle_level)
        if self.oracle_level not in {"O2", "O3"}:
            raise ValueError("oracle_level must be O2 or O3")
        if not math.isclose(
            self.config.command_interval_s,
            self.params.upper_control_period_s,
            abs_tol=1.0e-12,
        ):
            raise ValueError("NMPC and plant command intervals must match")
        schedule = tuple(tuple(str(value) for value in row) for row in regime_schedule)
        if len(schedule) != self.config.number_of_control_blocks:
            raise ValueError("regime schedule must contain one pair per control block")
        for row in schedule:
            if len(row) != 2 or any(value not in self.params.regimes for value in row):
                raise ValueError("regime schedule contains an invalid area pair")
        if self.oracle_level == "O2" and any(row != schedule[0] for row in schedule[1:]):
            raise ValueError("O2 may not receive a future regime schedule")
        self.regime_schedule = schedule
        self._ca = _load_casadi()
        self._warm: dict[str, FloatArray] = {}
        self._build_problem()

    @classmethod
    def for_current_regime(
        cls,
        plant_parameters: PlantBParameters,
        current_regime_ids: Sequence[str],
        *,
        config: ExactNMPCConfig | None = None,
    ) -> "ExactMultipleShootingNMPC":
        resolved = ExactNMPCConfig() if config is None else config
        pair = tuple(str(value) for value in current_regime_ids)
        if len(pair) != 2:
            raise ValueError("current regime requires two IDs")
        return cls(
            plant_parameters,
            regime_schedule=[pair] * resolved.number_of_control_blocks,
            config=resolved,
            oracle_level="O2",
        )

    @property
    def uses_future_load(self) -> bool:
        return self.oracle_level == "O3"

    @property
    def uses_future_regime(self) -> bool:
        return self.oracle_level == "O3"

    def _clip(self, value: Any, lower: float, upper: float) -> Any:
        return self._ca.fmin(self._ca.fmax(value, lower), upper)

    def _project_symbolic(self, state: Any) -> Any:
        ca = self._ca
        projected = [state[index] for index in range(15)]
        for area, indices in enumerate(
            (
                (0, 1, 2, 7, 8, 9, 10),
                (3, 4, 5, 11, 12, 13, 14),
            )
        ):
            _, pm, pv, _, pb, soc, availability = indices
            projected[pm] = self._clip(
                state[pm],
                -self.params.sg_capability.reserve_down_pu[area],
                self.params.sg_capability.reserve_up_pu[area],
            )
            projected[pv] = self._clip(
                state[pv],
                -self.params.sg_capability.reserve_down_pu[area],
                self.params.sg_capability.reserve_up_pu[area],
            )
            projected[pb] = self._clip(
                state[pb],
                -self.params.bess[area].rating_pu,
                self.params.bess[area].rating_pu,
            )
            projected[soc] = self._clip(
                state[soc],
                self.params.bess[area].soc_min,
                self.params.bess[area].soc_max,
            )
            projected[availability] = self._clip(state[availability], 0.0, 1.0)
        return ca.vertcat(*projected)

    def _raw_headroom_symbolic(self, area: int, soc: Any) -> tuple[Any, Any]:
        ca = self._ca
        physical = self.params.bess[area]
        state = self._clip(soc, physical.soc_min, physical.soc_max)
        apparent = math.sqrt(
            max(
                (physical.voltage_pu * physical.current_limit_pu_on_system_base) ** 2
                - physical.reactive_power_pu**2,
                0.0,
            )
        )
        upward_energy = (
            3600.0
            * physical.energy_mwh
            * physical.eta_discharge
            * (state - physical.soc_min)
            / (physical.system_base_mw * physical.sustainable_horizon_s)
        )
        downward_energy = (
            3600.0
            * physical.energy_mwh
            * (physical.soc_max - state)
            / (
                physical.system_base_mw
                * physical.sustainable_horizon_s
                * physical.eta_charge
            )
        )
        upward = ca.fmax(
            ca.fmin(
                ca.fmin(
                    physical.rating_pu - physical.base_power_pu,
                    apparent - physical.base_power_pu,
                ),
                upward_energy,
            ),
            0.0,
        )
        downward = ca.fmax(
            ca.fmin(
                ca.fmin(
                    physical.rating_pu + physical.base_power_pu,
                    apparent + physical.base_power_pu,
                ),
                downward_energy,
            ),
            0.0,
        )
        return upward, downward

    def _derivative_symbolic(
        self,
        state: Any,
        sg_command: Any,
        delayed_ibr: Any,
        load: Any,
        regime_ids: Sequence[str],
    ) -> Any:
        ca = self._ca
        derivative: list[Any] = [0.0] * 15
        tie = state[PlantBStateIndex.PTIE12]
        frequencies = (state[PlantBStateIndex.F1], state[PlantBStateIndex.F2])
        for area, indices in enumerate(
            (
                (0, 1, 2, 7, 8, 9, 10),
                (3, 4, 5, 11, 12, 13, 14),
            )
        ):
            frequency_index, pm_index, pv_index, z_index, pb_index, soc_index, a_index = indices
            frequency = state[frequency_index]
            pm = state[pm_index]
            pv = state[pv_index]
            z_command = state[z_index]
            pb = state[pb_index]
            availability = self._clip(state[a_index], 0.0, 1.0)
            area_params = self.params.areas[area]
            physical = self.params.bess[area]
            regime = self.params.regimes[regime_ids[area]]
            tie_export = tie if area == 0 else -tie
            derivative[frequency_index] = (
                -area_params.load_damping_pu_per_hz * frequency
                + pm
                + pb
                - load[area]
                - tie_export
            ) / area_params.inertia_pu_s_per_hz
            raw_pm_rate = (-pm + pv) / area_params.turbine_time_constant_s
            derivative[pm_index] = self._clip(
                raw_pm_rate,
                -self.params.sg_capability.grc_down_pu_per_s[area],
                self.params.sg_capability.grc_up_pu_per_s[area],
            )
            derivative[pv_index] = (
                -pv - frequency / area_params.droop_hz_per_pu + sg_command[area]
            ) / area_params.governor_time_constant_s
            if regime.central_service_enabled:
                expected_delivery = 1.0 - regime.dropout_probability
                central_target = (
                    regime.command_efficiency * expected_delivery * delayed_ibr[area]
                )
            else:
                central_target = 0.0
            derivative[z_index] = (-z_command + central_target) / (
                physical.nominal_command_time_constant_s
                * regime.command_time_constant_multiplier
            )
            raw_up, raw_down = self._raw_headroom_symbolic(area, state[soc_index])
            if regime.central_service_enabled:
                head_up = availability * regime.headroom_up_multiplier * raw_up
                head_down = availability * regime.headroom_down_multiplier * raw_down
            else:
                head_up = 0.0
                head_down = 0.0
            central_power = self._clip(z_command, -head_down, head_up)
            local_power = -physical.local_droop_pu_per_hz * frequency
            p_reference = self._clip(
                physical.base_power_pu + local_power + central_power,
                -physical.rating_pu,
                physical.rating_pu,
            )
            raw_pb_rate = (p_reference - pb) / (
                physical.nominal_power_time_constant_s
                * regime.power_time_constant_multiplier
            )
            derivative[pb_index] = self._clip(
                raw_pb_rate,
                -physical.nominal_ramp_down_pu_per_s * regime.ramp_down_multiplier,
                physical.nominal_ramp_up_pu_per_s * regime.ramp_up_multiplier,
            )
            relative_power = pb - physical.base_power_pu
            energy_term = ca.if_else(
                relative_power >= 0.0,
                relative_power / physical.eta_discharge,
                physical.eta_charge * relative_power,
            )
            derivative[soc_index] = -(
                physical.system_base_mw / (3600.0 * physical.energy_mwh)
            ) * energy_term
            derivative[a_index] = (regime.availability_target - availability) / (
                regime.availability_time_constant_s
            )
        derivative[PlantBStateIndex.PTIE12] = (
            2.0
            * math.pi
            * self.params.tie_synchronizing_coefficient_pu_per_rad
            * (frequencies[0] - frequencies[1])
        )
        return ca.vertcat(*derivative)

    def _rk4_symbolic(
        self,
        state: Any,
        sg_command: Any,
        delayed_ibr: Any,
        load: Any,
        regime_ids: Sequence[str],
    ) -> Any:
        dt = self.config.integration_step_s
        k1 = self._derivative_symbolic(state, sg_command, delayed_ibr, load, regime_ids)
        k2 = self._derivative_symbolic(
            self._project_symbolic(state + 0.5 * dt * k1),
            sg_command,
            delayed_ibr,
            load,
            regime_ids,
        )
        k3 = self._derivative_symbolic(
            self._project_symbolic(state + 0.5 * dt * k2),
            sg_command,
            delayed_ibr,
            load,
            regime_ids,
        )
        k4 = self._derivative_symbolic(
            self._project_symbolic(state + dt * k3),
            sg_command,
            delayed_ibr,
            load,
            regime_ids,
        )
        return self._project_symbolic(state + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4))

    def _stage_cost(self, state: Any, action: Any) -> Any:
        tie = state[PlantBStateIndex.PTIE12]
        frequency_1 = state[PlantBStateIndex.F1]
        frequency_2 = state[PlantBStateIndex.F2]
        ace_1 = self.params.areas[0].ace_bias_pu_per_hz * frequency_1 + tie
        ace_2 = self.params.areas[1].ace_bias_pu_per_hz * frequency_2 - tie
        return (
            self.config.q_frequency * (frequency_1**2 + frequency_2**2)
            + self.config.q_ace * (ace_1**2 + ace_2**2)
            + self.config.q_tie_line * tie**2
            + self.config.r_sg * (action[0] ** 2 + action[1] ** 2)
            + self.config.r_ibr * (action[2] ** 2 + action[3] ** 2)
        )

    def _delayed_action(
        self,
        area: int,
        *,
        block: int,
        substep: int,
        actions: Any,
        past_ibr: Any,
        regime_id: str,
    ) -> Any:
        delay = self.params.regimes[regime_id].command_delay_s
        source_time = (
            block * self.config.command_interval_s
            + substep * self.config.integration_step_s
            - delay
        )
        source_block = math.floor(
            (source_time + 1.0e-12) / self.config.command_interval_s
        )
        if source_block >= 0:
            return actions[2 + area, min(source_block, block)]
        past_column = max(0, min(1, source_block + 2))
        return past_ibr[area, past_column]

    def _state_bounds(self) -> tuple[FloatArray, FloatArray]:
        """Return explicit safety bounds.

        Physical reserve, power, SoC and availability bounds are enforced by
        the exact projected plant transition. Repeating those same bounds as
        NLP variable bounds creates a degenerate active set whenever the
        physical projection is active, so only independent grid-safety bounds
        are repeated here.
        """

        lower = np.full(15, -np.inf, dtype=np.float64)
        upper = np.full(15, np.inf, dtype=np.float64)
        lower[[0, 3]] = -self.config.frequency_bound_hz
        upper[[0, 3]] = self.config.frequency_bound_hz
        lower[6] = -self.config.tie_line_bound_pu
        upper[6] = self.config.tie_line_bound_pu
        return lower, upper

    def _build_problem(self) -> None:
        ca = self._ca
        number = self.config.number_of_control_blocks
        steps_per_block = self.config.integration_steps_per_block
        total_steps = number * steps_per_block
        states = ca.MX.sym("X", 15, total_steps + 1)
        actions = ca.MX.sym("U", 4, number)
        initial_state = ca.MX.sym("x0", 15)
        loads = ca.MX.sym("loads", 2, number)
        previous_action = ca.MX.sym("previous_action", 4)
        past_ibr = ca.MX.sym("past_ibr", 2, 2)
        parameters = ca.vertcat(
            initial_state,
            ca.reshape(loads, -1, 1),
            previous_action,
            ca.reshape(past_ibr, -1, 1),
        )
        objective: Any = 0.0
        constraints: list[Any] = [states[:, 0] - initial_state]
        constraint_lower: list[float] = [0.0] * 15
        constraint_upper: list[float] = [0.0] * 15
        for step in range(total_steps):
            block = step // steps_per_block
            substep = step % steps_per_block
            delayed = ca.vertcat(
                *(
                    self._delayed_action(
                        area,
                        block=block,
                        substep=substep,
                        actions=actions,
                        past_ibr=past_ibr,
                        regime_id=self.regime_schedule[block][area],
                    )
                    for area in (0, 1)
                )
            )
            objective += self.config.integration_step_s * self._stage_cost(
                states[:, step], actions[:, block]
            )
            predicted = self._rk4_symbolic(
                states[:, step],
                actions[:2, block],
                delayed,
                loads[:, block],
                self.regime_schedule[block],
            )
            constraints.append(states[:, step + 1] - predicted)
            constraint_lower.extend([0.0] * 15)
            constraint_upper.extend([0.0] * 15)
        for block in range(number):
            prior = previous_action if block == 0 else actions[:, block - 1]
            delta = actions[:, block] - prior
            constraints.append(delta)
            for area in (0, 1):
                command_span = (
                    self.params.sg_capability.reserve_up_pu[area]
                    + self.params.sg_capability.reserve_down_pu[area]
                )
                constraint_lower.append(-command_span)
                constraint_upper.append(command_span)
            constraint_lower.extend([-self.config.ibr_command_delta_bound_pu] * 2)
            constraint_upper.extend([self.config.ibr_command_delta_bound_pu] * 2)
            objective += self.config.s_sg * (delta[0] ** 2 + delta[1] ** 2)
            objective += self.config.s_ibr * (delta[2] ** 2 + delta[3] ** 2)
        objective += self.config.terminal_multiplier * self._stage_cost(
            states[:, total_steps], actions[:, number - 1]
        )
        decision = ca.vertcat(
            ca.reshape(states, -1, 1), ca.reshape(actions, -1, 1)
        )
        constraint_vector = ca.vertcat(*constraints)
        problem = {"x": decision, "p": parameters, "f": objective, "g": constraint_vector}
        options = {
            "print_time": False,
            "ipopt.print_level": 0,
            "ipopt.sb": "yes",
            "ipopt.max_iter": self.config.ipopt_max_iterations,
            "ipopt.tol": self.config.ipopt_tolerance,
            "ipopt.acceptable_tol": self.config.ipopt_acceptable_tolerance,
            "ipopt.acceptable_constr_viol_tol": self.config.solver_constraint_qualification_tolerance,
            "ipopt.constr_viol_tol": min(
                self.config.solver_constraint_qualification_tolerance, 1.0e-6
            ),
            "ipopt.warm_start_init_point": "yes",
            "ipopt.hessian_approximation": "limited-memory",
            "ipopt.mu_strategy": "adaptive",
            "ipopt.acceptable_iter": 3,
        }
        self._solver = ca.nlpsol(
            f"phase_b2_{self.oracle_level.lower()}_{id(self)}",
            "ipopt",
            problem,
            options,
        )
        lower_state, upper_state = self._state_bounds()
        self._lbx = np.concatenate(
            (
                np.tile(lower_state, total_steps + 1),
                np.tile(
                    np.asarray(
                        (
                            -self.params.sg_capability.reserve_down_pu[0],
                            -self.params.sg_capability.reserve_down_pu[1],
                            -self.params.bess[0].rating_pu,
                            -self.params.bess[1].rating_pu,
                        )
                    ),
                    number,
                ),
            )
        )
        self._ubx = np.concatenate(
            (
                np.tile(upper_state, total_steps + 1),
                np.tile(
                    np.asarray(
                        (
                            self.params.sg_capability.reserve_up_pu[0],
                            self.params.sg_capability.reserve_up_pu[1],
                            self.params.bess[0].rating_pu,
                            self.params.bess[1].rating_pu,
                        )
                    ),
                    number,
                ),
            )
        )
        self._lbg = np.asarray(constraint_lower, dtype=np.float64)
        self._ubg = np.asarray(constraint_upper, dtype=np.float64)
        self._number_decisions = int(decision.numel())
        self._number_state_values = 15 * (total_steps + 1)
        self._number_state_nodes = total_steps + 1
        lambda_g_symbol = ca.MX.sym("lambda_g", constraint_vector.numel())
        lambda_x_symbol = ca.MX.sym("lambda_x", decision.numel())
        lagrangian_gradient = (
            ca.gradient(objective, decision)
            + ca.jacobian(constraint_vector, decision).T
            @ lambda_g_symbol
            + lambda_x_symbol
        )
        self._stationarity = ca.Function(
            f"phase_b2_kkt_{id(self)}",
            [decision, parameters, lambda_g_symbol, lambda_x_symbol],
            [lagrangian_gradient],
        )
        self._constraint_evaluator = ca.Function(
            f"phase_b2_constraints_{id(self)}",
            [decision, parameters],
            [constraint_vector],
        )

    def _parameter_vector(
        self,
        state: FloatArray,
        load_forecast: FloatArray,
        previous_action: FloatArray,
        past_ibr: FloatArray,
    ) -> FloatArray:
        return np.concatenate(
            (
                state,
                load_forecast.reshape(-1, order="F"),
                previous_action,
                past_ibr.reshape(-1, order="F"),
            )
        )

    def _initial_guess(
        self,
        name: str,
        state: FloatArray,
        load_forecast: FloatArray,
        previous_action: FloatArray,
        past_ibr: FloatArray,
    ) -> FloatArray:
        number = self.config.number_of_control_blocks
        if name == "warm" and "decision" in self._warm:
            return self._warm["decision"].copy()
        if name == "hold":
            action_guess = np.tile(previous_action[:, None], (1, number))
        elif name == "split_load":
            action_guess = np.zeros((4, number), dtype=np.float64)
            for block in range(number):
                for area in (0, 1):
                    demand = load_forecast[area, block]
                    action_guess[area, block] = np.clip(
                        0.5 * demand,
                        -self.params.sg_capability.reserve_down_pu[area],
                        self.params.sg_capability.reserve_up_pu[area],
                    )
                    action_guess[2 + area, block] = np.clip(
                        0.5 * demand,
                        -self.params.bess[area].rating_pu,
                        self.params.bess[area].rating_pu,
                    )
        elif name == "ibr_first":
            action_guess = np.zeros((4, number), dtype=np.float64)
            for block in range(number):
                for area in (0, 1):
                    demand = load_forecast[area, block]
                    action_guess[2 + area, block] = np.clip(
                        demand,
                        -self.params.bess[area].rating_pu,
                        self.params.bess[area].rating_pu,
                    )
        else:
            action_guess = np.zeros((4, number), dtype=np.float64)
        state_guess = self._rollout_initial_guess(
            state, action_guess, load_forecast, past_ibr
        )
        guess = np.concatenate(
            (state_guess.reshape(-1, order="F"), action_guess.reshape(-1, order="F"))
        )
        return _numeric_clip(guess, self._lbx, self._ubx)

    def _rollout_initial_guess(
        self,
        state: FloatArray,
        actions: FloatArray,
        load_forecast: FloatArray,
        past_ibr: FloatArray,
    ) -> FloatArray:
        """Create a dynamically feasible multiple-shooting initialization."""

        model = TwoAreaPlantB(self.params)
        trajectory = np.empty((15, self._number_state_nodes), dtype=np.float64)
        trajectory[:, 0] = state
        current = state.copy()
        steps_per_block = self.config.integration_steps_per_block
        for step in range(self._number_state_nodes - 1):
            block = step // steps_per_block
            substep = step % steps_per_block
            regime_ids = self.regime_schedule[block]
            delivered: list[float] = []
            for area in (0, 1):
                regime = self.params.regimes[regime_ids[area]]
                delay = regime.command_delay_s
                source_time = (
                    block * self.config.command_interval_s
                    + substep * self.config.integration_step_s
                    - delay
                )
                source_block = math.floor(
                    (source_time + 1.0e-12) / self.config.command_interval_s
                )
                if source_block >= 0:
                    value = actions[2 + area, min(source_block, block)]
                else:
                    value = past_ibr[area, max(0, min(1, source_block + 2))]
                delivered.append((1.0 - regime.dropout_probability) * float(value))
            current = model.step(
                current,
                command=UpperCommand(
                    sg_pu=(float(actions[0, block]), float(actions[1, block])),
                    ibr_pu=(float(actions[2, block]), float(actions[3, block])),
                ),
                delayed_ibr_command_pu=delivered,
                load_disturbance_pu=load_forecast[:, block],
                regimes=tuple(self.params.regimes[value] for value in regime_ids),
                step_s=self.config.integration_step_s,
            )
            trajectory[:, step + 1] = current
        return trajectory

    def independent_rollout(
        self,
        state: ArrayLike,
        *,
        action_sequence: ArrayLike,
        load_forecast_pu: ArrayLike,
        past_ibr_commands_pu: ArrayLike | None = None,
    ) -> FloatArray:
        """Roll out the standalone Python simulator for an action sequence."""

        values = TwoAreaPlantB(self.params).validate_state(state)
        number = self.config.number_of_control_blocks
        actions = np.asarray(action_sequence, dtype=np.float64)
        loads = np.asarray(load_forecast_pu, dtype=np.float64)
        if loads.shape == (2,):
            loads = np.tile(loads[:, None], (1, number))
        if actions.shape != (4, number):
            raise ValueError(f"action sequence must have shape (4, {number})")
        if loads.shape != (2, number):
            raise ValueError(f"load forecast must have shape (2, {number})")
        past = (
            np.zeros((2, 2), dtype=np.float64)
            if past_ibr_commands_pu is None
            else np.asarray(past_ibr_commands_pu, dtype=np.float64)
        )
        if past.shape != (2, 2):
            raise ValueError("past IBR commands must have shape (2, 2)")
        return self._rollout_initial_guess(values, actions, loads, past)

    def evaluate_action_sequence(
        self,
        state: ArrayLike,
        *,
        action_sequence: ArrayLike,
        load_forecast_pu: ArrayLike,
        previous_command: UpperCommand | None = None,
        past_ibr_commands_pu: ArrayLike | None = None,
    ) -> float:
        """Evaluate the registered objective using an independent plant rollout."""

        number = self.config.number_of_control_blocks
        actions = np.asarray(action_sequence, dtype=np.float64)
        if actions.shape != (4, number):
            raise ValueError(f"action sequence must have shape (4, {number})")
        trajectory = self.independent_rollout(
            state,
            action_sequence=actions,
            load_forecast_pu=load_forecast_pu,
            past_ibr_commands_pu=past_ibr_commands_pu,
        )
        objective = 0.0
        steps_per_block = self.config.integration_steps_per_block
        for step in range(self._number_state_nodes - 1):
            block = step // steps_per_block
            node = trajectory[:, step]
            tie = node[PlantBStateIndex.PTIE12]
            frequency_1 = node[PlantBStateIndex.F1]
            frequency_2 = node[PlantBStateIndex.F2]
            ace_1 = self.params.areas[0].ace_bias_pu_per_hz * frequency_1 + tie
            ace_2 = self.params.areas[1].ace_bias_pu_per_hz * frequency_2 - tie
            objective += self.config.integration_step_s * (
                self.config.q_frequency * (frequency_1**2 + frequency_2**2)
                + self.config.q_ace * (ace_1**2 + ace_2**2)
                + self.config.q_tie_line * tie**2
                + self.config.r_sg * np.sum(actions[:2, block] ** 2)
                + self.config.r_ibr * np.sum(actions[2:, block] ** 2)
            )
        terminal = trajectory[:, -1]
        tie = terminal[PlantBStateIndex.PTIE12]
        frequency_1 = terminal[PlantBStateIndex.F1]
        frequency_2 = terminal[PlantBStateIndex.F2]
        ace_1 = self.params.areas[0].ace_bias_pu_per_hz * frequency_1 + tie
        ace_2 = self.params.areas[1].ace_bias_pu_per_hz * frequency_2 - tie
        objective += self.config.terminal_multiplier * (
            self.config.q_frequency * (frequency_1**2 + frequency_2**2)
            + self.config.q_ace * (ace_1**2 + ace_2**2)
            + self.config.q_tie_line * tie**2
            + self.config.r_sg * np.sum(actions[:2, -1] ** 2)
            + self.config.r_ibr * np.sum(actions[2:, -1] ** 2)
        )
        previous = UpperCommand() if previous_command is None else previous_command
        prior = np.asarray((*previous.sg_pu, *previous.ibr_pu), dtype=np.float64)
        for block in range(number):
            delta = actions[:, block] - prior
            objective += self.config.s_sg * np.sum(delta[:2] ** 2)
            objective += self.config.s_ibr * np.sum(delta[2:] ** 2)
            prior = actions[:, block]
        return float(objective)

    def solve(
        self,
        state: ArrayLike,
        *,
        load_forecast_pu: ArrayLike,
        previous_command: UpperCommand | None = None,
        past_ibr_commands_pu: ArrayLike | None = None,
        initializations: Sequence[str] = ("warm",),
    ) -> OracleSolveRecord:
        values = TwoAreaPlantB(self.params).validate_state(state)
        number = self.config.number_of_control_blocks
        load_forecast = np.asarray(load_forecast_pu, dtype=np.float64)
        if load_forecast.shape == (2,):
            load_forecast = np.tile(load_forecast[:, None], (1, number))
        if load_forecast.shape != (2, number) or not np.isfinite(load_forecast).all():
            raise ValueError(f"load forecast must have shape (2, {number})")
        if self.oracle_level == "O2" and not np.allclose(
            load_forecast, load_forecast[:, [0]], rtol=0.0, atol=0.0
        ):
            raise ValueError(
                "O2 may not use future load; only a held-current-load forecast is allowed"
            )
        previous = UpperCommand() if previous_command is None else previous_command
        previous_action = np.asarray((*previous.sg_pu, *previous.ibr_pu), dtype=np.float64)
        if past_ibr_commands_pu is None:
            past_ibr = np.zeros((2, 2), dtype=np.float64)
        else:
            past_ibr = np.asarray(past_ibr_commands_pu, dtype=np.float64)
        if past_ibr.shape != (2, 2) or not np.isfinite(past_ibr).all():
            raise ValueError("past IBR commands must have shape (2, 2), oldest to newest")
        initialization_names = tuple(dict.fromkeys(str(name) for name in initializations))
        if not initialization_names:
            raise ValueError("at least one initialization is required")
        parameter_vector = self._parameter_vector(
            values, load_forecast, previous_action, past_ibr
        )
        candidates: list[dict[str, Any]] = []
        total_started = time.perf_counter()
        for name in initialization_names:
            kwargs: dict[str, Any] = {
                "x0": self._initial_guess(
                    name, values, load_forecast, previous_action, past_ibr
                ),
                "p": parameter_vector,
                "lbx": self._lbx,
                "ubx": self._ubx,
                "lbg": self._lbg,
                "ubg": self._ubg,
            }
            if name == "warm" and "lam_x" in self._warm:
                kwargs["lam_x0"] = self._warm["lam_x"]
                kwargs["lam_g0"] = self._warm["lam_g"]
            try:
                solution = self._solver(**kwargs)
                stats = self._solver.stats()
                decision = np.asarray(solution["x"], dtype=np.float64).reshape(-1)
                constraint = np.asarray(solution["g"], dtype=np.float64).reshape(-1)
                lambda_g = np.asarray(solution["lam_g"], dtype=np.float64).reshape(-1)
                lambda_x = np.asarray(solution["lam_x"], dtype=np.float64).reshape(-1)
                stationarity = np.asarray(
                    self._stationarity(
                        decision, parameter_vector, lambda_g, lambda_x
                    ),
                    dtype=np.float64,
                ).reshape(-1)
                iteration_trace = stats.get("iterations", {})
                dual_trace = iteration_trace.get("inf_du", [math.inf])
                primal_trace = iteration_trace.get("inf_pr", [math.inf])
                barrier_trace = iteration_trace.get("mu", [math.inf])
                ipopt_kkt = max(
                    float(dual_trace[-1]),
                    float(primal_trace[-1]),
                    float(barrier_trace[-1]),
                )
                variable_violation = max(
                    float(np.max(np.maximum(self._lbx - decision, 0.0))),
                    float(np.max(np.maximum(decision - self._ubx, 0.0))),
                )
                constraint_violation = max(
                    float(np.max(np.maximum(self._lbg - constraint, 0.0))),
                    float(np.max(np.maximum(constraint - self._ubg, 0.0))),
                )
                candidates.append(
                    {
                        "name": name,
                        "solution": solution,
                        "decision": decision,
                        "objective": float(solution["f"]),
                        "status": str(stats.get("return_status", "unknown")),
                        "success": bool(stats.get("success", False)),
                        "iterations": int(stats.get("iter_count", -1)),
                        "kkt": ipopt_kkt,
                        "raw_stationarity": float(np.max(np.abs(stationarity))),
                        "constraint": max(variable_violation, constraint_violation),
                    }
                )
            except Exception as exc:
                candidates.append(
                    {
                        "name": name,
                        "solution": None,
                        "decision": np.full(self._number_decisions, np.nan),
                        "objective": math.inf,
                        "status": f"exception:{type(exc).__name__}",
                        "success": False,
                        "iterations": -1,
                        "kkt": math.inf,
                        "raw_stationarity": math.inf,
                        "constraint": math.inf,
                    }
                )
        successful = [
            row
            for row in candidates
            if row["success"]
            and np.isfinite(row["objective"])
            and row["constraint"]
            <= self.config.solver_constraint_qualification_tolerance
            and row["kkt"] <= self.config.solver_kkt_qualification_tolerance
        ]
        selected = min(successful or candidates, key=lambda row: row["objective"])
        wall_time = time.perf_counter() - total_started
        if selected["solution"] is not None and np.isfinite(selected["decision"]).all():
            solution = selected["solution"]
            self._warm = {
                "decision": selected["decision"].copy(),
                "lam_x": np.asarray(solution["lam_x"], dtype=np.float64).reshape(-1),
                "lam_g": np.asarray(solution["lam_g"], dtype=np.float64).reshape(-1),
            }
            state_nodes = selected["decision"][: self._number_state_values].reshape(
                15, self._number_state_nodes, order="F"
            )
            action_sequence = selected["decision"][self._number_state_values :].reshape(
                4, number, order="F"
            )
            first = action_sequence[:, 0]
            command = UpperCommand(
                sg_pu=(float(first[0]), float(first[1])),
                ibr_pu=(float(first[2]), float(first[3])),
            )
        else:
            state_nodes = np.full((15, self._number_state_nodes), np.nan)
            action_sequence = np.full((4, number), np.nan)
            command = UpperCommand()
        return OracleSolveRecord(
            oracle_level=self.oracle_level,
            solver_status=str(selected["status"]),
            success=bool(
                selected["success"]
                and selected["constraint"]
                <= self.config.solver_constraint_qualification_tolerance
                and selected["kkt"] <= self.config.solver_kkt_qualification_tolerance
            ),
            local_optimum_only=True,
            global_optimality_claim=False,
            objective=float(selected["objective"]),
            iterations=int(selected["iterations"]),
            kkt_residual_inf=float(selected["kkt"]),
            raw_stationarity_inf=float(selected["raw_stationarity"]),
            max_constraint_residual=float(selected["constraint"]),
            wall_time_s=wall_time,
            horizon_s=self.config.horizon_s,
            control_blocks=number,
            independent_actions=4 * number,
            initializations_attempted=len(initialization_names),
            selected_initialization=str(selected["name"]),
            command=command,
            action_sequence=action_sequence,
            state_nodes=state_nodes,
        )


__all__ = [
    "ExactMultipleShootingNMPC",
    "ExactNMPCConfig",
    "OracleSolveRecord",
]
