"""Safe zero-mean active capability probe and causal response monitor."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class ProbeDecision:
    action: np.ndarray
    probe_bess: np.ndarray
    backup_feasible: bool
    safety_margin_hz: float
    predicted_information_gain: float
    suppressed_reason: str


class SafeProbeDesigner:
    """Public-state candidate selection with a local SG compensation path."""

    def __init__(
        self, period_s: float, amplitude_pu: float = 0.04,
        start_time_s: float = 8.0, stop_time_s: float = 52.0,
    ) -> None:
        self.period_s = float(period_s)
        self.amplitude_pu = float(amplitude_pu)
        self.start_time_s = float(start_time_s)
        self.stop_time_s = float(stop_time_s)
        self.counter = 0

    def reset(self) -> None:
        self.counter = 0

    def apply(
        self, time_s: float, regulation_action: np.ndarray,
        frequency_hz: np.ndarray, ace_pu: np.ndarray, sg_reserve_pu: float,
    ) -> ProbeDecision:
        base = np.asarray(regulation_action, dtype=float).copy()
        frequency = np.asarray(frequency_hz, dtype=float)
        ace = np.asarray(ace_pu, dtype=float)
        margin = 0.80 - float(np.max(np.abs(frequency)))
        active_window = self.start_time_s <= time_s <= self.stop_time_s
        safety_ok = margin >= 0.55 and float(np.max(np.abs(ace))) <= 0.10
        sign = 1.0 if self.counter % 2 == 0 else -1.0
        probe = self.amplitude_pu * np.array([sign, -sign])
        sg_candidate = base[[0, 2]] - probe
        backup_feasible = bool(np.all(np.abs(sg_candidate) <= sg_reserve_pu + 1e-12))
        if not active_window:
            reason = "outside_probe_window"
            probe[:] = 0.0
        elif not safety_ok:
            reason = "public_frequency_or_ace_margin"
            probe[:] = 0.0
        elif not backup_feasible:
            reason = "sg_backup_reserve_infeasible"
            probe[:] = 0.0
        else:
            reason = ""
            base[[0, 2]] = sg_candidate
            base[[1, 3]] += probe
            self.counter += 1
        information = float(np.dot(probe, probe) / max(self.period_s, 1e-12))
        return ProbeDecision(base, probe, backup_feasible, margin, information, reason)


@dataclass(frozen=True, slots=True)
class ActiveInformationState:
    update_time_s: float
    candidate: str
    effective_power_upper_pu: float
    ramp_upper_pu_s: float
    delay_lower_s: float
    information_gain: float


class ActiveResponseIdentifier:
    """High-rate causal external-response monitor; no capability label input."""

    def __init__(self, dt_s: float = 0.05) -> None:
        self.dt_s = float(dt_s)
        self.reset()

    def reset(self) -> None:
        self.previous_command = np.zeros(2)
        self.previous_power = np.zeros(2)
        self.transition_time = float("nan")
        self.transition_initial_power = np.zeros(2)
        self.transition_target = np.zeros(2)
        self.maximum_slope = 0.0
        self.first_response_time = float("nan")
        self.update_time = float("nan")
        self.candidate = "uncertain"
        self.power_upper = 0.10
        self.ramp_upper = 0.08
        self.delay_lower = 0.0
        self.information = 0.0

    def update(
        self, time_s: float, issued_bess_command: np.ndarray,
        measured_bess_power: np.ndarray, frequency_hz: np.ndarray,
    ) -> ActiveInformationState:
        command = np.asarray(issued_bess_command, dtype=float)
        power = np.asarray(measured_bess_power, dtype=float) + 0.60 * np.asarray(frequency_hz) / 50.0
        change = float(np.max(np.abs(command - self.previous_command)))
        if change >= 0.045:
            self.transition_time = float(time_s)
            self.transition_initial_power = power.copy()
            self.transition_target = command.copy()
            self.maximum_slope = 0.0
            self.first_response_time = float("nan")
        slope = float(np.max(np.abs(power - self.previous_power)) / self.dt_s)
        self.maximum_slope = max(self.maximum_slope, slope)
        if np.isfinite(self.transition_time):
            elapsed = float(time_s - self.transition_time)
            delta = self.transition_target - self.transition_initial_power
            progress = power - self.transition_initial_power
            informative = np.abs(delta) >= 0.03
            if not np.isfinite(self.first_response_time) and np.any(
                informative & (np.sign(delta) * progress >= 0.10 * np.abs(delta))
            ):
                self.first_response_time = elapsed
            changed = False
            if elapsed >= 0.65 and not np.isfinite(self.first_response_time):
                self.delay_lower = max(self.delay_lower, 0.60)
                self.candidate = "delay"
                changed = True
            elif elapsed >= 0.80 and self.maximum_slope <= 0.025 and np.max(np.abs(delta)) >= 0.05:
                self.ramp_upper = min(self.ramp_upper, 0.030)
                self.candidate = "ramp"
                changed = True
            elif elapsed >= 1.20:
                tracking_gap = float(np.max(np.abs(self.transition_target - power)))
                if tracking_gap >= 0.010 and self.maximum_slope <= 0.035:
                    self.power_upper = min(
                        self.power_upper, float(np.max(np.abs(power))) + 0.006
                    )
                    self.candidate = "effective_power_limit"
                    changed = True
            if changed and not np.isfinite(self.update_time):
                self.update_time = float(time_s)
            self.information = max(
                self.information,
                change**2 / max(1e-6, 0.004**2) * min(max(elapsed, 0.0), 2.0),
            )
        self.previous_command = command.copy()
        self.previous_power = power.copy()
        return ActiveInformationState(
            self.update_time, self.candidate, self.power_upper,
            self.ramp_upper, self.delay_lower, self.information,
        )
