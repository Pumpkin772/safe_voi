"""Break-even value boundary for an explicit binary capability prior."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BinaryPriorValueBoundary:
    low_capability_net_value: float
    high_capability_net_value: float

    def net_value(self, high_capability_probability: float) -> float:
        probability = float(high_capability_probability)
        return (
            (1.0 - probability) * self.low_capability_net_value
            + probability * self.high_capability_net_value
        )

    def break_even_probability(self) -> float | None:
        slope = self.high_capability_net_value - self.low_capability_net_value
        if slope <= 0.0:
            return None
        return max(0.0, min(1.0, -self.low_capability_net_value / slope))

    def worst_value_over_prior_interval(self, lower: float, upper: float) -> float:
        return min(self.net_value(lower), self.net_value(upper))
