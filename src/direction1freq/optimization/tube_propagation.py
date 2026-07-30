"""Axis-aligned finite-horizon error-tube propagation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.linalg import solve_discrete_are


@dataclass(frozen=True, slots=True)
class ReachableTubeCertificate:
    feedback_gain: np.ndarray
    state_radii: np.ndarray
    input_radii: np.ndarray
    disturbance_radius: np.ndarray
    closed_loop_spectral_radius: float


def finite_horizon_reachable_tube(
    ad: np.ndarray, bd: np.ndarray, horizon: int,
    disturbance_radius: np.ndarray | None = None,
) -> ReachableTubeCertificate:
    """Build a conservative box tube for e+=Acl e+w."""

    n, m = ad.shape[0], bd.shape[1]
    q = np.diag([400.0, 400.0, 150.0, 5.0, 5.0, 20.0, 20.0, 20.0, 20.0])
    r = 4.0 * np.eye(m)
    riccati = solve_discrete_are(ad, bd, q, r)
    gain = -np.linalg.solve(r + bd.T @ riccati @ bd, bd.T @ riccati @ ad)
    closed = ad + bd @ gain
    spectral = float(np.max(np.abs(np.linalg.eigvals(closed))))
    disturbance = np.asarray(
        disturbance_radius if disturbance_radius is not None
        else [2e-5, 2e-5, 5e-5, 2e-4, 2e-4, 3e-4, 3e-4, 3e-4, 3e-4],
        dtype=float,
    )
    radii = np.zeros((n, horizon + 1))
    input_radii = np.zeros((m, horizon))
    for stage in range(horizon):
        input_radii[:, stage] = np.abs(gain) @ radii[:, stage]
        radii[:, stage + 1] = np.abs(closed) @ radii[:, stage] + disturbance
    return ReachableTubeCertificate(gain, radii, input_radii, disturbance, spectral)


def verify_box_tube(certificate: ReachableTubeCertificate, ad: np.ndarray, bd: np.ndarray) -> float:
    closed = ad + bd @ certificate.feedback_gain
    worst_violation = 0.0
    for stage in range(certificate.state_radii.shape[1] - 1):
        propagated = np.abs(closed) @ certificate.state_radii[:, stage] + certificate.disturbance_radius
        worst_violation = max(
            worst_violation,
            float(np.max(propagated - certificate.state_radii[:, stage + 1])),
        )
    return worst_violation
