from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
import numpy as np

@dataclass(frozen=True)
class PublicMeasurement:
    timestamp_s: float
    frequency_hz: np.ndarray
    ace_pu: np.ndarray
    tie_line_pu: np.ndarray
    sg_mechanical_pu: np.ndarray
    ibr_poi_power_pu: np.ndarray
    last_issued_command_pu: np.ndarray

@dataclass(frozen=True)
class ControlAction:
    sg_sfr_command_pu: np.ndarray
    ibr_sfr_command_pu: np.ndarray
    feasible: bool
    used_backup: bool
    solver_status: str

class DeployableController(Protocol):
    evaluation_only: bool
    def reset(self, public_initialization: dict) -> None: ...
    def update(self, measurement: PublicMeasurement) -> ControlAction: ...
