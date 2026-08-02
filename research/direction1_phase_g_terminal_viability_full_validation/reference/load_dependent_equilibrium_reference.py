"""Reference equilibrium definition for terminal error coordinates."""
from __future__ import annotations
import numpy as np


def equilibrium_from_static_solution(pg1: float, pg2: float, ptie: float, state_dimension: int = 9) -> np.ndarray:
    xstar = np.zeros(state_dimension, dtype=float)
    # [omega1, omega2, tie, valve1, valve2, pm1, pm2, pb1, pb2]
    xstar[2] = ptie
    xstar[3] = pg1
    xstar[4] = pg2
    xstar[5] = pg1
    xstar[6] = pg2
    return xstar
