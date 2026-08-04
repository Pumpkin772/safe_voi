"""Causal contract-floor violation detection and emergency routing."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from direction5freq.models.capability_contract import CapabilityContract
from direction5freq.models.plant_a_full import PublicObservation


@dataclass(frozen=True, slots=True)
class ContractViolationDecision:
    status: str
    detected: bool
    area_mask: np.ndarray
    expected_guaranteed_power_pu: np.ndarray
    measured_actual_power_pu: np.ndarray
    sg_emergency_increment_pu: np.ndarray
    slow_reserve_request_pu: np.ndarray
    consecutive_misses: np.ndarray


class ContractViolationSupervisor:
    """Detect only after the registered delay and route causal recourse.

    The detector reads applied guaranteed command and measured POI power.  It
    intentionally has no true-capability input and makes no same-instant
    guarantee after an unannounced contract breach.
    """

    def __init__(
        self,
        contract: CapabilityContract,
        period_s: float,
        *,
        tolerance_pu: float = 0.004,
        consecutive_required: int = 2,
    ) -> None:
        self.contract = contract
        self.period_s = float(period_s)
        self.tolerance_pu = float(tolerance_pu)
        self.consecutive_required = int(consecutive_required)
        maximum_delay = float(max(contract.maximum_delay_s))
        self._history: deque[np.ndarray] = deque(
            maxlen=int(np.ceil(maximum_delay / self.period_s)) + 3
        )
        self._misses = np.zeros(2, dtype=int)

    def update(
        self,
        guaranteed_bess_command_pu: np.ndarray,
        observation: PublicObservation,
    ) -> ContractViolationDecision:
        guaranteed = np.asarray(guaranteed_bess_command_pu, dtype=float)
        if guaranteed.shape != (2,):
            raise ValueError("guaranteed command must have two areas")
        self._history.append(guaranteed.copy())
        delay_steps = int(np.ceil(max(self.contract.maximum_delay_s) / self.period_s))
        if len(self._history) <= delay_steps:
            expected = np.zeros(2)
            eligible = np.zeros(2, dtype=bool)
        else:
            expected = np.asarray(list(self._history)[-1 - delay_steps])
            eligible = np.abs(expected) >= 0.75 * np.asarray(self.contract.upper_power_pu)
        actual = np.asarray(observation.bess_actual_power_pu, dtype=float)
        same_direction = np.sign(actual) == np.sign(expected)
        underdelivered = (
            eligible
            & (~same_direction | (np.abs(actual) + self.tolerance_pu < np.abs(expected)))
        )
        self._misses = np.where(underdelivered, self._misses + 1, 0)
        detected_mask = self._misses >= self.consecutive_required
        missing = np.where(
            detected_mask,
            np.sign(expected) * np.maximum(np.abs(expected) - np.abs(actual), 0.0),
            0.0,
        )
        sg_emergency = np.clip(missing, -0.04, 0.04)
        reserve_request = np.clip(np.maximum(missing, 0.0), 0.0, 0.08)
        detected = bool(detected_mask.any())
        return ContractViolationDecision(
            status="CONTRACT_VIOLATION_DETECTED" if detected else "NO_DETECTED_VIOLATION",
            detected=detected,
            area_mask=detected_mask,
            expected_guaranteed_power_pu=expected,
            measured_actual_power_pu=actual.copy(),
            sg_emergency_increment_pu=sg_emergency,
            slow_reserve_request_pu=reserve_request,
            consecutive_misses=self._misses.copy(),
        )


__all__ = ["ContractViolationDecision", "ContractViolationSupervisor"]
