"""Causal set-membership command-to-actual deliverability estimator."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from direction5freq.models.capability_contract import CapabilityContract


@dataclass(frozen=True, slots=True)
class DeliverabilitySetSnapshot:
    lower_power_capability_interval_pu: np.ndarray
    upper_power_capability_interval_pu: np.ndarray
    ramp_down_capability_interval_pu_per_s: np.ndarray
    ramp_up_capability_interval_pu_per_s: np.ndarray
    delay_interval_s: np.ndarray
    delay_candidate_count: np.ndarray
    excitation_sufficient: np.ndarray
    performance_power_pu: np.ndarray
    performance_ramp_pu_per_s: np.ndarray
    model_residual_bound_pu: float
    samples: int


class DeliverabilitySetMHE:
    """Windowed set estimator with explicit no-excitation behavior.

    The interval lower ends are evidence-backed delivered magnitudes, clipped
    no higher than the contract floor for safety use.  The upper ends retain all
    models compatible with public command/actual data and bounded residual.
    No historical maximum is represented as an unconditional future guarantee.
    """

    def __init__(
        self,
        contract: CapabilityContract,
        dt_s: float,
        window_s: float = 20.0,
        physical_power_max_pu: float = 0.10,
        physical_ramp_max_pu_per_s: float = 0.10,
        residual_bound_pu: float = 0.0025,
    ) -> None:
        self.contract = contract
        self.dt_s = float(dt_s)
        self.window = max(5, int(round(window_s / dt_s)))
        self.physical_power_max = float(physical_power_max_pu)
        self.physical_ramp_max = float(physical_ramp_max_pu_per_s)
        self.residual_bound = float(residual_bound_pu)
        self._time: deque[float] = deque(maxlen=self.window)
        self._command: deque[np.ndarray] = deque(maxlen=self.window)
        self._actual: deque[np.ndarray] = deque(maxlen=self.window)

    def reset_online_evidence(self) -> None:
        self._time.clear(); self._command.clear(); self._actual.clear()

    def update(
        self, time_s: float, requested_total_power_pu: np.ndarray, actual_poi_power_pu: np.ndarray
    ) -> DeliverabilitySetSnapshot:
        command = np.asarray(requested_total_power_pu, dtype=float)
        actual = np.asarray(actual_poi_power_pu, dtype=float)
        if command.shape != (2,) or actual.shape != (2,):
            raise ValueError("deliverability estimator requires two-area command and actual vectors")
        if self._time and time_s <= self._time[-1]:
            raise ValueError("deliverability estimator timestamps must increase")
        self._time.append(float(time_s)); self._command.append(command.copy()); self._actual.append(actual.copy())
        commands = np.asarray(self._command); actuals = np.asarray(self._actual)
        count = len(actuals)
        if count >= 2:
            ramps = np.diff(actuals, axis=0) / self.dt_s
            observed_up = np.maximum(np.max(ramps, axis=0) - self.residual_bound / self.dt_s, 0.0)
            observed_down = np.maximum(np.max(-ramps, axis=0) - self.residual_bound / self.dt_s, 0.0)
        else:
            observed_up = np.zeros(2); observed_down = np.zeros(2)
        command_range = np.ptp(commands, axis=0) if count else np.zeros(2)
        excitation = (command_range >= 0.04) & (np.max(np.abs(commands), axis=0) >= 0.04)

        contract_upper = np.asarray(self.contract.upper_power_pu)
        contract_lower_magnitude = -np.asarray(self.contract.lower_power_pu)
        delivered_positive = np.maximum(np.max(actuals, axis=0) - self.residual_bound, 0.0)
        delivered_negative = np.maximum(-np.min(actuals, axis=0) - self.residual_bound, 0.0)
        safe_positive = np.minimum(contract_upper, delivered_positive)
        safe_negative = np.minimum(contract_lower_magnitude, delivered_negative)
        positive_interval = np.c_[safe_positive, np.full(2, self.physical_power_max)]
        negative_interval = np.c_[safe_negative, np.full(2, self.physical_power_max)]

        contract_up = np.asarray(self.contract.ramp_up_pu_per_s)
        contract_down = np.asarray(self.contract.ramp_down_pu_per_s)
        safe_ramp_up = np.minimum(contract_up, observed_up)
        safe_ramp_down = np.minimum(contract_down, observed_down)
        ramp_up_interval = np.c_[safe_ramp_up, np.full(2, self.physical_ramp_max)]
        ramp_down_interval = np.c_[safe_ramp_down, np.full(2, self.physical_ramp_max)]

        delay_interval = np.tile(np.array((0.0, max(self.contract.maximum_delay_s))), (2, 1))
        candidate_count = np.full(2, 31, dtype=int)
        if count >= 4:
            time = np.asarray(self._time)
            for area in range(2):
                changes = np.where(np.abs(np.diff(commands[:, area])) >= 0.025)[0]
                if not excitation[area] or len(changes) == 0:
                    continue
                start = int(changes[-1] + 1)
                baseline = actuals[start - 1, area]
                direction = np.sign(commands[start, area] - commands[start - 1, area])
                responses = np.where(direction * (actuals[start:, area] - baseline) >= self.residual_bound)[0]
                if len(responses) == 0:
                    continue
                observed_onset = time[start + int(responses[0])] - time[start]
                # The actuator time constant and threshold add at most 0.30 s;
                # retain a deliberately outer interval.
                low = max(0.0, observed_onset - 0.35)
                high = min(max(self.contract.maximum_delay_s), observed_onset + 0.15)
                if high >= low:
                    delay_interval[area] = (low, high)
                    candidate_count[area] = max(1, int(np.floor((high - low) / 0.05)) + 1)

        performance_power = np.maximum(contract_upper, np.maximum(delivered_positive, delivered_negative))
        performance_power = np.minimum(performance_power, self.physical_power_max)
        performance_ramp = np.maximum(contract_up, np.maximum(observed_up, observed_down))
        performance_ramp = np.minimum(performance_ramp, self.physical_ramp_max)
        return DeliverabilitySetSnapshot(
            lower_power_capability_interval_pu=negative_interval,
            upper_power_capability_interval_pu=positive_interval,
            ramp_down_capability_interval_pu_per_s=ramp_down_interval,
            ramp_up_capability_interval_pu_per_s=ramp_up_interval,
            delay_interval_s=delay_interval,
            delay_candidate_count=candidate_count,
            excitation_sufficient=excitation,
            performance_power_pu=performance_power,
            performance_ramp_pu_per_s=performance_ramp,
            model_residual_bound_pu=self.residual_bound,
            samples=count,
        )
