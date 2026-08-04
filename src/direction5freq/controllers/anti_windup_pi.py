"""Deployable anti-windup PI baselines."""

from __future__ import annotations

import numpy as np

from direction5freq.models.plant_a_full import PublicObservation


class _AntiWindupPI:
    is_true_rolling_mpc = False

    def __init__(
        self,
        period_s: float,
        allocation: tuple[float, float],
        *,
        kp: float = 0.42,
        ki: float = 0.025,
        kaw: float = 0.65,
        total_limit_pu: float = 0.12,
    ) -> None:
        self.period_s = float(period_s)
        self.allocation = np.asarray(allocation, dtype=float)
        self.kp = float(kp)
        self.ki = float(ki)
        self.kaw = float(kaw)
        self.total_limit = float(total_limit_pu)
        self.integral = np.zeros(2)
        self.saturation_count = 0

    def propose(self, observation: PublicObservation) -> np.ndarray:
        error = np.asarray(observation.ace_pu, dtype=float)
        candidate_integral = self.integral + self.period_s * error
        unsaturated = -self.kp * error - self.ki * candidate_integral
        total = np.clip(unsaturated, -self.total_limit, self.total_limit)
        saturated = np.abs(total - unsaturated) > 1e-12
        self.saturation_count += int(np.any(saturated))
        if self.ki > 0:
            # The controller uses the negative-feedback convention
            # ``u = -kp * e - ki * integral``.  Consequently the usual
            # back-calculation term has the opposite sign in the integral
            # state: a clipped negative command must *decrease* the positive
            # integral that caused the clipping.
            candidate_integral -= self.kaw * (total - unsaturated) / self.ki
        self.integral = candidate_integral
        return np.array((
            self.allocation[0] * total[0], self.allocation[1] * total[0],
            self.allocation[0] * total[1], self.allocation[1] * total[1],
        ))


class SGOnlyAntiWindupPI(_AntiWindupPI):
    name = "sg_only_anti_windup_pi"

    def __init__(self, period_s: float, **kwargs) -> None:
        super().__init__(period_s, (1.0, 0.0), **kwargs)


class FixedAllocationAntiWindupPI(_AntiWindupPI):
    name = "fixed_allocation_anti_windup_pi"

    def __init__(self, period_s: float, **kwargs) -> None:
        super().__init__(period_s, (0.75, 0.25), **kwargs)


__all__ = ["SGOnlyAntiWindupPI", "FixedAllocationAntiWindupPI"]
