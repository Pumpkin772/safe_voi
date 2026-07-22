from __future__ import annotations

import numpy as np
import pytest

from d5freq.utils.seeds import SeedManager, derive_seed, make_rng, spawn_rngs


def test_named_generators_are_reproducible_and_order_independent() -> None:
    manager = SeedManager(20260722)
    first = manager.rng("scenario", "nominal", 7).normal(size=8)
    manager.rng("unrelated").normal(size=100)
    second = manager.rng("scenario", "nominal", 7).normal(size=8)

    np.testing.assert_array_equal(first, second)
    assert manager.seed("scenario", "nominal", 7) == derive_seed(
        20260722, "scenario", "nominal", 7
    )
    assert manager.seed("scenario", "nominal", 7) != manager.seed(
        "scenario", "nominal", 8
    )


def test_make_rng_does_not_modify_numpy_global_state() -> None:
    np.random.seed(12345)
    expected = np.random.random(4)
    np.random.seed(12345)

    rng = make_rng(9)
    assert isinstance(rng, np.random.Generator)
    rng.normal(size=100)

    np.testing.assert_array_equal(np.random.random(4), expected)


def test_spawn_rngs_is_reproducible() -> None:
    first = [rng.integers(0, 2**31, size=4) for rng in spawn_rngs(17, 3)]
    second = [rng.integers(0, 2**31, size=4) for rng in spawn_rngs(17, 3)]
    for first_values, second_values in zip(first, second, strict=True):
        np.testing.assert_array_equal(first_values, second_values)


@pytest.mark.parametrize("bad_seed", [-1, 1.5, True])
def test_invalid_seeds_are_rejected(bad_seed: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        make_rng(bad_seed)  # type: ignore[arg-type]
