"""Information accumulation over non-overlapping causal observation windows."""

from __future__ import annotations

from math import ceil, sqrt

from scipy.stats import norm


def equal_prior_binary_error(
    separation_sigma_per_window: float,
    independent_windows: int,
) -> float:
    combined = separation_sigma_per_window * sqrt(independent_windows)
    return float(norm.cdf(-0.5 * combined))


def windows_for_error(
    separation_sigma_per_window: float,
    target_error: float = 0.01,
) -> int:
    required_separation = -2.0 * float(norm.ppf(target_error))
    return int(ceil((required_separation / separation_sigma_per_window) ** 2))
