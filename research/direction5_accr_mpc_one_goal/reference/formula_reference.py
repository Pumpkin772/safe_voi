"""Reference ACCR equations and diagnostics. Not a complete controller."""
from __future__ import annotations
import numpy as np


def allocation_neutral(base_sg: np.ndarray, base_bess: np.ndarray, probe: np.ndarray):
    """Return commands preserving the aggregate SFR command."""
    ug = np.asarray(base_sg, dtype=float) - np.asarray(probe, dtype=float)
    ub = np.asarray(base_bess, dtype=float) + np.asarray(probe, dtype=float)
    assert np.allclose(ug + ub, np.asarray(base_sg) + np.asarray(base_bess))
    return ug, ub


def energy_step_mwh(
    energy_mwh: np.ndarray,
    power_pu: np.ndarray,
    dt_s: float,
    base_mw: float,
    eta_charge: float,
    eta_discharge: float,
) -> np.ndarray:
    p = np.asarray(power_pu, dtype=float)
    discharge = np.maximum(p, 0.0)
    charge = np.maximum(-p, 0.0)
    delta = dt_s * base_mw / 3600.0 * (
        discharge / eta_discharge - eta_charge * charge
    )
    return np.asarray(energy_mwh, dtype=float) - delta


def update_feasible_mask(
    current_mask: np.ndarray,
    actual_next: float,
    predictions: np.ndarray,
    residual_bound: float,
) -> np.ndarray:
    """Set-membership intersection for a finite candidate grid."""
    return np.asarray(current_mask, dtype=bool) & (
        np.abs(float(actual_next) - np.asarray(predictions)) <= float(residual_bound)
    )


def value_recovery(contract_cost: float, method_cost: float, oracle_cost: float) -> float:
    denominator = float(contract_cost) - float(oracle_cost)
    if denominator <= 0.0:
        return float("nan")
    return (float(contract_cost) - float(method_cost)) / denominator


def pairwise_minimum_separation(predicted_outputs: np.ndarray, metric: np.ndarray | None = None) -> float:
    """predicted_outputs shape=(hypotheses, time)."""
    y = np.asarray(predicted_outputs, dtype=float)
    if y.ndim != 2 or y.shape[0] < 2:
        return 0.0
    W = np.eye(y.shape[1]) if metric is None else np.asarray(metric, dtype=float)
    minimum = np.inf
    for i in range(y.shape[0]):
        for j in range(i + 1, y.shape[0]):
            delta = y[i] - y[j]
            minimum = min(minimum, float(delta @ W @ delta))
    return float(minimum)
