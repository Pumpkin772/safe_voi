"""Causal rolling controller for nonlinear boundary confirmation experiments."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter
from typing import Sequence

import numpy as np

from direction5freq.estimation.grid_load_mhe import ConstrainedGridLoadMHE
from direction5freq.estimation.grid_load_observer import LoadObserverInput
from direction5freq.models.capability_contract import CapabilityRealization
from direction5freq.models.plant_a_full import PlantAParameters, PublicObservation

from selective_boundary_policy import (
    BoundaryDecision, CausalBoundaryFeatures, FrozenBoundaryLookup,
    SelectiveProbeScheduler,
)
from voi_boundary_engine import (
    BoundaryPoint, CapabilityModel, candidate_models, objective_scales, solve_policy,
)


@dataclass(frozen=True, slots=True)
class RollingDiagnostics:
    attempted_optimization_calls: int
    solver_failure_calls: int
    fallback_calls: int
    probe_triggers: int
    probe_active_calls: int
    probe_command_l1_pu_s: float
    maximum_solve_time_s: float
    ordinary_controller_truth_read: bool
    evaluation_only_truth_read: bool


class RollingBoundaryController:
    """Uses actual POI power and a causal load MHE; truth is not an input."""

    def __init__(
        self,
        template: BoundaryPoint,
        parameters: PlantAParameters,
        *,
        lookup: FrozenBoundaryLookup | None = None,
        horizon_s: float = 24.0,
        observation_dt_s: float = 0.02,
    ) -> None:
        self.template = template
        self.parameters = parameters
        self.lookup = lookup
        self.horizon_s = float(horizon_s)
        self.models = candidate_models(template)
        self.last_action = np.zeros(4)
        self.last_decision: BoundaryDecision | None = None
        self.scheduler = None if lookup is None else SelectiveProbeScheduler(lookup)
        self.observer = ConstrainedGridLoadMHE(
            nominal_frequency_hz=parameters.nominal_frequency_hz,
            inertia_s=parameters.inertia_s,
            damping_pu_per_pu_frequency=parameters.damping_pu_per_pu_frequency,
            derivative_filter=0.40,
            warmup_samples=8,
            window_samples=6,
        )
        self.attempts = 0; self.failures = 0; self.fallbacks = 0
        self.probe_triggers = 0; self.probe_active_calls = 0
        self.probe_l1 = 0.0; self.solve_times: list[float] = []
        self._change_epoch = 0; self._last_residual_large = False
        self._last_actual_poi = np.zeros(2)

    def _causal_point(self, observation: PublicObservation, load_estimate: np.ndarray) -> BoundaryPoint:
        # Nominal warm-up is a genuine zero-disturbance operating point.  The
        # 0.015 pu lower bound belongs to the offline event-design domain and
        # must not create a fictitious online load before the event occurs.
        magnitude = float(np.clip(np.max(np.abs(load_estimate)), 0.0, 0.075))
        return replace(
            self.template,
            load_magnitude_pu=magnitude,
            soc=float(np.mean(observation.measured_soc)),
            tie_loading_pu=float(min(abs(observation.tie_line_pu), 0.04)),
        )

    def _detect_change(self, observation: PublicObservation) -> bool:
        requested = self.last_action[[1, 3]]
        residual = float(np.max(np.abs(requested - observation.bess_actual_power_pu)))
        large = residual > max(3.0 * self.template.noise_std_pu, 0.0015)
        triggered = bool(large and not self._last_residual_large)
        self._last_residual_large = large
        if triggered:
            self._change_epoch += 1
        return triggered

    def propose(self, observation: PublicObservation) -> np.ndarray:
        load = self.observer.update(LoadObserverInput(
            observation.time_s,
            observation.frequency_deviation_hz,
            observation.tie_line_pu,
            observation.sg_mechanical_power_pu,
            observation.bess_actual_power_pu,
            observation.slow_reserve_power_pu,
        )).load_pu
        point = self._causal_point(observation, load)
        state = np.r_[
            observation.frequency_deviation_hz / self.parameters.nominal_frequency_hz,
            observation.tie_line_pu,
            observation.valve_pu,
            observation.sg_mechanical_power_pu,
        ]
        solution = solve_policy(
            point, self.models,
            horizon_steps=int(round(self.horizon_s / point.period_s)),
            initial_grid_state=state,
            initial_bess_power=observation.bess_actual_power_pu,
            previous_sg_command=self.last_action[[0, 2]],
            previous_bess_command=self.last_action[[1, 3]],
            initial_energy_mwh=observation.measured_soc * self.parameters.bess.energy_mwh,
            scales=objective_scales(point.objective),
        )
        self.attempts += 1; self.solve_times.append(solution.solve_time_s)
        if not np.isfinite(solution.objective):
            self.failures += 1; self.fallbacks += 1
            return self.last_action
        action = np.array((
            solution.sg_command[0, 0], solution.bess_command[0, 0],
            solution.sg_command[1, 0], solution.bess_command[1, 0],
        ))
        changed = self._detect_change(observation)
        if self.scheduler is not None and changed and not self.lookup.has_positive_region:
            # A globally empty frozen positive region is decided before any
            # candidate-specific solve.  The control path therefore contains
            # exactly the same robust MPC solve as contract MPC.
            self.last_decision = self.scheduler.consider(
                CausalBoundaryFeatures(
                    period_s=point.period_s, sg_tension=point.sg_tension,
                    objective=point.objective, load_magnitude_pu=point.load_magnitude_pu,
                    power_spread_pu=point.power_spread_pu,
                    ramp_spread_pu_per_s=point.ramp_spread_pu_per_s,
                    delay_spread_s=point.delay_spread_s,
                    noise_std_pu=point.noise_std_pu, soc=point.soc,
                    tie_loading_pu=point.tie_loading_pu,
                ),
                causal_change_epoch=self._change_epoch,
                decision_relevant=True,
            )
        elif self.scheduler is not None and changed:
            # Decision relevance is causal: candidate-specific first actions are
            # solved from the same public state; no true model is queried.
            candidate_actions = []
            for model in self.models:
                candidate = solve_policy(
                    point, (model,),
                    horizon_steps=int(round(self.horizon_s / point.period_s)),
                    initial_grid_state=state,
                    initial_bess_power=observation.bess_actual_power_pu,
                    previous_sg_command=self.last_action[[0, 2]],
                    previous_bess_command=self.last_action[[1, 3]],
                    initial_energy_mwh=observation.measured_soc * self.parameters.bess.energy_mwh,
                    scales=objective_scales(point.objective),
                )
                self.attempts += 1; self.solve_times.append(candidate.solve_time_s)
                if np.isfinite(candidate.objective):
                    candidate_actions.append(candidate.bess_command[:, 0])
                else:
                    self.failures += 1
            relevance = bool(
                candidate_actions
                and np.max(np.ptp(np.asarray(candidate_actions), axis=0)) > 1e-5
            )
            features = CausalBoundaryFeatures(
                period_s=point.period_s, sg_tension=point.sg_tension,
                objective=point.objective, load_magnitude_pu=point.load_magnitude_pu,
                power_spread_pu=point.power_spread_pu,
                ramp_spread_pu_per_s=point.ramp_spread_pu_per_s,
                delay_spread_s=point.delay_spread_s,
                noise_std_pu=point.noise_std_pu, soc=point.soc,
                tie_loading_pu=point.tie_loading_pu,
            )
            self.last_decision = self.scheduler.consider(
                features, causal_change_epoch=self._change_epoch,
                decision_relevant=relevance,
            )
            self.probe_triggers += int(self.last_decision.worthwhile)
        if self.scheduler is not None:
            before = action
            action = self.scheduler.overlay(before)
            if action is not before:
                self.probe_active_calls += 1
                self.probe_l1 += float(np.sum(np.abs(action - before))) * point.period_s
        self.last_action = np.asarray(action, dtype=float)
        self._last_actual_poi = observation.bess_actual_power_pu.copy()
        return self.last_action

    def observe_actual(self, observation: PublicObservation) -> None:
        if self.scheduler is not None:
            self.scheduler.observe_actual_poi(observation.bess_actual_power_pu)

    def diagnostics(self) -> RollingDiagnostics:
        return RollingDiagnostics(
            attempted_optimization_calls=self.attempts,
            solver_failure_calls=self.failures,
            fallback_calls=self.fallbacks,
            probe_triggers=self.probe_triggers,
            probe_active_calls=self.probe_active_calls,
            probe_command_l1_pu_s=self.probe_l1,
            maximum_solve_time_s=max(self.solve_times, default=0.0),
            ordinary_controller_truth_read=False,
            evaluation_only_truth_read=False,
        )


class PerfectCapabilityBoundaryOracle(RollingBoundaryController):
    """Evaluation-only first-order recourse arm; explicitly accepts capability truth."""

    def propose_with_truth(
        self, observation: PublicObservation, truth: CapabilityRealization,
    ) -> np.ndarray:
        self.models = (
            CapabilityModel(
                "EVALUATION_TRUTH",
                float(min(truth.upper_power_pu)),
                float(min(truth.ramp_up_pu_per_s)),
                float(max(truth.delay_s)),
            ),
        )
        return super().propose(observation)

    def diagnostics(self) -> RollingDiagnostics:
        result = super().diagnostics()
        return replace(
            result, ordinary_controller_truth_read=False,
            evaluation_only_truth_read=True,
        )


__all__ = [
    "PerfectCapabilityBoundaryOracle", "RollingBoundaryController",
    "RollingDiagnostics",
]
