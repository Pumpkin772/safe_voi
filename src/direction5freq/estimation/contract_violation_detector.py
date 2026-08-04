"""Causal evidence state for a capability fall below the contract floor."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from direction5freq.models.capability_contract import CapabilityContract


@dataclass(frozen=True, slots=True)
class ContractViolationState:
    status: str
    evidence_count: np.ndarray
    affected_area: np.ndarray


class ContractViolationDetector:
    def __init__(self, contract: CapabilityContract, persistence_samples: int = 3, tolerance_pu: float = 0.003) -> None:
        self.contract = contract
        self.persistence_samples = int(persistence_samples)
        self.tolerance_pu = float(tolerance_pu)
        self._counts = np.zeros(2, dtype=int)

    def update(self, requested_pu: np.ndarray, actual_pu: np.ndarray, settled: bool) -> ContractViolationState:
        request = np.asarray(requested_pu, dtype=float)
        actual = np.asarray(actual_pu, dtype=float)
        upper = np.asarray(self.contract.upper_power_pu)
        lower = np.asarray(self.contract.lower_power_pu)
        asks_for_contract = (request >= upper) | (request <= lower)
        misses_contract = ((request >= upper) & (actual < upper - self.tolerance_pu)) | (
            (request <= lower) & (actual > lower + self.tolerance_pu)
        )
        evidence = asks_for_contract & misses_contract & bool(settled)
        self._counts = np.where(evidence, self._counts + 1, np.maximum(self._counts - 1, 0))
        affected = self._counts >= self.persistence_samples
        return ContractViolationState(
            status="DETECTED_CONTRACT_VIOLATION" if np.any(affected) else "NO_DETECTED_VIOLATION",
            evidence_count=self._counts.copy(),
            affected_area=affected,
        )
