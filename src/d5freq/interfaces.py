"""Controller-visible interfaces shared by all closed-loop methods.

Hidden simulator truth is intentionally absent from this module. Evaluation
records live on the simulator side and are merged only after controller calls.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol, runtime_checkable


def _finite(value: float, name: str) -> float:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


@dataclass(frozen=True, slots=True)
class Measurement:
    """Signals visible to a controller at one control instant."""

    time_s: float
    omega_pu: float
    p_mech_pu: float
    p_ibr_pu: float
    u_sg_prev_pu: float
    u_ibr_prev_pu: float

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            object.__setattr__(self, field_name, _finite(getattr(self, field_name), field_name))
        if self.time_s < 0.0:
            raise ValueError("time_s must be non-negative")


@dataclass(frozen=True, slots=True)
class ControlAction:
    """Executable SG/IBR commands and auditable controller metadata."""

    u_sg_pu: float
    u_ibr_pu: float
    controller_state: str = "UNSPECIFIED"
    solver_status: str = "not_run"
    solve_time_s: float = 0.0
    max_freq_slack_hz: float = 0.0

    def __post_init__(self) -> None:
        for field_name in (
            "u_sg_pu",
            "u_ibr_pu",
            "solve_time_s",
            "max_freq_slack_hz",
        ):
            object.__setattr__(self, field_name, _finite(getattr(self, field_name), field_name))
        if self.solve_time_s < 0.0:
            raise ValueError("solve_time_s must be non-negative")
        if self.max_freq_slack_hz < 0.0:
            raise ValueError("max_freq_slack_hz must be non-negative")
        if not self.controller_state.strip():
            raise ValueError("controller_state must not be empty")
        if not self.solver_status.strip():
            raise ValueError("solver_status must not be empty")


@runtime_checkable
class FrequencyController(Protocol):
    """Uniform runtime API for the proposed controller and all baselines."""

    def reset(self, initial_measurement: Measurement) -> None: ...

    def act(self, measurement: Measurement) -> ControlAction: ...


__all__ = ["ControlAction", "FrequencyController", "Measurement"]

