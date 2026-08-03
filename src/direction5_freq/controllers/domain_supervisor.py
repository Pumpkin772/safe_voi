"""Causal sustainable/bridge/infeasible routing for DCSV-MPC."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from direction5_freq.models.sustainability_classifier import (
    CapabilityContract,
    DomainResult,
    classify_physical_domain,
)


@dataclass(frozen=True, slots=True)
class DomainDecision:
    classification: str
    certificate_kind: str
    result: DomainResult
    ordinary_information_only: bool


class DomainSupervisor:
    """Classify from estimated load and guaranteed capability-set bounds."""

    def __init__(
        self,
        period_s: float,
        plant: str = "A",
        sg_reserve_pu: float = 0.10,
        slow_reserve_arrival_s: float | None = 60.0,
    ) -> None:
        self.period_s = float(period_s)
        self.plant = str(plant)
        self.sg_reserve = float(sg_reserve_pu)
        self.tie_limit = 0.08 if self.plant == "A" else 0.06
        self.slow_reserve_arrival_s = slow_reserve_arrival_s

    def classify(
        self,
        load_estimate_pu: np.ndarray,
        contract: CapabilityContract,
    ) -> DomainDecision:
        arrival = (
            float(self.slow_reserve_arrival_s)
            if self.slow_reserve_arrival_s is not None
            else 3600.0
        )
        additional = (
            np.array([0.08, 0.08])
            if self.slow_reserve_arrival_s is not None
            else np.zeros(2)
        )
        result = classify_physical_domain(
            np.asarray(load_estimate_pu, dtype=float),
            self.sg_reserve,
            self.tie_limit,
            contract,
            self.period_s,
            arrival,
            additional,
        )
        if result.classification == "SUSTAINABLE":
            certificate = "SUSTAINABLE_TERMINAL_REQUIRED"
        elif result.classification == "BRIDGE_ONLY":
            certificate = (
                "FINITE_ENERGY_BRIDGE_TO_REGISTERED_SLOW_RESERVE"
                if self.slow_reserve_arrival_s is not None
                else "FINITE_HORIZON_BRIDGE_ONLY_NO_RECURSIVE_CLAIM"
            )
        else:
            certificate = "PHYSICAL_INFEASIBILITY_CERTIFICATE"
        return DomainDecision(result.classification, certificate, result, True)
