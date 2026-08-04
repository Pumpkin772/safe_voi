"""Reference semantics for contract-safe and revocable surplus control."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class ContractCapability:
    power_lower: np.ndarray
    power_upper: np.ndarray
    ramp_down: np.ndarray
    ramp_up: np.ndarray
    delay_candidates_s: tuple[float, ...]


@dataclass(frozen=True)
class OnlinePerformanceEnvelope:
    power_lower: np.ndarray
    power_upper: np.ndarray
    ramp_down: np.ndarray
    ramp_up: np.ndarray
    delay_candidates_s: tuple[float, ...]
    confidence: float


@dataclass(frozen=True)
class SplitCommand:
    guaranteed: np.ndarray
    surplus: np.ndarray

    @property
    def total(self) -> np.ndarray:
        return self.guaranteed + self.surplus


def hard_safety_capability(contract: ContractCapability) -> ContractCapability:
    """Hard safety never silently uses an unverified online envelope."""
    return contract
