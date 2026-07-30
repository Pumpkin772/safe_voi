"""A genuine discrete finite-state LQI baseline for the Phase-E nominal model."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.linalg import solve_discrete_are
from scipy.signal import cont2discrete

from direction1freq.models.plant_a_v2 import PublicObservationV2, TwoAreaPlantAV2


@dataclass(frozen=True, slots=True)
class LQIDesign:
    gain: np.ndarray
    closed_loop_spectral_radius: float
    discrete_a: np.ndarray
    discrete_b: np.ndarray
    augmented_a: np.ndarray
    augmented_b: np.ndarray


def design_discrete_lqi(
    plant: TwoAreaPlantAV2, period_s: float, sg_fraction: float = 0.70,
    nominal_delay_s: float = 0.20,
) -> LQIDesign:
    if not 0.0 <= nominal_delay_s < period_s:
        raise ValueError("nominal delay must be shorter than the supervisory period")
    a, b, c_ace, _ = plant.linear_continuous_model(sg_fraction)
    dummy_c = np.zeros((1, a.shape[0]))
    dummy_d = np.zeros((1, b.shape[1]))
    ad, bd, _, _, _ = cont2discrete((a, b, dummy_c, dummy_d), period_s, method="zoh")
    _, b_current, _, _, _ = cont2discrete(
        (a, b, dummy_c, dummy_d), period_s - nominal_delay_s, method="zoh"
    )
    b_previous = bd - b_current
    n = ad.shape[0]
    p = c_ace.shape[0]
    # Augmented state: plant, ACE integral, previous total command.  The latter
    # is the exact one-step memory required by the within-period nominal delay.
    a_aug = np.block([
        [ad, np.zeros((n, p)), b_previous],
        [period_s * c_ace, np.eye(p), np.zeros((p, p))],
        [np.zeros((p, n)), np.zeros((p, p)), np.zeros((p, p))],
    ])
    b_aug = np.vstack((b_current, np.zeros((p, p)), np.eye(p)))
    q = np.diag([
        2000.0, 2000.0, 300.0, 2.0, 2.0, 20.0, 20.0, 8.0, 8.0,
        20.0, 20.0, 1.0, 1.0,
    ])
    # The supervisory action is deliberately penalized relative to fast local
    # PFR.  A weaker penalty reproduced the Phase-D failure mode under 4 s ZOH:
    # repeated command saturation excited a slow limit cycle for 0.05--0.08 pu
    # load steps even though the unsaturated linear poles were stable.
    r = np.eye(2) * 2000.0
    solution = solve_discrete_are(a_aug, b_aug, q, r)
    gain = np.linalg.solve(r + b_aug.T @ solution @ b_aug, b_aug.T @ solution @ a_aug)
    radius = float(np.max(np.abs(np.linalg.eigvals(a_aug - b_aug @ gain))))
    return LQIDesign(gain, radius, np.asarray(ad), np.asarray(bd), a_aug, b_aug)


class DiscreteLQIBaseline:
    """Deployable LQI shell consuming a causal state estimate, never plant truth."""

    def __init__(
        self, design: LQIDesign, period_s: float, sg_fraction: float = 0.70,
        total_limit_pu: float = 0.20, anti_windup_gain: float = 0.5,
    ) -> None:
        self.design = design
        self.period_s = float(period_s)
        self.sg_fraction = float(sg_fraction)
        self.total_limit_pu = float(total_limit_pu)
        self.anti_windup_gain = float(anti_windup_gain)
        self.ace_integral = np.zeros(2)
        self.previous_total = np.zeros(2)

    def reset(self) -> None:
        self.ace_integral = np.zeros(2)
        self.previous_total = np.zeros(2)

    def update(
        self, observation: PublicObservationV2, estimated_linear_state: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        estimate = np.asarray(estimated_linear_state, dtype=float)
        if estimate.shape != (9,):
            raise ValueError("estimated_linear_state must follow the documented nine-state model")
        candidate_integral = self.ace_integral + self.period_s * np.asarray(observation.ace_pu)
        raw = -self.design.gain @ np.r_[estimate, candidate_integral, self.previous_total]
        total = np.clip(raw, -self.total_limit_pu, self.total_limit_pu)
        # Back-calculate only the integral states through their local gain sign.
        correction = self.anti_windup_gain * (total - raw)
        integral_gain = np.diag(self.design.gain[:, 9:11])
        safe_gain = np.where(np.abs(integral_gain) > 1e-8, integral_gain, 1.0)
        self.ace_integral = candidate_integral - correction / safe_gain
        self.previous_total = total.copy()
        sg = self.sg_fraction * total
        bess = (1.0 - self.sg_fraction) * total
        command = np.array([sg[0], bess[0], sg[1], bess[1]])
        return command, {"raw_total_pu": raw, "total_pu": total, "ace_integral": self.ace_integral.copy()}
