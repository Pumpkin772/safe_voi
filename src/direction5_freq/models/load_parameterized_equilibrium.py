"""Load-parameterized two-area equilibrium solved as a registered static LP."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog


@dataclass(frozen=True, slots=True)
class EquilibriumResult:
    feasible: bool
    load_pu: np.ndarray
    sg_power_pu: np.ndarray
    tie_pu: float
    bess_power_pu: np.ndarray
    state_pu: np.ndarray
    balance_residual_pu: np.ndarray
    solver_status: str


def solve_sustainable_equilibrium(
    load_pu: np.ndarray,
    sg_lower_pu: np.ndarray,
    sg_upper_pu: np.ndarray,
    tie_limit_pu: float,
) -> EquilibriumResult:
    """Solve the p_b*=0 sustainable balance with minimum absolute tie flow."""

    load = np.asarray(load_pu, dtype=float)
    lower = np.asarray(sg_lower_pu, dtype=float)
    upper = np.asarray(sg_upper_pu, dtype=float)
    if load.shape != (2,) or lower.shape != (2,) or upper.shape != (2,):
        raise ValueError("load and SG bounds must contain two areas")
    # z = [pm1, pm2, tie, |tie|]
    objective = np.array([0.0, 0.0, 0.0, 1.0])
    equality = np.array(
        [
            [1.0, 0.0, -1.0, 0.0],
            [0.0, 1.0, 1.0, 0.0],
        ]
    )
    inequality = np.array(
        [
            [0.0, 0.0, 1.0, -1.0],
            [0.0, 0.0, -1.0, -1.0],
        ]
    )
    result = linprog(
        objective,
        A_ub=inequality,
        b_ub=np.zeros(2),
        A_eq=equality,
        b_eq=load,
        bounds=[
            (float(lower[0]), float(upper[0])),
            (float(lower[1]), float(upper[1])),
            (-float(tie_limit_pu), float(tie_limit_pu)),
            (0.0, None),
        ],
        method="highs",
    )
    if not result.success:
        nan = np.full(2, np.nan)
        return EquilibriumResult(
            False,
            load.copy(),
            nan,
            float("nan"),
            np.zeros(2),
            np.full(9, np.nan),
            nan,
            str(result.message),
        )
    pm = np.asarray(result.x[:2], dtype=float)
    tie = float(result.x[2])
    bess = np.zeros(2)
    residual = np.array(
        [pm[0] + bess[0] - load[0] - tie, pm[1] + bess[1] - load[1] + tie]
    )
    # Plant-A control-layer state: omega, tie, valve, mechanical, actual BESS.
    state = np.r_[np.zeros(2), tie, pm, pm, bess]
    return EquilibriumResult(
        True,
        load.copy(),
        pm,
        tie,
        bess,
        state,
        residual,
        str(result.message),
    )
