"""Exact zero-order-hold discretization utilities.

The routines in this module use seconds for every time argument.  Input
matrices may contain one or more channels, but every channel is assumed
constant over the complete sampling interval (zero-order hold).
"""

from __future__ import annotations

import math
from numbers import Real

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.linalg import expm

FloatArray = NDArray[np.float64]


def _positive_seconds(value: float, name: str) -> float:
    """Return a finite, strictly positive duration in seconds."""

    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real-valued duration in seconds")
    duration_s = float(value)
    if not math.isfinite(duration_s):
        raise ValueError(f"{name} must be finite")
    if duration_s <= 0.0:
        raise ValueError(f"{name} must be strictly positive")
    return duration_s


def _finite_matrix(value: ArrayLike, name: str) -> FloatArray:
    """Normalize an array-like value to a finite two-dimensional matrix."""

    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise ValueError(f"{name} must be real-valued")
    try:
        matrix = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real-valued matrix") from exc
    if matrix.ndim != 2:
        raise ValueError(f"{name} must be two-dimensional")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"{name} must contain only finite values")
    return matrix


def exact_zoh(
    A_c: ArrayLike,
    *input_matrices: ArrayLike,
    sample_time_s: float,
) -> tuple[FloatArray, ...]:
    """Discretize a continuous linear system using an exact ZOH.

    This implements equation (10).  Given ``xdot = A_c x + sum(B_i u_i)``,
    it returns ``(A_d, B_1_d, ..., B_n_d)`` for inputs that are constant for
    ``sample_time_s`` seconds.  Each input matrix must have the same number of
    rows as ``A_c`` and at least one column.  With no input matrices, the
    return value is the one-element tuple ``(A_d,)``.

    Parameters
    ----------
    A_c:
        Continuous state matrix, with units consistent with inverse seconds.
    *input_matrices:
        Continuous input matrices.  Columns may have different physical units.
    sample_time_s:
        Zero-order-hold interval in seconds.
    """

    state_matrix = _finite_matrix(A_c, "A_c")
    state_count = state_matrix.shape[0]
    if state_count == 0 or state_matrix.shape[1] != state_count:
        raise ValueError("A_c must be a non-empty square matrix")

    duration_s = _positive_seconds(sample_time_s, "sample_time_s")
    normalized_inputs: list[FloatArray] = []
    for index, value in enumerate(input_matrices):
        matrix = _finite_matrix(value, f"input_matrices[{index}]")
        if matrix.shape[0] != state_count:
            raise ValueError(
                f"input_matrices[{index}] must have {state_count} rows, "
                f"got {matrix.shape[0]}"
            )
        if matrix.shape[1] == 0:
            raise ValueError(f"input_matrices[{index}] must have at least one column")
        normalized_inputs.append(matrix)

    input_width = sum(matrix.shape[1] for matrix in normalized_inputs)
    augmented = np.zeros(
        (state_count + input_width, state_count + input_width), dtype=np.float64
    )
    augmented[:state_count, :state_count] = state_matrix
    if normalized_inputs:
        augmented[:state_count, state_count:] = np.hstack(normalized_inputs)

    exponential = expm(augmented * duration_s)
    if not np.all(np.isfinite(exponential)):
        raise FloatingPointError("matrix exponential produced non-finite values")

    outputs: list[FloatArray] = [
        np.array(exponential[:state_count, :state_count], dtype=np.float64, copy=True)
    ]
    cursor = state_count
    for matrix in normalized_inputs:
        next_cursor = cursor + matrix.shape[1]
        outputs.append(
            np.array(exponential[:state_count, cursor:next_cursor], copy=True)
        )
        cursor = next_cursor
    return tuple(outputs)


__all__ = ["FloatArray", "exact_zoh"]
