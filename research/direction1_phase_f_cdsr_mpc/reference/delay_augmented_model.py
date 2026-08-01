"""Reference formulas for one-period fractional input delay augmentation."""

from __future__ import annotations
import numpy as np
from scipy.signal import cont2discrete


def zoh_input_split(A: np.ndarray, B: np.ndarray, E: np.ndarray, Ts: float, tau: float):
    """Return Ad, B_current(tau), B_previous(tau), Ed.

    Assumes 0 <= tau < Ts:
    previous command acts for tau seconds and current command acts for Ts-tau.
    """
    if not (0.0 <= tau < Ts):
        raise ValueError("tau must lie in [0, Ts)")
    C = np.zeros((1, A.shape[0]))
    D = np.zeros((1, B.shape[1] + E.shape[1]))
    AB = np.column_stack([B, E])
    Ad, Bd_all, *_ = cont2discrete((A, AB, C, D), Ts, method="zoh")
    _, B_current_all, *_ = cont2discrete((A, AB, C, D), Ts - tau, method="zoh")
    Bd = Bd_all[:, :B.shape[1]]
    Ed = Bd_all[:, B.shape[1]:]
    B_current = B_current_all[:, :B.shape[1]]
    B_previous = Bd - B_current
    return np.asarray(Ad), np.asarray(B_current), np.asarray(B_previous), np.asarray(Ed)


def augment_previous_action(Ad, B_current, B_previous, Ed):
    """z=[x;u_prev], z+ = Abar z + Bbar u + Ebar d."""
    n, m = B_current.shape
    Abar = np.block([
        [Ad, B_previous],
        [np.zeros((m, n)), np.zeros((m, m))],
    ])
    Bbar = np.vstack([B_current, np.eye(m)])
    Ebar = np.vstack([Ed, np.zeros((m, Ed.shape[1]))])
    return Abar, Bbar, Ebar
