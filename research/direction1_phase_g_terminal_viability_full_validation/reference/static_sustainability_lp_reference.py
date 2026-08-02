"""Small reference LP for classifying sustainable steady-state cells."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.optimize import linprog


@dataclass(frozen=True)
class StaticLimits:
    sg_max: tuple[float, float]
    tie_max: float


def sustainable(load: tuple[float, float], limits: StaticLimits) -> dict:
    # variables: pg1, pg2, ptie; BESS steady power fixed to zero
    c = np.zeros(3)
    Aeq = np.array([[1.0, 0.0, -1.0], [0.0, 1.0, 1.0]])
    beq = np.asarray(load, dtype=float)
    bounds = [(-limits.sg_max[0], limits.sg_max[0]),
              (-limits.sg_max[1], limits.sg_max[1]),
              (-limits.tie_max, limits.tie_max)]
    res = linprog(c, A_eq=Aeq, b_eq=beq, bounds=bounds, method="highs")
    return {"sustainable": bool(res.success), "solution": None if not res.success else res.x.tolist()}
