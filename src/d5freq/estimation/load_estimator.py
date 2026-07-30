"""Causal random-walk unknown-input estimator; never reads true load."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass
class LoadEstimator:
    gain: float = 0.08
    estimate_pu: np.ndarray | None = None

    def update(self, ace_pu: np.ndarray) -> np.ndarray:
        if self.estimate_pu is None:
            self.estimate_pu = np.zeros_like(np.asarray(ace_pu, dtype=float))
        self.estimate_pu = self.estimate_pu + self.gain * np.asarray(ace_pu, dtype=float)
        return self.estimate_pu.copy()
