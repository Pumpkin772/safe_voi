"""Causal delayed-actuator set membership and CUSUM reset logic."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class CapabilityEstimate:
    power_magnitude_interval_pu: tuple[float, float]
    ramp_interval_pu_per_s: tuple[float, float]
    delay_candidates_s: tuple[float, ...]
    energy_interval_mwh: tuple[float, float]
    alarm: bool
    updated: bool
    cusum_score: float
    one_step_residual_pu: float
    model_set_nonempty: bool


class CausalCapabilitySetEstimator:
    """Update a safe current-capability set from samples available at `0:k`.

    The set contracts only after achieved command/output evidence.  A strictly
    causal one-sided CUSUM expands it to the registered global physical set.
    Event source labels are never produced or consumed.
    """

    def __init__(
        self, dt_s: float = 0.05, rating_pu: float = 0.1,
        global_ramp_pu_per_s: float = 0.08,
        delay_candidates_s: tuple[float, ...] = (0.0, 0.2, 0.5, 1.0, 2.0),
        noise_bound_pu: float = 0.0015,
        actuator_time_constant_s: float = 0.15,
        initial_energy_interval_mwh: tuple[float, float] = (17.5, 32.5),
        system_base_mva: float = 1000.0,
        efficiency_interval: tuple[float, float] = (0.93, 0.97),
        cusum_drift: float = 1.0, cusum_threshold: float = 8.0,
    ) -> None:
        self.dt_s = float(dt_s); self.rating = float(rating_pu); self.global_ramp = float(global_ramp_pu_per_s)
        self.global_delays = tuple(float(value) for value in delay_candidates_s)
        self.noise = float(noise_bound_pu); self.tau = float(actuator_time_constant_s)
        self.base = float(system_base_mva); self.eta_interval = efficiency_interval
        self.cusum_drift = float(cusum_drift); self.cusum_threshold = float(cusum_threshold)
        maximum_steps = int(round(max(self.global_delays) / self.dt_s)) + 3
        self.commands: deque[float] = deque([0.0] * maximum_steps, maxlen=maximum_steps)
        self.previous_power = 0.0; self.power_lower = 0.0; self.ramp_lower = 0.0
        self.delay_candidates = self.global_delays
        self.energy_lower, self.energy_upper = map(float, initial_energy_interval_mwh)
        self.score = 0.0; self.cooldown = 0; self.sample_index = 0

    def _command_at_delay(self, delay_s: float) -> float:
        steps = int(round(delay_s / self.dt_s))
        sequence = list(self.commands)
        return sequence[-1 - min(steps, len(sequence) - 1)]

    def _predict(self, delay_s: float) -> float:
        target = self._command_at_delay(delay_s)
        alpha = 1.0 - np.exp(-self.dt_s / self.tau)
        rate_limited = np.clip((target - self.previous_power) / self.tau, -self.global_ramp, self.global_ramp)
        first_order = self.previous_power + alpha * (target - self.previous_power)
        return float(np.clip(first_order, self.previous_power - self.global_ramp * self.dt_s, self.previous_power + self.global_ramp * self.dt_s)) if abs(rate_limited) >= self.global_ramp - 1e-12 else float(first_order)

    def _propagate_energy(self, measured_power_pu: float) -> None:
        eta_low, eta_high = self.eta_interval
        power_mw = measured_power_pu * self.base
        if power_mw >= 0:
            low_change = -power_mw / eta_low * self.dt_s / 3600.0
            high_change = -power_mw / eta_high * self.dt_s / 3600.0
        else:
            low_change = -power_mw * eta_low * self.dt_s / 3600.0
            high_change = -power_mw * eta_high * self.dt_s / 3600.0
        self.energy_lower += min(low_change, high_change)
        self.energy_upper += max(low_change, high_change)

    def update(self, issued_total_command_pu: float, measured_power_pu: float) -> CapabilityEstimate:
        command = float(issued_total_command_pu); measured = float(measured_power_pu)
        self.commands.append(command)
        nominal_prediction = self._predict(0.2)
        residual = abs(measured - nominal_prediction)
        normalized = residual / max(self.noise, 1e-12)
        self.score = max(0.0, self.score + normalized - self.cusum_drift)
        alarm = self.cooldown == 0 and self.score >= self.cusum_threshold
        updated = False
        if alarm:
            self.power_lower = 0.0; self.ramp_lower = 0.0
            self.delay_candidates = self.global_delays
            self.score = 0.0; self.cooldown = int(round(3.0 / self.dt_s)); updated = True
        else:
            self.cooldown = max(0, self.cooldown - 1)
            # Achieved I/O can only raise guaranteed lower capability.
            if abs(command) >= 0.015 and residual <= 2.0 * self.noise:
                self.power_lower = max(self.power_lower, max(abs(measured) - 2.0 * self.noise, 0.0))
            observed_ramp = abs(measured - self.previous_power) / self.dt_s
            if abs(command - self.previous_power) >= 0.01 and residual <= 2.5 * self.noise:
                self.ramp_lower = max(self.ramp_lower, max(observed_ramp - 2.0 * self.noise / self.dt_s, 0.0))
            # Delays are removed only by one-step inconsistency with a generous
            # bounded-noise/model-error envelope. An empty set triggers reset.
            consistent = tuple(delay for delay in self.delay_candidates if abs(measured - self._predict(delay)) <= 0.006)
            if consistent:
                self.delay_candidates = consistent
            else:
                self.delay_candidates = self.global_delays; updated = True
        self._propagate_energy(measured)
        self.previous_power = measured; self.sample_index += 1
        return CapabilityEstimate(
            (min(self.power_lower, self.rating), self.rating),
            (min(self.ramp_lower, self.global_ramp), self.global_ramp),
            self.delay_candidates, (self.energy_lower, self.energy_upper), alarm, updated,
            float(self.score), float(residual), bool(self.delay_candidates),
        )
