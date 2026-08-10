"""A2 causal candidate-set and interval-MHE capability identification."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from direction5freq.estimation.deliverability_set_membership import (
    DeliverabilityFeasibleSetSnapshot,
    DeliverabilitySetMembership,
)
from direction5freq.estimation.deliverability_set_mhe import (
    DeliverabilitySetMHE,
    DeliverabilitySetSnapshot,
)
from direction5freq.models.capability_contract import CapabilityContract


@dataclass(frozen=True, slots=True)
class PassiveCapabilitySnapshot:
    candidate_set: DeliverabilityFeasibleSetSnapshot
    interval_set: DeliverabilitySetSnapshot
    samples: int


class PassiveCapabilityIdentifier:
    """Maintain both a finite model set and conservative capability intervals.

    Neither estimator receives true capability, true load, a future event, or a
    hidden mode.  The finite grid supplies auditable `(a,b,delay)` candidates and
    abrupt-change reset; the interval MHE supplies outer power/ramp/delay sets.
    """

    def __init__(
        self,
        contract: CapabilityContract,
        dt_s: float,
        *,
        window_s: float = 24.0,
        residual_bound_pu: float = 0.0025,
    ) -> None:
        self.grid = DeliverabilitySetMembership(
            contract,
            dt_s,
            window_samples=max(8, int(round(window_s / dt_s))),
            residual_bound_pu=residual_bound_pu,
        )
        self.mhe = DeliverabilitySetMHE(
            contract,
            dt_s,
            window_s=window_s,
            residual_bound_pu=residual_bound_pu,
        )

    def update(
        self,
        time_s: float,
        requested_total_power_pu: np.ndarray,
        actual_poi_power_pu: np.ndarray,
    ) -> PassiveCapabilitySnapshot:
        grid = self.grid.update(time_s, requested_total_power_pu, actual_poi_power_pu)
        if grid.change_reset.any():
            self.mhe.reset_online_evidence()
            interval = self.mhe.update(time_s, requested_total_power_pu, actual_poi_power_pu)
        else:
            interval = self.mhe.update(time_s, requested_total_power_pu, actual_poi_power_pu)
        return PassiveCapabilitySnapshot(grid, interval, interval.samples)


def interval_contains_truth(
    snapshot: DeliverabilitySetSnapshot,
    *,
    positive_power_pu: np.ndarray,
    negative_power_pu: np.ndarray,
    ramp_up_pu_per_s: np.ndarray,
    ramp_down_pu_per_s: np.ndarray,
    delay_s: np.ndarray,
) -> tuple[bool, bool, bool]:
    power = bool(
        np.all((positive_power_pu >= snapshot.upper_power_capability_interval_pu[:, 0])
               & (positive_power_pu <= snapshot.upper_power_capability_interval_pu[:, 1]))
        and np.all((negative_power_pu >= snapshot.lower_power_capability_interval_pu[:, 0])
                   & (negative_power_pu <= snapshot.lower_power_capability_interval_pu[:, 1]))
    )
    ramp = bool(
        np.all((ramp_up_pu_per_s >= snapshot.ramp_up_capability_interval_pu_per_s[:, 0])
               & (ramp_up_pu_per_s <= snapshot.ramp_up_capability_interval_pu_per_s[:, 1]))
        and np.all((ramp_down_pu_per_s >= snapshot.ramp_down_capability_interval_pu_per_s[:, 0])
                   & (ramp_down_pu_per_s <= snapshot.ramp_down_capability_interval_pu_per_s[:, 1]))
    )
    delay = bool(np.all(
        (delay_s >= snapshot.delay_interval_s[:, 0])
        & (delay_s <= snapshot.delay_interval_s[:, 1])
    ))
    return power, ramp, delay


__all__ = [
    "PassiveCapabilityIdentifier", "PassiveCapabilitySnapshot",
    "interval_contains_truth",
]

