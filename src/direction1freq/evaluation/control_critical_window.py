"""Evaluation-only causal update-time and matched control-window utilities."""

from __future__ import annotations

import numpy as np

from direction1freq.identification.passive_set_membership import CapabilitySetEstimate


def contains_capability(estimate: CapabilitySetEstimate, capability: np.ndarray) -> bool:
    value = np.asarray(capability, dtype=float)
    return bool(np.all(value >= estimate.lower - 1e-12) and np.all(value <= estimate.upper + 1e-12))


def causal_control_relevant_update_time(
    estimates: list[CapabilitySetEstimate], capabilities: list[np.ndarray],
    change_time_s: float, d_ctrl: float = 0.08,
) -> float:
    """Earliest past-only set change that covers the contemporaneous truth."""

    if len(estimates) != len(capabilities):
        raise ValueError("estimates and evaluation labels must have equal length")
    for index in range(1, len(estimates)):
        current = estimates[index]
        if current.time_s < change_time_s:
            continue
        previous = estimates[index - 1]
        bound_change = max(
            float(np.max(np.abs(current.lower - previous.lower))),
            float(np.max(np.abs(current.upper - previous.upper))),
        )
        if current.set_changed and bound_change >= d_ctrl and contains_capability(
            current, capabilities[index]
        ):
            return float(current.time_s)
    return float("nan")
