"""Causal control-aligned surplus excitation for development experiments."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm


@dataclass(frozen=True)
class ControlAlignedConfig:
    amplitude_pu: float = 0.003
    binding_command_pu: float = 0.040
    active_steps: int = 2
    cooldown_steps: int = 4
    maximum_windows: int = 10
    maximum_frequency_hz: float = 0.25
    maximum_ace_pu: float = 0.12
    contract_power_pu: float = 0.045
    certificate_samples: int = 2
    certificate_validity_s: float = 120.0
    minimum_excitation_margin_pu: float = 0.0015
    measurement_noise_std_pu: float = 0.001
    observation_residual_bound_pu: float = 0.00025
    evidence_window_correlation: float = 0.2
    false_optimism_rate: float = 0.01


class ControlAlignedSequentialProbe:
    """Adds BESS surplus while leaving the SG contract-safe action unchanged."""

    def __init__(self, config: ControlAlignedConfig = ControlAlignedConfig()) -> None:
        self.config = config
        self._remaining_active = 0
        self._remaining_cooldown = 0
        self._direction = 0.0
        self.windows_started = 0
        self.active_calls = 0
        self.command_l1_pu = 0.0
        self.power_certified_until_s = -float("inf")
        self.evidence_started_at_s: float | None = None
        self._signed_delivery_samples: list[float] = []

    def observe_delivery(
        self,
        time_s: float,
        issued_bess_command: np.ndarray,
        actual_bess_poi_power: np.ndarray,
    ) -> bool:
        """Issue a one-sided power certificate from causal measured delivery."""

        issued = np.asarray(issued_bess_command, dtype=float)
        actual = np.asarray(actual_bess_poi_power, dtype=float)
        area = int(np.argmax(np.abs(issued)))
        direction = float(np.sign(issued[area]))
        eligible = bool(
            direction != 0.0
            and abs(issued[area])
            > self.config.contract_power_pu + self.config.minimum_excitation_margin_pu
        )
        if eligible:
            self._signed_delivery_samples.append(direction * float(actual[area]))
        samples = len(self._signed_delivery_samples)
        effective_samples = (
            samples
            * (1.0 - self.config.evidence_window_correlation)
            / (1.0 + self.config.evidence_window_correlation)
        )
        threshold = (
            self.config.contract_power_pu
            + self.config.observation_residual_bound_pu
            + float(norm.ppf(1.0 - self.config.false_optimism_rate))
            * self.config.measurement_noise_std_pu
            / np.sqrt(max(effective_samples, 1e-12))
        )
        newly_certified = bool(
            samples >= self.config.certificate_samples
            and float(np.mean(self._signed_delivery_samples)) > threshold
        )
        if newly_certified:
            start = time_s if self.evidence_started_at_s is None else self.evidence_started_at_s
            self.power_certified_until_s = start + self.config.certificate_validity_s
        return newly_certified

    def power_certified(self, time_s: float) -> bool:
        return bool(time_s <= self.power_certified_until_s)

    @property
    def signed_delivery_samples(self) -> tuple[float, ...]:
        return tuple(self._signed_delivery_samples)

    def overlay(
        self,
        contract_action: np.ndarray,
        time_s: float,
        frequency_deviation_hz: np.ndarray,
        ace_pu: np.ndarray,
        measured_soc: np.ndarray,
    ) -> np.ndarray:
        action = np.asarray(contract_action, dtype=float)
        if self._remaining_cooldown > 0 and self._remaining_active == 0:
            self._remaining_cooldown -= 1

        if self._remaining_active == 0 and self._remaining_cooldown == 0:
            bess = action[[1, 3]]
            area = int(np.argmax(np.abs(bess)))
            direction = float(np.sign(bess[area]))
            eligible = bool(
                self.windows_started < self.config.maximum_windows
                and direction != 0.0
                and abs(bess[area]) >= self.config.binding_command_pu
                and np.max(np.abs(frequency_deviation_hz)) <= self.config.maximum_frequency_hz
                and np.max(np.abs(ace_pu)) <= self.config.maximum_ace_pu
                and np.all((measured_soc >= 0.25) & (measured_soc <= 0.75))
            )
            if eligible:
                if self.evidence_started_at_s is None:
                    self.evidence_started_at_s = float(time_s)
                if time_s > self.evidence_started_at_s + self.config.certificate_validity_s:
                    return action
                self._direction = direction
                self._remaining_active = self.config.active_steps
                self.windows_started += 1

        if self._remaining_active == 0:
            return action

        bess = action[[1, 3]]
        area = int(np.argmax(np.abs(bess)))
        result = action.copy()
        result[[1, 3][area]] += self._direction * self.config.amplitude_pu
        self._remaining_active -= 1
        self.active_calls += 1
        self.command_l1_pu += self.config.amplitude_pu
        if self._remaining_active == 0:
            self._remaining_cooldown = self.config.cooldown_steps
        return result
