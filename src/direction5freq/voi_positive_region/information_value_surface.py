"""Prior-lifetime value surface for opportunistic capability certification."""

from __future__ import annotations

from dataclasses import dataclass

from .prior_value_boundary import BinaryPriorValueBoundary


@dataclass(frozen=True)
class OpportunityValuePoint:
    amplitude_pu: float
    evidence_window_s: float
    windows_to_certify: int
    information_validity_s: float
    low_acquisition_control_value: float
    high_acquisition_control_value: float
    low_information_value_per_s: float
    high_information_value_per_s: float
    physical_safe: bool

    @property
    def certification_time_s(self) -> float:
        return self.evidence_window_s * self.windows_to_certify

    @property
    def useful_information_time_s(self) -> float:
        return max(0.0, self.information_validity_s - self.certification_time_s)

    @property
    def low_total_value(self) -> float:
        return (
            self.low_acquisition_control_value
            + self.useful_information_time_s * self.low_information_value_per_s
        )

    @property
    def high_total_value(self) -> float:
        return (
            self.high_acquisition_control_value
            + self.useful_information_time_s * self.high_information_value_per_s
        )

    @property
    def prior_boundary(self) -> BinaryPriorValueBoundary:
        return BinaryPriorValueBoundary(self.low_total_value, self.high_total_value)

    def admissible(self, low_capability_downside_limit: float) -> bool:
        return bool(
            self.physical_safe
            and self.certification_time_s < self.information_validity_s
            and self.low_total_value >= -low_capability_downside_limit
        )

    def ambiguity_value(self, prior_lower: float, prior_upper: float) -> float:
        return self.prior_boundary.worst_value_over_prior_interval(
            prior_lower, prior_upper
        )


def select_opportunity(
    candidates: list[OpportunityValuePoint],
    *,
    prior_lower: float,
    prior_upper: float,
    low_capability_downside_limit: float,
) -> OpportunityValuePoint | None:
    admissible = [
        candidate
        for candidate in candidates
        if candidate.admissible(low_capability_downside_limit)
        and candidate.ambiguity_value(prior_lower, prior_upper) > 0.0
    ]
    return max(
        admissible,
        key=lambda candidate: candidate.ambiguity_value(prior_lower, prior_upper),
        default=None,
    )
