"""Public stochastic continuation paths for the online information-value gate."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class ContinuationBankConfig:
    integration_seeds: tuple[int, ...] = (
        57001, 57002, 57003, 57004, 57005, 57006, 57007, 57008,
    )
    event_time_window_s: tuple[float, float] = (210.0, 390.0)
    event_magnitude_range_pu: tuple[float, float] = (0.025, 0.050)
    regulation_time_constant_s: float = 60.0
    regulation_stationary_std_pu: float = 0.012
    regulation_hard_bound_pu: float = 0.020
    regulation_area_correlation: float = 0.4
    total_load_bound_pu: float = 0.070


SCREEN_CONTINUATION_CONFIG = ContinuationBankConfig(
    integration_seeds=(57101, 57102, 57103, 57104),
)


def _contingency_vector(magnitude: float, sign: int, area: str) -> np.ndarray:
    signed = float(sign) * float(magnitude)
    if area == "area0":
        return np.asarray((signed, 0.25 * signed))
    if area == "area1":
        return np.asarray((0.25 * signed, signed))
    return np.asarray((signed, 0.65 * signed))


def registered_continuation_load_bank(
    *,
    current_time_s: float,
    current_load_estimate_pu: np.ndarray,
    period_s: float,
    duration_s: float,
    config: ContinuationBankConfig = ContinuationBankConfig(),
) -> np.ndarray:
    """Return common-random-number paths from the registered public law.

    The fixed integration seeds are outside all episode seed ranges.  They are
    numerical integration nodes, not the current episode's future realization.
    A load estimate outside the registered OU-only bound causally establishes
    that the persistent event component has already arrived; otherwise each
    integration path retains its independently drawn event time.
    """

    current_load = np.asarray(current_load_estimate_pu, dtype=float)
    steps = int(np.floor(duration_s / period_s + 1e-10))
    paths = np.zeros((len(config.integration_seeds), steps, 2), dtype=float)
    phi = float(np.exp(-period_s / config.regulation_time_constant_s))
    innovation_std = (
        config.regulation_stationary_std_pu * np.sqrt(1.0 - phi * phi)
    )
    correlation = np.asarray((
        (1.0, config.regulation_area_correlation),
        (config.regulation_area_correlation, 1.0),
    ))
    cholesky = np.linalg.cholesky(correlation)
    event_is_observed = bool(
        np.max(np.abs(current_load))
        > config.regulation_hard_bound_pu + 1e-8
    )

    for path_index, seed in enumerate(config.integration_seeds):
        timing_rng, event_rng, regulation_rng = (
            np.random.default_rng(child)
            for child in np.random.SeedSequence(seed).spawn(3)
        )
        event_time = float(timing_rng.uniform(*config.event_time_window_s))
        magnitude = float(event_rng.uniform(*config.event_magnitude_range_pu))
        sign = int(event_rng.choice((-1, 1)))
        area = str(event_rng.choice(("area0", "area1", "both")))
        event_vector = _contingency_vector(magnitude, sign, area)

        event_has_arrived = bool(event_is_observed or event_time <= current_time_s)
        persistent = current_load.copy() if event_has_arrived else np.zeros(2)
        regulation = (
            np.zeros(2)
            if event_has_arrived
            else np.clip(
                current_load,
                -config.regulation_hard_bound_pu,
                config.regulation_hard_bound_pu,
            )
        )
        for step in range(steps):
            regulation = np.clip(
                phi * regulation
                + innovation_std * (cholesky @ regulation_rng.normal(size=2)),
                -config.regulation_hard_bound_pu,
                config.regulation_hard_bound_pu,
            )
            time_s = current_time_s + (step + 1) * period_s
            if not event_has_arrived and time_s + 1e-10 >= event_time:
                persistent = event_vector
                event_has_arrived = True
            paths[path_index, step] = np.clip(
                persistent + regulation,
                -config.total_load_bound_pu,
                config.total_load_bound_pu,
            )
    return paths


__all__ = [
    "ContinuationBankConfig",
    "SCREEN_CONTINUATION_CONFIG",
    "registered_continuation_load_bank",
]
