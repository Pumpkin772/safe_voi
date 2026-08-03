"""Reference only: grid/load observer should use measured BESS POI power.

This file is intentionally incomplete; it specifies information flow and
state-space structure for Codex implementation and testing.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class PublicGridMeasurement:
    omega_pu: np.ndarray
    tie_pu: float
    mechanical_power_pu: np.ndarray
    actual_bess_power_pu: np.ndarray
    issued_sg_command_pu: np.ndarray


def build_augmented_grid_load_model(A_grid, B_sg, B_bess_actual, E_load, C_measurement):
    """Augment slowly varying load, treating actual BESS power as known input.

    chi = [x_grid; d]
    chi+ = Aaug chi + Bsg u_sg + Bb p_b_actual + noise
    y = Caug chi + measurement noise
    """
    n = A_grid.shape[0]
    nd = E_load.shape[1]
    Aaug = np.block([
        [A_grid, E_load],
        [np.zeros((nd, n)), np.eye(nd)],
    ])
    Bsg_aug = np.vstack([B_sg, np.zeros((nd, B_sg.shape[1]))])
    Bb_aug = np.vstack([B_bess_actual, np.zeros((nd, B_bess_actual.shape[1]))])
    Caug = np.hstack([C_measurement, np.zeros((C_measurement.shape[0], nd))])
    return Aaug, Bsg_aug, Bb_aug, Caug
