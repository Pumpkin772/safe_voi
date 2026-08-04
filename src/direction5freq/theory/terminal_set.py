"""Load-parameterized local robust positively invariant terminal boxes."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.linalg import solve_discrete_are
from scipy.signal import cont2discrete

from direction5freq.models.plant_a_full import PlantAFull


@dataclass(frozen=True, slots=True)
class LocalRPICertificate:
    period_s: float
    load_pu: np.ndarray
    equilibrium_state: np.ndarray
    equilibrium_input: np.ndarray
    terminal_feedback_gain: np.ndarray
    error_box_radius: np.ndarray
    additive_remainder_bound: np.ndarray
    closed_loop_spectral_radius: float
    absolute_closed_loop_spectral_radius: float
    invariance_residual: float
    minimum_state_margin_pu: float
    minimum_input_margin_pu: float
    nonempty: bool
    admissible: bool
    claim_level: str


def compute_local_rpi_certificate(period_s: float, load_pu: np.ndarray) -> LocalRPICertificate:
    """Compute a box RPI certificate for the registered local terminal model.

    The certificate is conditional on the explicit one-step additive remainder
    bound and a quiescent BESS command pipeline. It is not a proof for the full
    native ANDES DAE.
    """

    plant = PlantAFull()
    load = np.asarray(load_pu, dtype=float)
    if load.shape != (2,) or np.any(load < 0.0):
        raise ValueError("terminal load must be a nonnegative two-area vector")
    if np.any(load >= np.asarray(plant.parameters.sg_power_upper_pu)):
        raise ValueError("local sustainable terminal certificate requires SG-only equilibrium margin")
    a, b, _c, _e = plant.linear_continuous_model_separate()
    ad, bd, _, _, _ = cont2discrete((a, b, np.eye(9), np.zeros((9, 4))), period_s)
    b_sg = bd[:, [0, 2]]
    q = np.diag((200.0, 200.0, 100.0, 2.0, 2.0, 2.0, 2.0, 1.0, 1.0))
    r = np.eye(2) * 0.5
    p = solve_discrete_are(ad, b_sg, q, r)
    gain = np.linalg.solve(r + b_sg.T @ p @ b_sg, b_sg.T @ p @ ad)
    closed_loop = ad - b_sg @ gain
    absolute_closed_loop = np.abs(closed_loop)
    remainder = np.array((2e-6, 2e-6, 5e-6, 1e-5, 1e-5, 1e-5, 1e-5, 2e-6, 2e-6))
    radius = np.linalg.solve(np.eye(9) - absolute_closed_loop, remainder)
    invariance = absolute_closed_loop @ radius + remainder - radius
    equilibrium_state = np.r_[0.0, 0.0, 0.0, load, load, 0.0, 0.0]
    equilibrium_input = np.array((load[0], 0.0, load[1], 0.0))
    valve_margin = np.minimum(
        np.asarray(plant.parameters.valve_upper_pu) - load,
        load - np.asarray(plant.parameters.valve_lower_pu),
    ) - radius[3:5]
    mechanical_margin = np.minimum(
        np.asarray(plant.parameters.sg_power_upper_pu) - load,
        load - np.asarray(plant.parameters.sg_power_lower_pu),
    ) - radius[5:7]
    sg_input_margin = np.minimum(
        np.asarray(plant.parameters.valve_upper_pu) - load,
        load - np.asarray(plant.parameters.valve_lower_pu),
    ) - np.abs(gain) @ radius
    state_margin = float(min(np.min(valve_margin), np.min(mechanical_margin), 0.10 - np.max(radius[7:9])))
    input_margin = float(np.min(sg_input_margin))
    spectral = float(np.max(np.abs(np.linalg.eigvals(closed_loop))))
    absolute_spectral = float(np.max(np.abs(np.linalg.eigvals(absolute_closed_loop))))
    nonempty = bool(np.all(radius > 0.0) and np.all(np.isfinite(radius)))
    admissible = bool(
        nonempty
        and absolute_spectral < 1.0
        and np.max(invariance) <= 1e-12
        and state_margin > 0.0
        and input_margin > 0.0
    )
    return LocalRPICertificate(
        period_s=float(period_s),
        load_pu=load,
        equilibrium_state=equilibrium_state,
        equilibrium_input=equilibrium_input,
        terminal_feedback_gain=gain,
        error_box_radius=radius,
        additive_remainder_bound=remainder,
        closed_loop_spectral_radius=spectral,
        absolute_closed_loop_spectral_radius=absolute_spectral,
        invariance_residual=float(np.max(invariance)),
        minimum_state_margin_pu=state_margin,
        minimum_input_margin_pu=input_margin,
        nonempty=nonempty,
        admissible=admissible,
        claim_level="CONDITIONAL_LOCAL_LINEAR_RPI",
    )
