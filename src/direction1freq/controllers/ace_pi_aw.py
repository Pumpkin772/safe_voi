"""Stable sampled ACE PI with explicit back-calculation anti-windup."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import cont2discrete

from direction1freq.models.plant_a_v2 import PublicObservationV2, TwoAreaPlantAV2


@dataclass(frozen=True, slots=True)
class PIControllerDiagnostics:
    ace_pu: np.ndarray
    unsaturated_total_pu: np.ndarray
    saturated_total_pu: np.ndarray
    integral_action_pu: np.ndarray
    anti_windup_correction_pu: np.ndarray


def _zoh(a: np.ndarray, b: np.ndarray, period_s: float) -> tuple[np.ndarray, np.ndarray]:
    c_dummy = np.zeros((1, a.shape[0]))
    d_dummy = np.zeros((1, b.shape[1]))
    ad, bd, _, _, _ = cont2discrete((a, b, c_dummy, d_dummy), period_s, method="zoh")
    return np.asarray(ad), np.asarray(bd)


def delayed_sampled_closed_loop_matrix(
    plant: TwoAreaPlantAV2,
    period_s: float,
    proportional_gain: float,
    integral_gain_per_s: float,
    sg_fraction: float = 0.70,
    nominal_delay_s: float = 0.20,
) -> np.ndarray:
    """Exact ZOH matrix with a fractional-period input-delay memory.

    State is ``[plant x, integral action i, previous total command q]`` and
    ``u_k=-Kp*ACE_k+i_k``.  The first delay seconds use ``q_k``; the remaining
    interval uses ``u_k``.
    """

    if not 0.0 <= nominal_delay_s < period_s:
        raise ValueError("nominal delay must be shorter than the supervisory period")
    a, b, c, _ = plant.linear_continuous_model(sg_fraction)
    ad, bd = _zoh(a, b, period_s)
    _, b_current = _zoh(a, b, period_s - nominal_delay_s)
    b_previous = bd - b_current
    n = a.shape[0]
    p = b.shape[1]
    closed = np.zeros((n + 2 * p, n + 2 * p))
    closed[:n, :n] = ad - b_current @ (proportional_gain * c)
    closed[:n, n : n + p] = b_current
    closed[:n, n + p :] = b_previous
    closed[n : n + p, :n] = -integral_gain_per_s * period_s * c
    closed[n : n + p, n : n + p] = np.eye(p)
    closed[n + p :, :n] = -proportional_gain * c
    closed[n + p :, n : n + p] = np.eye(p)
    return closed


def design_stable_pi(
    plant: TwoAreaPlantAV2,
    period_s: float,
    nominal_delay_s: float = 0.20,
    sg_fraction: float = 0.70,
) -> tuple[float, float, float]:
    """Select a preregistered grid point by minimum unsaturated spectral radius."""

    best: tuple[float, float, float] | None = None
    for proportional in np.geomspace(1e-4, 0.08, 48):
        for integral in np.geomspace(2e-5, 5e-2, 48):
            matrix = delayed_sampled_closed_loop_matrix(
                plant, period_s, float(proportional), float(integral), sg_fraction, nominal_delay_s
            )
            radius = float(np.max(np.abs(np.linalg.eigvals(matrix))))
            candidate = (radius, float(proportional), float(integral))
            if best is None or candidate < best:
                best = candidate
    assert best is not None
    radius, proportional, integral = best
    return proportional, integral, radius


class ACEPIAntiWindup:
    """Deployable ACE PI using only the public observation contract."""

    def __init__(
        self,
        period_s: float,
        proportional_gain: float,
        integral_gain_per_s: float,
        sg_fraction: float = 0.70,
        total_lower_pu: tuple[float, float] = (-0.20, -0.20),
        total_upper_pu: tuple[float, float] = (0.20, 0.20),
        anti_windup_gain: float = 0.5,
    ) -> None:
        self.period_s = float(period_s)
        self.proportional_gain = float(proportional_gain)
        self.integral_gain_per_s = float(integral_gain_per_s)
        self.sg_fraction = float(sg_fraction)
        self.total_lower_pu = np.asarray(total_lower_pu, dtype=float)
        self.total_upper_pu = np.asarray(total_upper_pu, dtype=float)
        self.anti_windup_gain = float(anti_windup_gain)
        self.integral_action_pu = np.zeros(2)

    def reset(self) -> None:
        self.integral_action_pu = np.zeros(2)

    def update(self, observation: PublicObservationV2) -> tuple[np.ndarray, PIControllerDiagnostics]:
        ace = np.asarray(observation.ace_pu, dtype=float)
        candidate_integral = self.integral_action_pu - self.integral_gain_per_s * self.period_s * ace
        unsaturated = -self.proportional_gain * ace + candidate_integral
        saturated = np.minimum(np.maximum(unsaturated, self.total_lower_pu), self.total_upper_pu)
        correction = self.anti_windup_gain * (saturated - unsaturated)
        self.integral_action_pu = candidate_integral + correction
        sg = self.sg_fraction * saturated
        bess = (1.0 - self.sg_fraction) * saturated
        command = np.array([sg[0], bess[0], sg[1], bess[1]])
        return command, PIControllerDiagnostics(
            ace_pu=ace.copy(), unsaturated_total_pu=unsaturated,
            saturated_total_pu=saturated, integral_action_pu=self.integral_action_pu.copy(),
            anti_windup_correction_pu=correction,
        )
