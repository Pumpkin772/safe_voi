"""Exact joint grid/ARX prediction matrices for equations (27)--(30)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import ArrayLike, NDArray

from d5freq.models.grid_frequency import GRID_STATE_SIZE, GridFrequencyModel


FloatArray = NDArray[np.float64]
ARX_STATE_SIZE = 5
JOINT_ARX_STATE_SIZE = GRID_STATE_SIZE + ARX_STATE_SIZE
JOINT_INPUT_SIZE = 2

ARX_POWER_OUTPUT = np.array([[1.0, 0.0, 0.0, 0.0, 0.0]])
GRID_FREQUENCY_OUTPUT = np.array([[1.0, 0.0, 0.0, 0.0, 0.0]])
JOINT_FREQUENCY_OUTPUT = np.array(
    [[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]
)
JOINT_INTEGRAL_OUTPUT = np.array(
    [[0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]
)
for _selector in (
    ARX_POWER_OUTPUT,
    GRID_FREQUENCY_OUTPUT,
    JOINT_FREQUENCY_OUTPUT,
    JOINT_INTEGRAL_OUTPUT,
):
    _selector.setflags(write=False)


def _real_matrix(value: ArrayLike, shape: tuple[int, int], name: str) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise ValueError(f"{name} must be real-valued")
    try:
        matrix = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real-valued matrix") from exc
    if matrix.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {matrix.shape}")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"{name} must contain only finite values")
    owned = matrix.copy()
    owned.setflags(write=False)
    return owned


def _real_vector(value: ArrayLike, size: int, name: str) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise ValueError(f"{name} must be real-valued")
    try:
        vector = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real-valued vector") from exc
    if vector.shape != (size,):
        raise ValueError(f"{name} must have shape ({size},), got {vector.shape}")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must contain only finite values")
    return vector.copy()


@dataclass(frozen=True, slots=True)
class JointARXPredictionModel:
    """Ten-state mode predictor with input order ``[u_sg, u_ibr]``."""

    A: FloatArray
    B: FloatArray
    C_frequency: FloatArray = field(
        default_factory=lambda: JOINT_FREQUENCY_OUTPUT.copy()
    )
    C_integral: FloatArray = field(
        default_factory=lambda: JOINT_INTEGRAL_OUTPUT.copy()
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "A",
            _real_matrix(
                self.A,
                (JOINT_ARX_STATE_SIZE, JOINT_ARX_STATE_SIZE),
                "A",
            ),
        )
        object.__setattr__(
            self,
            "B",
            _real_matrix(
                self.B,
                (JOINT_ARX_STATE_SIZE, JOINT_INPUT_SIZE),
                "B",
            ),
        )
        object.__setattr__(
            self,
            "C_frequency",
            _real_matrix(
                self.C_frequency,
                (1, JOINT_ARX_STATE_SIZE),
                "C_frequency",
            ),
        )
        object.__setattr__(
            self,
            "C_integral",
            _real_matrix(
                self.C_integral,
                (1, JOINT_ARX_STATE_SIZE),
                "C_integral",
            ),
        )

    def step(self, state: ArrayLike, control: ArrayLike) -> FloatArray:
        """Evaluate equation (29) without the additive prediction error."""

        state_vector = _real_vector(state, JOINT_ARX_STATE_SIZE, "state")
        control_vector = _real_vector(control, JOINT_INPUT_SIZE, "control")
        return self.A @ state_vector + self.B @ control_vector


def assemble_joint_arx_prediction(
    grid_model: GridFrequencyModel,
    A_b: ArrayLike,
    B_b: ArrayLike,
    F_b: ArrayLike,
) -> JointARXPredictionModel:
    """Assemble the block matrices in equations (27)--(30).

    ``A_b``, ``B_b`` and ``F_b`` are the exact five-state ARX realization from
    equations (23)--(24). The known grid's load-random-walk input is omitted
    from the executable control vector and remains an estimator/process-noise
    quantity.
    """

    if not isinstance(grid_model, GridFrequencyModel):
        raise TypeError("grid_model must be a GridFrequencyModel")
    arx_A = _real_matrix(A_b, (ARX_STATE_SIZE, ARX_STATE_SIZE), "A_b")
    arx_B = _real_matrix(B_b, (ARX_STATE_SIZE, 1), "B_b")
    arx_F = _real_matrix(F_b, (ARX_STATE_SIZE, 1), "F_b")
    grid_A, grid_B, grid_E, _ = grid_model.discrete_matrices()

    joint_A = np.block(
        [
            [grid_A, grid_E @ ARX_POWER_OUTPUT],
            [arx_F @ GRID_FREQUENCY_OUTPUT, arx_A],
        ]
    )
    joint_B = np.block(
        [
            [grid_B, np.zeros((GRID_STATE_SIZE, 1), dtype=np.float64)],
            [np.zeros((ARX_STATE_SIZE, 1), dtype=np.float64), arx_B],
        ]
    )
    return JointARXPredictionModel(A=joint_A, B=joint_B)


__all__ = [
    "ARX_POWER_OUTPUT",
    "ARX_STATE_SIZE",
    "GRID_FREQUENCY_OUTPUT",
    "JOINT_ARX_STATE_SIZE",
    "JOINT_FREQUENCY_OUTPUT",
    "JOINT_INPUT_SIZE",
    "JOINT_INTEGRAL_OUTPUT",
    "JointARXPredictionModel",
    "assemble_joint_arx_prediction",
]
