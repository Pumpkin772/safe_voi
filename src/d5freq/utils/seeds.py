"""Order-independent seed derivation and explicit NumPy generators."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from numbers import Integral
from typing import Any

import numpy as np

from .hashing import canonical_json_bytes


def _checked_seed(seed: int | np.integer[Any]) -> int:
    if isinstance(seed, bool) or not isinstance(seed, Integral):
        raise TypeError("seed must be a non-negative integer")
    normalized = int(seed)
    if normalized < 0:
        raise ValueError("seed must be non-negative")
    return normalized


def make_rng(seed: int | np.integer[Any]) -> np.random.Generator:
    """Construct an explicit generator without touching NumPy's global RNG."""

    return np.random.default_rng(_checked_seed(seed))


def derive_seed(master_seed: int | np.integer[Any], *namespace: Any) -> int:
    """Derive a stable 64-bit seed from a master seed and namespace components."""

    master = _checked_seed(master_seed)
    payload = canonical_json_bytes(
        {"master_seed": master, "namespace": list(namespace)}
    )
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def spawn_rngs(
    master_seed: int | np.integer[Any], count: int
) -> tuple[np.random.Generator, ...]:
    """Create a deterministic tuple of statistically independent generators."""

    if isinstance(count, bool) or not isinstance(count, Integral):
        raise TypeError("count must be a non-negative integer")
    normalized_count = int(count)
    if normalized_count < 0:
        raise ValueError("count must be non-negative")
    sequence = np.random.SeedSequence(_checked_seed(master_seed))
    return tuple(np.random.default_rng(child) for child in sequence.spawn(normalized_count))


@dataclass(frozen=True, slots=True)
class SeedManager:
    """Immutable namespace-based seed factory.

    Unlike a mutable ``SeedSequence.spawn`` counter, named streams do not depend
    on the order in which other streams are requested.
    """

    master_seed: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "master_seed", _checked_seed(self.master_seed))

    def seed(self, *namespace: Any) -> int:
        """Return the master seed or a stable namespace-derived seed."""

        if not namespace:
            return self.master_seed
        return derive_seed(self.master_seed, *namespace)

    def rng(self, *namespace: Any) -> np.random.Generator:
        """Return a fresh explicit generator for a named stream."""

        return make_rng(self.seed(*namespace))

    def child(self, *namespace: Any) -> "SeedManager":
        """Return a new immutable manager rooted at a named child seed."""

        if not namespace:
            raise ValueError("child namespace must not be empty")
        return SeedManager(self.seed(*namespace))


__all__ = ["SeedManager", "derive_seed", "make_rng", "spawn_rngs"]
