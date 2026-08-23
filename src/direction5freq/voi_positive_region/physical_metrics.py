"""Physical grid-service and resource metrics, separate from MPC regularizers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class GridMetricScales:
    frequency_hz: float = 0.20
    ace_pu: float = 0.05
    tie_pu: float = 0.025
    frequency_bias: float = 21.0


@dataclass(frozen=True)
class PhysicalMetrics:
    grid_service_cost: float
    frequency_peak_hz: float
    frequency_iae_hz_s: float
    ace_iae_pu_s: float
    tie_iae_pu_s: float
    sg_command_mileage_pu: float
    bess_command_mileage_pu: float


def trajectory_metrics(
    grid_states: np.ndarray,
    sg_commands: np.ndarray,
    bess_commands: np.ndarray,
    *,
    period_s: float,
    nominal_frequency_hz: float = 50.0,
    scales: GridMetricScales = GridMetricScales(),
    previous_sg_command: np.ndarray | None = None,
    previous_bess_command: np.ndarray | None = None,
) -> PhysicalMetrics:
    """Evaluate measured physical performance without optimizer move penalties."""

    states = np.asarray(grid_states, dtype=float)
    sg = np.asarray(sg_commands, dtype=float)
    bess = np.asarray(bess_commands, dtype=float)
    if states.ndim != 2 or states.shape[0] < 3:
        raise ValueError("grid states must be state-by-time")
    if sg.shape != bess.shape or sg.ndim != 2 or sg.shape[0] != 2:
        raise ValueError("SG and BESS commands must be two-area time series")
    if states.shape[1] != sg.shape[1]:
        raise ValueError("state and command time dimensions differ")

    frequency = nominal_frequency_hz * states[:2]
    tie = states[2]
    ace = np.vstack((
        scales.frequency_bias * states[0] + tie,
        scales.frequency_bias * states[1] - tie,
    ))
    grid_cost = period_s * float(np.sum(
        (frequency / scales.frequency_hz) ** 2
        + (ace / scales.ace_pu) ** 2
    ) + np.sum((tie / scales.tie_pu) ** 2))

    previous_sg = (
        np.zeros(2) if previous_sg_command is None
        else np.asarray(previous_sg_command, dtype=float)
    )
    previous_bess = (
        np.zeros(2) if previous_bess_command is None
        else np.asarray(previous_bess_command, dtype=float)
    )
    sg_delta = np.diff(np.column_stack((previous_sg, sg)), axis=1)
    bess_delta = np.diff(np.column_stack((previous_bess, bess)), axis=1)
    return PhysicalMetrics(
        grid_service_cost=grid_cost,
        frequency_peak_hz=float(np.max(np.abs(frequency))),
        frequency_iae_hz_s=period_s * float(np.sum(np.abs(frequency))),
        ace_iae_pu_s=period_s * float(np.sum(np.abs(ace))),
        tie_iae_pu_s=period_s * float(np.sum(np.abs(tie))),
        sg_command_mileage_pu=float(np.sum(np.abs(sg_delta))),
        bess_command_mileage_pu=float(np.sum(np.abs(bess_delta))),
    )
