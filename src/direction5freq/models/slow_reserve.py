"""Finite-ramp slow reserve used for bridge handover."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class SlowReserveParameters:
    lower_pu: tuple[float, float] = (0.0, 0.0)
    upper_pu: tuple[float, float] = (0.12, 0.12)
    ramp_up_pu_per_s: tuple[float, float] = (0.0020, 0.0020)
    ramp_down_pu_per_s: tuple[float, float] = (0.0030, 0.0030)
    time_constant_s: tuple[float, float] = (15.0, 15.0)


@dataclass(frozen=True, slots=True)
class SlowReserveState:
    power_pu: np.ndarray

    @classmethod
    def equilibrium(cls) -> "SlowReserveState":
        return cls(np.zeros(2))


@dataclass(frozen=True, slots=True)
class SlowReserveDiagnostics:
    requested_pu: np.ndarray
    actual_rate_pu_per_s: np.ndarray
    saturation: np.ndarray


def step_slow_reserve(
    state: SlowReserveState,
    requested_pu: np.ndarray,
    parameters: SlowReserveParameters,
    dt_s: float,
) -> tuple[SlowReserveState, SlowReserveDiagnostics]:
    request = np.clip(
        np.asarray(requested_pu, dtype=float),
        np.asarray(parameters.lower_pu),
        np.asarray(parameters.upper_pu),
    )
    raw_rate = (request - state.power_pu) / np.asarray(parameters.time_constant_s)
    rate = np.clip(raw_rate, -np.asarray(parameters.ramp_down_pu_per_s), np.asarray(parameters.ramp_up_pu_per_s))
    next_power = state.power_pu + dt_s * rate
    next_power = np.where(request >= state.power_pu, np.minimum(next_power, request), np.maximum(next_power, request))
    next_power = np.clip(next_power, np.asarray(parameters.lower_pu), np.asarray(parameters.upper_pu))
    return SlowReserveState(next_power), SlowReserveDiagnostics(
        requested_pu=request,
        actual_rate_pu_per_s=rate,
        saturation=np.abs(raw_rate - rate) > 1e-12,
    )
