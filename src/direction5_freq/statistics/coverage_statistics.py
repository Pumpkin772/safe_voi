"""Exact finite-sample coverage summaries."""

from __future__ import annotations

from scipy.stats import beta


def one_sided_binomial_lower_bound(
    successes: int, samples: int, confidence: float = 0.95
) -> float:
    """Return the exact one-sided Clopper--Pearson lower bound."""

    if samples <= 0 or not 0 <= successes <= samples:
        raise ValueError("require 0 <= successes <= samples and samples > 0")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be strictly between zero and one")
    if successes == 0:
        return 0.0
    return float(beta.ppf(1.0 - confidence, successes, samples - successes + 1))
