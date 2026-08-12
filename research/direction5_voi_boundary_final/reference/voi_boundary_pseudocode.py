"""Pseudocode-level reference for exact registered VoI evaluation.

This is not a complete optimization implementation.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Hashable, Iterable


@dataclass(frozen=True)
class ValueResult:
    baseline_cost: float
    perfect_information_cost: float
    probe_cost: float
    posterior_cost: float
    net_value: float
    safe: bool


def no_probe_upper_bound(baseline_cost: float, probe_perfect_information_lower_cost: float) -> float:
    """Upper bound on any causal post-probe improvement."""
    return float(baseline_cost - probe_perfect_information_lower_cost)


def net_probe_value(baseline_cost: float, full_probe_and_posterior_cost: float) -> float:
    return float(baseline_cost - full_probe_and_posterior_cost)


def select_probe(results: dict[Hashable, ValueResult], margin: float = 0.0):
    safe = {
        key: value
        for key, value in results.items()
        if value.safe and value.net_value > margin
    }
    if not safe:
        return None
    return max(safe, key=lambda key: safe[key].net_value)


def posterior_set(candidate_outputs: dict[Hashable, object], observed_output, overlap_test):
    return frozenset(
        candidate
        for candidate, output_tube in candidate_outputs.items()
        if overlap_test(output_tube, observed_output)
    )
