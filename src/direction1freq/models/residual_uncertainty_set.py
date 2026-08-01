"""Development-calibrated finite-horizon model-error envelope."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class ResidualUncertaintySet:
    horizons: tuple[int, ...]
    component_radii: np.ndarray
    calibration_split: str
    quantile: float
    finite_sample_inflation: float
    delay_hull_remainder: np.ndarray

    def __post_init__(self) -> None:
        radii = np.asarray(self.component_radii, dtype=float)
        if radii.ndim != 2 or radii.shape[0] != len(self.horizons):
            raise ValueError("one component-radius row is required per horizon")
        if np.any(radii < 0.0) or not np.all(np.isfinite(radii)):
            raise ValueError("residual radii must be finite and nonnegative")
        object.__setattr__(self, "component_radii", radii.copy())
        remainder = np.asarray(self.delay_hull_remainder, dtype=float)
        if remainder.shape != (radii.shape[1],):
            raise ValueError("delay remainder must match state dimension")
        object.__setattr__(self, "delay_hull_remainder", remainder.copy())

    def radius(self, horizon: int) -> np.ndarray:
        return self.component_radii[self.horizons.index(int(horizon))].copy()

    def contains(self, residual: np.ndarray, horizon: int) -> bool:
        return bool(
            np.all(np.abs(np.asarray(residual, dtype=float)) <= self.radius(horizon))
        )

