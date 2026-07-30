"""Leakage-safe measurement model shared by deployed controllers."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True, slots=True)
class MeasurementModel:
    standard_deviation: float = 1e-4

    def measure(self, observable: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        return np.asarray(observable, dtype=float) + rng.normal(0.0, self.standard_deviation, size=np.asarray(observable).shape)
