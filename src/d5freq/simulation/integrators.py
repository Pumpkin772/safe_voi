"""Small, deterministic integration utilities used by the truth simulator."""

from __future__ import annotations

from collections.abc import Callable
import math

import numpy as np
from numpy.typing import ArrayLike, NDArray


StateDerivative = Callable[[float, NDArray[np.float64]], ArrayLike]


def _finite_positive(value: float, name: str) -> float:
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return normalized


def _state_vector(state: ArrayLike) -> NDArray[np.float64]:
    vector = np.asarray(state, dtype=float)
    if vector.ndim != 1:
        raise ValueError("state must be a one-dimensional vector")
    if not np.all(np.isfinite(vector)):
        raise ValueError("state must contain only finite values")
    return vector.copy()


def _evaluate(
    derivative: StateDerivative,
    time_s: float,
    state: NDArray[np.float64],
) -> NDArray[np.float64]:
    value = np.asarray(derivative(float(time_s), state.copy()), dtype=float)
    if value.shape != state.shape:
        raise ValueError(
            f"derivative shape {value.shape} does not match state shape {state.shape}"
        )
    if not np.all(np.isfinite(value)):
        raise FloatingPointError("derivative returned a non-finite value")
    return value


def rk4_step(
    derivative: StateDerivative,
    time_s: float,
    state: ArrayLike,
    dt_s: float,
) -> NDArray[np.float64]:
    """Advance an ODE by one classical fourth-order Runge--Kutta step.

    The input state is copied and never mutated. ``derivative`` receives the
    physical time first and a one-dimensional state vector second.
    """

    time = float(time_s)
    if not math.isfinite(time):
        raise ValueError("time_s must be finite")
    dt = _finite_positive(dt_s, "dt_s")
    initial = _state_vector(state)

    k1 = _evaluate(derivative, time, initial)
    k2 = _evaluate(derivative, time + 0.5 * dt, initial + 0.5 * dt * k1)
    k3 = _evaluate(derivative, time + 0.5 * dt, initial + 0.5 * dt * k2)
    k4 = _evaluate(derivative, time + dt, initial + dt * k3)
    result = initial + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
    if not np.all(np.isfinite(result)):
        raise FloatingPointError("RK4 step produced a non-finite state")
    return result


def integrate_rk4(
    derivative: StateDerivative,
    initial_state: ArrayLike,
    *,
    start_time_s: float,
    duration_s: float,
    max_step_s: float,
) -> NDArray[np.float64]:
    """Integrate for ``duration_s`` using steps no larger than ``max_step_s``."""

    start = float(start_time_s)
    duration = float(duration_s)
    if not math.isfinite(start):
        raise ValueError("start_time_s must be finite")
    if not math.isfinite(duration) or duration < 0.0:
        raise ValueError("duration_s must be finite and non-negative")
    maximum_step = _finite_positive(max_step_s, "max_step_s")

    state = _state_vector(initial_state)
    if duration == 0.0:
        return state

    step_count = max(1, math.ceil(duration / maximum_step))
    step = duration / step_count
    time = start
    for _ in range(step_count):
        state = rk4_step(derivative, time, state, step)
        time += step
    return state


__all__ = ["StateDerivative", "integrate_rk4", "rk4_step"]
