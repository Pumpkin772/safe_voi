"""Causal vector observation tubes for actual BESS POI power."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np


@dataclass(frozen=True)
class VectorObservationTube:
    candidate_id: str
    lower: np.ndarray
    upper: np.ndarray

    def __post_init__(self) -> None:
        lower = np.asarray(self.lower, dtype=float)
        upper = np.asarray(self.upper, dtype=float)
        if lower.ndim != 2 or lower.shape != upper.shape:
            raise ValueError("observation tubes must be time-by-channel matrices")
        if not np.all(np.isfinite(lower)) or not np.all(np.isfinite(upper)):
            raise ValueError("observation tube must be finite")
        if np.any(lower > upper):
            raise ValueError("tube lower bound exceeds upper bound")
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)

    def contains(self, observed: np.ndarray, tolerance: float = 0.0) -> bool:
        value = np.asarray(observed, dtype=float)
        if value.shape != self.lower.shape:
            raise ValueError("observation shape does not match registered tube")
        return bool(np.all(value >= self.lower - tolerance) and np.all(value <= self.upper + tolerance))

    def overlaps(self, other: "VectorObservationTube") -> bool:
        if self.lower.shape != other.lower.shape:
            raise ValueError("tube shapes differ")
        return bool(np.all(np.maximum(self.lower, other.lower) <= np.minimum(self.upper, other.upper)))


def causal_posterior(
    tubes: Mapping[str, VectorObservationTube],
    observed_actual_poi_power: np.ndarray,
    tolerance: float = 0.0,
) -> frozenset[str]:
    """Retain every hypothesis consistent with the observed causal trace."""

    posterior = frozenset(
        candidate_id
        for candidate_id, tube in tubes.items()
        if tube.contains(observed_actual_poi_power, tolerance=tolerance)
    )
    return posterior


def pairwise_distinguishable_fraction(
    tubes: Mapping[str, VectorObservationTube],
) -> float:
    values = list(tubes.values())
    if len(values) < 2:
        return 0.0
    pairs = 0
    distinguished = 0
    for index, left in enumerate(values):
        for right in values[index + 1:]:
            pairs += 1
            distinguished += int(not left.overlaps(right))
    return distinguished / pairs
