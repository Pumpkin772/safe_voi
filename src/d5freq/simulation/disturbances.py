"""Simulator-side load events and reproducible sampled disturbances."""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np
from numpy.typing import NDArray


def _finite(value: float, name: str) -> float:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


@dataclass(frozen=True, slots=True)
class LoadEvent:
    """A load increment active on ``[start_time_s, end_time_s)``.

    Omitting ``end_time_s`` creates a permanent step. Positive magnitude means
    an increase in net load and therefore a negative frequency tendency.
    """

    start_time_s: float
    magnitude_pu: float
    end_time_s: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "start_time_s", _finite(self.start_time_s, "start_time_s")
        )
        object.__setattr__(
            self, "magnitude_pu", _finite(self.magnitude_pu, "magnitude_pu")
        )
        if self.start_time_s < 0.0:
            raise ValueError("start_time_s must be non-negative")
        if self.end_time_s is not None:
            end = _finite(self.end_time_s, "end_time_s")
            if end <= self.start_time_s:
                raise ValueError("end_time_s must be greater than start_time_s")
            object.__setattr__(self, "end_time_s", end)

    def value_at(self, time_s: float) -> float:
        time = _finite(time_s, "time_s")
        if time < 0.0:
            raise ValueError("time_s must be non-negative")
        active = time >= self.start_time_s and (
            self.end_time_s is None or time < self.end_time_s
        )
        return self.magnitude_pu if active else 0.0


@dataclass(frozen=True, slots=True)
class SampledLoadNoise:
    """Zero-order-held random load samples with query-order independence."""

    sample_period_s: float
    samples_pu: NDArray[np.float64] = field(repr=False)

    def __post_init__(self) -> None:
        period = _finite(self.sample_period_s, "sample_period_s")
        if period <= 0.0:
            raise ValueError("sample_period_s must be positive")
        samples = np.asarray(self.samples_pu, dtype=float)
        if samples.ndim != 1 or samples.size == 0:
            raise ValueError("samples_pu must be a non-empty one-dimensional array")
        if not np.all(np.isfinite(samples)):
            raise ValueError("samples_pu must contain only finite values")
        owned = samples.copy()
        owned.setflags(write=False)
        object.__setattr__(self, "sample_period_s", period)
        object.__setattr__(self, "samples_pu", owned)

    @classmethod
    def from_seed(
        cls,
        *,
        seed: int,
        duration_s: float,
        sample_period_s: float,
        white_std_pu: float = 0.0,
        random_walk_step_std_pu: float = 0.0,
    ) -> "SampledLoadNoise":
        duration = _finite(duration_s, "duration_s")
        period = _finite(sample_period_s, "sample_period_s")
        white_std = _finite(white_std_pu, "white_std_pu")
        walk_std = _finite(
            random_walk_step_std_pu, "random_walk_step_std_pu"
        )
        if duration < 0.0:
            raise ValueError("duration_s must be non-negative")
        if period <= 0.0:
            raise ValueError("sample_period_s must be positive")
        if white_std < 0.0 or walk_std < 0.0:
            raise ValueError("noise standard deviations must be non-negative")
        if isinstance(seed, bool) or int(seed) != seed or int(seed) < 0:
            raise ValueError("seed must be a non-negative integer")

        count = math.floor(duration / period) + 1
        rng = np.random.default_rng(int(seed))
        white = rng.normal(0.0, white_std, size=count)
        walk = np.zeros(count, dtype=float)
        if count > 1 and walk_std > 0.0:
            walk[1:] = np.cumsum(rng.normal(0.0, walk_std, size=count - 1))
        return cls(period, white + walk)

    def value_at(self, time_s: float) -> float:
        time = _finite(time_s, "time_s")
        if time < 0.0:
            raise ValueError("time_s must be non-negative")
        index = min(int(math.floor(time / self.sample_period_s)), self.samples_pu.size - 1)
        return float(self.samples_pu[index])

    def transition_times_between(
        self, start_time_s: float, end_time_s: float
    ) -> tuple[float, ...]:
        """Return held-sample changes in the half-open interval ``(start, end]``."""

        start = _finite(start_time_s, "start_time_s")
        end = _finite(end_time_s, "end_time_s")
        if start < 0.0 or end < start:
            raise ValueError("noise interval must satisfy 0 <= start <= end")
        first_index = math.floor(start / self.sample_period_s) + 1
        last_index = min(
            math.floor(end / self.sample_period_s), self.samples_pu.size - 1
        )
        return tuple(
            index * self.sample_period_s
            for index in range(first_index, last_index + 1)
            if start < index * self.sample_period_s <= end
        )


@dataclass(frozen=True, slots=True)
class LoadDisturbance:
    """Realized net-load trajectory combining deterministic and random terms."""

    base_pu: float = 0.0
    events: tuple[LoadEvent, ...] = ()
    noise: SampledLoadNoise | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_pu", _finite(self.base_pu, "base_pu"))
        object.__setattr__(self, "events", tuple(self.events))

    def value_at(self, time_s: float) -> float:
        value = self.base_pu + sum(event.value_at(time_s) for event in self.events)
        if self.noise is not None:
            value += self.noise.value_at(time_s)
        return float(value)

    def transition_times_between(
        self, start_time_s: float, end_time_s: float
    ) -> tuple[float, ...]:
        """Return all discontinuity times in ``(start, end]``."""

        start = _finite(start_time_s, "start_time_s")
        end = _finite(end_time_s, "end_time_s")
        if start < 0.0 or end < start:
            raise ValueError("disturbance interval must satisfy 0 <= start <= end")
        transitions = {
            boundary
            for event in self.events
            for boundary in (event.start_time_s, event.end_time_s)
            if boundary is not None and start < boundary <= end
        }
        if self.noise is not None:
            transitions.update(self.noise.transition_times_between(start, end))
        return tuple(sorted(transitions))


@dataclass(frozen=True, slots=True)
class LoadDisturbanceSpec:
    """Seed-independent recipe realized by a simulator during ``reset``."""

    base_pu: float = 0.0
    events: tuple[LoadEvent, ...] = ()
    sample_period_s: float = 0.5
    white_noise_std_pu: float = 0.0
    random_walk_step_std_pu: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_pu", _finite(self.base_pu, "base_pu"))
        object.__setattr__(self, "events", tuple(self.events))
        period = _finite(self.sample_period_s, "sample_period_s")
        white = _finite(self.white_noise_std_pu, "white_noise_std_pu")
        walk = _finite(
            self.random_walk_step_std_pu, "random_walk_step_std_pu"
        )
        if period <= 0.0:
            raise ValueError("sample_period_s must be positive")
        if white < 0.0 or walk < 0.0:
            raise ValueError("noise standard deviations must be non-negative")
        object.__setattr__(self, "sample_period_s", period)
        object.__setattr__(self, "white_noise_std_pu", white)
        object.__setattr__(self, "random_walk_step_std_pu", walk)

    def realize(self, *, seed: int, duration_s: float) -> LoadDisturbance:
        noise: SampledLoadNoise | None = None
        if self.white_noise_std_pu > 0.0 or self.random_walk_step_std_pu > 0.0:
            noise = SampledLoadNoise.from_seed(
                seed=seed,
                duration_s=duration_s,
                sample_period_s=self.sample_period_s,
                white_std_pu=self.white_noise_std_pu,
                random_walk_step_std_pu=self.random_walk_step_std_pu,
            )
        return LoadDisturbance(self.base_pu, self.events, noise)


__all__ = [
    "LoadDisturbance",
    "LoadDisturbanceSpec",
    "LoadEvent",
    "SampledLoadNoise",
]
