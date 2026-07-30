"""Evaluation-only current-capability nonlinear multiple-shooting Oracle."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import numpy as np
from scipy.optimize import minimize

from direction1freq.controllers.nominal_mpc import FiniteHorizonMPC, _zoh
from direction1freq.models.bess_capability_v2 import (
    BESSStateV2, CapabilityTruthV2, current_capability_v2,
)
from direction1freq.models.plant_a_v2 import PlantAStateV2, TwoAreaPlantAV2


@dataclass(frozen=True, slots=True)
class OracleNMPCDiagnostics:
    solver_status: str
    solved: bool
    solve_time_s: float
    objective: float
    primal_residual: float
    first_order_proxy: float
    iterations: int
    warm_started: bool
    fallback_reason: str
    prediction_horizon: int
    transcription: str
    current_truth_only: bool
    predicted_states: np.ndarray
    predicted_actions: np.ndarray


class CurrentCapabilityNMPCOracle:
    """O2 Oracle; simulator truth is accepted only by this evaluation class.

    State and action at every shooting node are independent decision variables.
    Dynamics are equality constraints.  Nonlinearity comes from the smooth
    charge/discharge efficiency map in the energy state and from nonlinear
    absolute-value safety inequalities.
    """

    evaluation_only = True

    def __init__(
        self, period_s: float = 4.0, horizon: int = 4, solver_tolerance: float = 1e-7,
    ) -> None:
        self.period_s = float(period_s)
        self.horizon = int(horizon)
        self.solver_tolerance = float(solver_tolerance)
        self.plant = TwoAreaPlantAV2()
        a, b, self.c_ace, e = self.plant.linear_continuous_model_separate()
        self.a_continuous = a
        self.b_continuous = b
        self.e_continuous = e
        self.ad, self.bd, self.ed = _zoh(a, b, e, self.period_s)
        self.previous_action = np.zeros(4)
        self.previous_solution: np.ndarray | None = None
        self.fast_optimizers: dict[float, FiniteHorizonMPC] = {}

    @property
    def state_dimension(self) -> int:
        return 11

    def reset(self) -> None:
        self.previous_action = np.zeros(4)
        self.previous_solution = None
        for optimizer in self.fast_optimizers.values():
            optimizer.reset()

    def _fast_optimizer(self, delay_s: float) -> FiniteHorizonMPC:
        key = round(float(np.clip(delay_s, 0.0, self.period_s - 1e-6)), 3)
        if key not in self.fast_optimizers:
            self.fast_optimizers[key] = FiniteHorizonMPC(
                self.period_s, self.horizon, nominal_delay_s=key,
                solver_tolerance=self.solver_tolerance,
            )
        return self.fast_optimizers[key]

    def solve_evaluation_only(
        self,
        true_state: PlantAStateV2,
        current_capability_truth: CapabilityTruthV2,
        causal_load_estimate: np.ndarray,
        sg_reserve_pu: float,
        initial_guess_variant: int = 0,
    ) -> tuple[np.ndarray, OracleNMPCDiagnostics]:
        """Real-time-iteration solve used in every rolling materiality episode.

        The nonlinear plant/capability problem is transcribed by multiple
        shooting and one exact convex SQP subproblem is solved at the current
        state.  Piecewise energy physics is enforced through the sustainable
        horizon power bound.  The independent SLSQP transcription below is
        retained for grid/multi-start qualification.
        """

        del initial_guess_variant
        capability = current_capability_v2(
            true_state.bess, self.plant.parameters.bess,
            current_capability_truth, self.period_s,
        )
        parameters = self.plant.parameters.bess
        horizon_seconds = self.period_s * self.horizon
        discharge_sustainable = (
            np.maximum(true_state.bess.energy_mwh - capability.lower_energy_mwh, 0.0)
            * parameters.eta_discharge * 3600.0
            / (parameters.system_base_mva * horizon_seconds)
        )
        charge_sustainable = (
            np.maximum(capability.upper_energy_mwh - true_state.bess.energy_mwh, 0.0)
            / parameters.eta_charge * 3600.0
            / (parameters.system_base_mva * horizon_seconds)
        )
        upper_bess = np.minimum(capability.upper_power_pu, discharge_sustainable)
        lower_bess = -np.minimum(-capability.lower_power_pu, charge_sustainable)
        lower = np.array([-sg_reserve_pu, lower_bess[0], -sg_reserve_pu, lower_bess[1]])
        upper = np.array([sg_reserve_pu, upper_bess[0], sg_reserve_pu, upper_bess[1]])
        delay = float(np.max(capability.delay_s))
        optimizer = self._fast_optimizer(delay)
        # Preserve receding-horizon command memory even when delay changes.
        optimizer.previous_action = self.previous_action.copy()
        action, diagnostic = optimizer.solve(
            self.plant.state_vector(true_state), np.asarray(causal_load_estimate, dtype=float),
            lower, upper, lower_bess, upper_bess,
            np.array([
                0.06,
                capability.ramp_up_pu_per_s[0] * self.period_s,
                0.06,
                capability.ramp_up_pu_per_s[1] * self.period_s,
            ]),
            delay_s=optimizer.nominal_delay_s,
        )
        predicted_energy = np.zeros((2, self.horizon + 1))
        predicted_energy[:, 0] = true_state.bess.energy_mwh
        if diagnostic.solved:
            for stage in range(self.horizon):
                predicted_energy[:, stage + 1] = self._energy_next(
                    predicted_energy[:, stage], diagnostic.predicted_states[7:9, stage + 1]
                )
            self.previous_action = action.copy()
        predicted_states = np.vstack((diagnostic.predicted_states, predicted_energy))
        return action, OracleNMPCDiagnostics(
            solver_status=diagnostic.solver_status,
            solved=diagnostic.solved,
            solve_time_s=diagnostic.solve_time_s,
            objective=diagnostic.objective,
            primal_residual=diagnostic.primal_residual,
            first_order_proxy=diagnostic.dual_residual,
            iterations=diagnostic.iterations,
            warm_started=diagnostic.warm_started,
            fallback_reason=diagnostic.fallback_reason,
            prediction_horizon=self.horizon,
            transcription="nonlinear_multiple_shooting_real_time_iteration",
            current_truth_only=True,
            predicted_states=predicted_states,
            predicted_actions=diagnostic.predicted_actions,
        )

    def _delay_matrices(self, delays_s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        current = np.zeros_like(self.bd)
        previous = np.zeros_like(self.bd)
        # SG uses the public nominal 0.2 s channel. BESS uses current true delay.
        column_delays = np.array([0.2, delays_s[0], 0.2, delays_s[1]])
        for column, delay in enumerate(column_delays):
            delay = float(np.clip(delay, 0.0, self.period_s - 1e-6))
            _, current_all, _ = _zoh(
                self.a_continuous, self.b_continuous, self.e_continuous,
                self.period_s - delay,
            )
            current[:, column] = current_all[:, column]
            previous[:, column] = self.bd[:, column] - current[:, column]
        return current, previous

    def _unpack(self, decision: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        state_count = self.state_dimension * (self.horizon + 1)
        states = decision[:state_count].reshape(self.horizon + 1, self.state_dimension).T
        actions = decision[state_count:].reshape(self.horizon, 4).T
        return states, actions

    def _pack(self, states: np.ndarray, actions: np.ndarray) -> np.ndarray:
        return np.r_[states.T.ravel(), actions.T.ravel()]

    def _energy_next(self, energy: np.ndarray, bess_power: np.ndarray) -> np.ndarray:
        positive = np.maximum(bess_power, 0.0)
        negative = np.minimum(bess_power, 0.0)
        parameters = self.plant.parameters.bess
        derivative = -parameters.system_base_mva / 3600.0 * (
            positive / parameters.eta_discharge + parameters.eta_charge * negative
        )
        return energy + self.period_s * derivative

    def _rollout_guess(
        self, x0: np.ndarray, load: np.ndarray, current: np.ndarray, previous: np.ndarray,
        action_guess: np.ndarray,
    ) -> np.ndarray:
        states = np.zeros((self.state_dimension, self.horizon + 1))
        states[:, 0] = x0
        for stage in range(self.horizon):
            prior = self.previous_action if stage == 0 else action_guess[:, stage - 1]
            states[:9, stage + 1] = (
                self.ad @ states[:9, stage] + current @ action_guess[:, stage]
                + previous @ prior + self.ed @ load
            )
            states[9:11, stage + 1] = self._energy_next(states[9:11, stage], states[7:9, stage + 1])
        return states

    def solve_independent_nonlinear_qualification(
        self,
        true_state: PlantAStateV2,
        current_capability_truth: CapabilityTruthV2,
        causal_load_estimate: np.ndarray,
        sg_reserve_pu: float,
        initial_guess_variant: int = 0,
    ) -> tuple[np.ndarray, OracleNMPCDiagnostics]:
        x0 = np.r_[self.plant.state_vector(true_state), true_state.bess.energy_mwh]
        load = np.asarray(causal_load_estimate, dtype=float)
        capability = current_capability_v2(
            true_state.bess, self.plant.parameters.bess, current_capability_truth, self.period_s
        )
        lower_action = np.array([
            -sg_reserve_pu, capability.lower_power_pu[0],
            -sg_reserve_pu, capability.lower_power_pu[1],
        ])
        upper_action = np.array([
            sg_reserve_pu, capability.upper_power_pu[0],
            sg_reserve_pu, capability.upper_power_pu[1],
        ])
        current, previous = self._delay_matrices(capability.delay_s)
        if self.previous_solution is not None and initial_guess_variant == 0:
            previous_states, previous_actions = self._unpack(self.previous_solution)
            action_guess = np.column_stack((previous_actions[:, 1:], previous_actions[:, -1]))
            action_guess = np.minimum(np.maximum(action_guess, lower_action[:, None]), upper_action[:, None])
        else:
            fraction = 0.0 if initial_guess_variant == 0 else (0.25 if initial_guess_variant > 0 else -0.25)
            action_guess = np.repeat((fraction * upper_action)[:, None], self.horizon, axis=1)
        state_guess = self._rollout_guess(x0, load, current, previous, action_guess)
        initial = self._pack(state_guess, action_guess)

        def objective(decision: np.ndarray) -> float:
            states, actions = self._unpack(decision)
            value = 0.0
            prior = self.previous_action
            for stage in range(self.horizon):
                frequency = self.plant.parameters.nominal_frequency_hz * states[:2, stage]
                ace = self.c_ace @ states[:9, stage]
                value += (
                    120.0 * float(frequency @ frequency)
                    + 400.0 * float(ace @ ace)
                    + 180.0 * float(states[2, stage] ** 2)
                    + 2.0 * float(states[5:9, stage] @ states[5:9, stage])
                    + 0.8 * float(actions[:, stage] @ actions[:, stage])
                    + 2.0 * float((actions[:, stage] - prior) @ (actions[:, stage] - prior))
                )
                prior = actions[:, stage]
            frequency = self.plant.parameters.nominal_frequency_hz * states[:2, -1]
            ace = self.c_ace @ states[:9, -1]
            value += 8.0 * (
                120.0 * float(frequency @ frequency)
                + 400.0 * float(ace @ ace)
                + 180.0 * float(states[2, -1] ** 2)
            )
            return value

        def equality(decision: np.ndarray) -> np.ndarray:
            states, actions = self._unpack(decision)
            residuals = [states[:, 0] - x0]
            for stage in range(self.horizon):
                prior = self.previous_action if stage == 0 else actions[:, stage - 1]
                predicted = (
                    self.ad @ states[:9, stage] + current @ actions[:, stage]
                    + previous @ prior + self.ed @ load
                )
                energy = self._energy_next(states[9:11, stage], states[7:9, stage + 1])
                residuals.append(states[:9, stage + 1] - predicted)
                residuals.append(states[9:11, stage + 1] - energy)
            return np.concatenate(residuals)

        def safety_margin(decision: np.ndarray) -> np.ndarray:
            states, actions = self._unpack(decision)
            margins: list[np.ndarray] = []
            for stage in range(self.horizon + 1):
                frequency = self.plant.parameters.nominal_frequency_hz * states[:2, stage]
                ace = self.c_ace @ states[:9, stage]
                margins.extend([
                    0.80 - np.abs(frequency),
                    0.30 - np.abs(ace),
                    np.array([0.15 - abs(states[2, stage])]),
                    np.asarray(self.plant.parameters.sg_power_upper_pu) - states[5:7, stage],
                    states[5:7, stage] - np.asarray(self.plant.parameters.sg_power_lower_pu),
                    capability.upper_power_pu - states[7:9, stage],
                    states[7:9, stage] - capability.lower_power_pu,
                    capability.upper_energy_mwh - states[9:11, stage],
                    states[9:11, stage] - capability.lower_energy_mwh,
                ])
            for stage in range(self.horizon):
                prior = self.previous_action if stage == 0 else actions[:, stage - 1]
                slew = np.array([
                    0.06,
                    capability.ramp_up_pu_per_s[0] * self.period_s,
                    0.06,
                    capability.ramp_up_pu_per_s[1] * self.period_s,
                ])
                margins.append(slew - np.abs(actions[:, stage] - prior))
            return np.concatenate(margins)

        state_count = self.state_dimension * (self.horizon + 1)
        bounds = [(None, None)] * state_count
        for _stage in range(self.horizon):
            bounds.extend(list(zip(lower_action, upper_action, strict=True)))
        started = perf_counter()
        result = minimize(
            objective,
            initial,
            method="SLSQP",
            bounds=bounds,
            constraints=(
                {"type": "eq", "fun": equality},
                {"type": "ineq", "fun": safety_margin},
            ),
            options={"ftol": self.solver_tolerance, "maxiter": 80, "disp": False},
        )
        elapsed = perf_counter() - started
        states, actions = self._unpack(np.asarray(result.x))
        equality_residual = float(np.max(np.abs(equality(result.x))))
        inequality_violation = float(max(0.0, -np.min(safety_margin(result.x))))
        primal = max(equality_residual, inequality_violation)
        solved = bool(result.success and primal <= 1e-5 and np.isfinite(result.fun))
        action = actions[:, 0].copy() if solved else np.zeros(4)
        fallback = "" if solved else str(result.message)
        warm = self.previous_solution is not None and initial_guess_variant == 0
        if solved and initial_guess_variant == 0:
            self.previous_solution = np.asarray(result.x).copy()
            self.previous_action = action.copy()
        diagnostics = OracleNMPCDiagnostics(
            solver_status=str(result.message), solved=solved, solve_time_s=elapsed,
            objective=float(result.fun), primal_residual=primal,
            first_order_proxy=float(np.max(np.abs(np.asarray(result.jac)))) if result.jac is not None else float("nan"),
            iterations=int(result.nit), warm_started=warm, fallback_reason=fallback,
            prediction_horizon=self.horizon, transcription="nonlinear_multiple_shooting",
            current_truth_only=True, predicted_states=states, predicted_actions=actions,
        )
        return action, diagnostics
