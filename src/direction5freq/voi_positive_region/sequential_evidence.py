"""Information accumulation over non-overlapping causal observation windows."""

from __future__ import annotations

from math import ceil, sqrt

from scipy.stats import norm
import numpy as np


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


def effective_windows_ar1(windows: int, correlation: float) -> float:
    return float(windows * (1.0 - correlation) / (1.0 + correlation))


def windows_for_error_ar1(
    separation_sigma_per_window: float,
    correlation: float,
    target_error: float = 0.01,
) -> int:
    independent = windows_for_error(separation_sigma_per_window, target_error)
    return int(ceil(independent * (1.0 + correlation) / (1.0 - correlation)))


def stacked_mahalanobis_separation(
    low_mean: np.ndarray,
    high_mean: np.ndarray,
    covariance: np.ndarray,
) -> float:
    difference = np.asarray(high_mean, dtype=float) - np.asarray(low_mean, dtype=float)
    return float(np.sqrt(difference @ np.linalg.solve(covariance, difference)))


def stacked_equal_prior_error(
    low_mean: np.ndarray,
    high_mean: np.ndarray,
    covariance: np.ndarray,
) -> float:
    separation = stacked_mahalanobis_separation(low_mean, high_mean, covariance)
    return float(norm.cdf(-0.5 * separation))
