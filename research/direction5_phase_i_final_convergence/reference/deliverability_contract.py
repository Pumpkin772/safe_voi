"""Reference semantics for safety contract and online deliverability."""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class DeliverabilityEnvelope:
    p_discharge: np.ndarray
    p_charge: np.ndarray
    ramp_up: np.ndarray
    ramp_down: np.ndarray
    delay_candidates_s: tuple[float, ...]


@dataclass(frozen=True)
class CapabilityInformation:
    contract_floor: DeliverabilityEnvelope
    online_feasible_set: DeliverabilityEnvelope
    measured_energy_mwh: np.ndarray
    contract_violation_alarm: np.ndarray


def safety_envelope(info: CapabilityInformation) -> DeliverabilityEnvelope:
    """Hard safety constraints always use the registered contract floor."""
    return info.contract_floor
