"""Kalman state and load-disturbance estimator for the known grid model.

The estimator implements equations (31)--(37) with the fixed grid state order
``[omega_pu, p_mech_pu, p_valve_pu, xi_pu_s, load_disturbance_pu]`` and the
measurement order ``[omega_pu, p_mech_pu]``.  It has no hidden-mode input.
"""

from __future__ import annotations

import math
from numbers import Real

import numpy as np
from numpy.typing import ArrayLike, NDArray

from d5freq.interfaces import Measurement
from d5freq.models.grid_frequency import (
    GRID_STATE_SIZE,
    GridFrequencyModel,
    GridStateIndex,
)

FloatArray = NDArray[np.float64]

GRID_MEASUREMENT_SIZE = 2
GRID_MEASUREMENT_NAMES: tuple[str, str] = ("omega_pu", "p_mech_pu")
GRID_MEASUREMENT_MATRIX = np.array(
    [
        [1.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0, 0.0],
    ],
    dtype=np.float64,
)

_DEFAULT_BASE_PROCESS_DIAGONAL = np.array(
    [1.0e-12, 1.0e-10, 1.0e-9, 1.0e-12, 0.0], dtype=np.float64
)
_DEFAULT_MEASUREMENT_DIAGONAL = np.array([1.0e-8, 4.0e-8], dtype=np.float64)
_DEFAULT_INITIAL_COVARIANCE_DIAGONAL = np.array(
    [1.0e-6, 1.0e-5, 1.0e-4, 1.0e-3, 1.0e-3], dtype=np.float64
)


def _finite_real(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _vector(value: ArrayLike, size: int, name: str) -> FloatArray:
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


def _covariance(
    value: ArrayLike,
    size: int,
    name: str,
    *,
    positive_definite: bool,
) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise ValueError(f"{name} must be real-valued")
    try:
        matrix = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real-valued covariance matrix") from exc
    if matrix.shape != (size, size):
        raise ValueError(
            f"{name} must have shape ({size}, {size}), got {matrix.shape}"
        )
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"{name} must contain only finite values")
    symmetry_tolerance = 1.0e-12 * max(1.0, float(np.max(np.abs(matrix))))
    if not np.allclose(matrix, matrix.T, rtol=1.0e-12, atol=symmetry_tolerance):
        raise ValueError(f"{name} must be symmetric")
    symmetric = 0.5 * (matrix + matrix.T)
    eigenvalues = np.linalg.eigvalsh(symmetric)
    scale = max(1.0, float(np.max(np.abs(eigenvalues))))
    tolerance = 1.0e-12 * scale
    if positive_definite:
        # Positive definiteness is scale independent.  Very small but strictly
        # positive measurement variances remain valid research configurations.
        if float(eigenvalues[0]) <= 0.0:
            raise ValueError(f"{name} must be positive definite")
    elif float(eigenvalues[0]) < -tolerance:
        raise ValueError(f"{name} must be positive semidefinite")
    return symmetric.copy()


def _stabilize_covariance(value: FloatArray, name: str) -> FloatArray:
    """Symmetrize and remove only roundoff-scale negative eigenvalues."""

    symmetric = 0.5 * (value + value.T)
    if not np.all(np.isfinite(symmetric)):
        raise FloatingPointError(f"{name} became non-finite")
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    scale = max(1.0, float(np.max(np.abs(eigenvalues))))
    tolerance = 1.0e-10 * scale
    if float(eigenvalues[0]) < -tolerance:
        raise FloatingPointError(f"{name} lost positive semidefiniteness")
    if float(eigenvalues[0]) < 0.0:
        symmetric = (eigenvectors * np.maximum(eigenvalues, 0.0)) @ eigenvectors.T
        symmetric = 0.5 * (symmetric + symmetric.T)
        # Reconstructing an extremely ill-conditioned PSD matrix can itself
        # introduce a small negative eigenvalue.  A final diagonal correction
        # makes the stored covariance PSD at machine precision.
        reconstructed_minimum = float(np.linalg.eigvalsh(symmetric)[0])
        if reconstructed_minimum < 0.0:
            correction = -reconstructed_minimum + np.finfo(np.float64).eps * scale
            symmetric = symmetric + np.eye(symmetric.shape[0]) * correction
    return symmetric


class GridKalmanFilter:
    """Five-state linear Kalman filter with augmented load estimation.

    ``process_noise_covariance`` is a base discrete covariance in grid-state
    units.  In addition, ``load_random_walk_std_pu_per_s`` represents the
    standard deviation of a load slope held for one control interval.  Its
    covariance contribution is ``sigma_d**2 * G_d @ G_d.T``, so the exact ZOH
    load channel is used consistently in both prediction and process noise.

    The default covariances are conservative conveniences for smoke runs;
    experiments should pass calibrated values explicitly and save them in the
    resolved configuration.
    """

    __slots__ = (
        "_grid_model",
        "_A_d",
        "_B_d",
        "_E_d",
        "_G_d",
        "_C_g",
        "_base_Q_g",
        "_load_Q_g",
        "_Q_g",
        "_R_g",
        "_default_initial_covariance",
        "_state",
        "_covariance",
        "_innovation",
        "_innovation_covariance",
        "_kalman_gain",
        "_last_p_ibr_pu",
    )

    def __init__(
        self,
        grid_model: GridFrequencyModel,
        process_noise_covariance: ArrayLike | None = None,
        measurement_noise_covariance: ArrayLike | None = None,
        *,
        initial_covariance: ArrayLike | None = None,
        load_random_walk_std_pu_per_s: float = 1.0e-3,
    ) -> None:
        if not isinstance(grid_model, GridFrequencyModel):
            raise TypeError("grid_model must be a GridFrequencyModel")
        self._grid_model = grid_model
        self._A_d, self._B_d, self._E_d, self._G_d = (
            grid_model.discrete_matrices()
        )
        self._C_g = GRID_MEASUREMENT_MATRIX.copy()

        base_Q = (
            np.diag(_DEFAULT_BASE_PROCESS_DIAGONAL)
            if process_noise_covariance is None
            else process_noise_covariance
        )
        self._base_Q_g = _covariance(
            base_Q,
            GRID_STATE_SIZE,
            "process_noise_covariance",
            positive_definite=False,
        )
        load_std = _finite_real(
            load_random_walk_std_pu_per_s,
            "load_random_walk_std_pu_per_s",
        )
        if load_std < 0.0:
            raise ValueError("load_random_walk_std_pu_per_s must be non-negative")
        self._load_Q_g = (load_std * load_std) * (self._G_d @ self._G_d.T)
        # This is a sum of validated/generated PSD matrices.  Keep the exact
        # G_d mapping here; posterior stabilization is applied after propagation.
        self._Q_g = self._base_Q_g + self._load_Q_g

        R_g = (
            np.diag(_DEFAULT_MEASUREMENT_DIAGONAL)
            if measurement_noise_covariance is None
            else measurement_noise_covariance
        )
        self._R_g = _covariance(
            R_g,
            GRID_MEASUREMENT_SIZE,
            "measurement_noise_covariance",
            positive_definite=True,
        )
        default_P = (
            np.diag(_DEFAULT_INITIAL_COVARIANCE_DIAGONAL)
            if initial_covariance is None
            else initial_covariance
        )
        self._default_initial_covariance = _covariance(
            default_P,
            GRID_STATE_SIZE,
            "initial_covariance",
            positive_definite=False,
        )

        self._state = grid_model.zero_state()
        self._covariance = self._default_initial_covariance.copy()
        self._innovation = np.zeros(GRID_MEASUREMENT_SIZE, dtype=np.float64)
        self._innovation_covariance = self._R_g.copy()
        self._kalman_gain = np.zeros(
            (GRID_STATE_SIZE, GRID_MEASUREMENT_SIZE), dtype=np.float64
        )
        self._last_p_ibr_pu: float | None = None

    @property
    def grid_model(self) -> GridFrequencyModel:
        """Known physical model used by the filter."""

        return self._grid_model

    @property
    def state(self) -> FloatArray:
        """Current posterior/predicted state estimate as a defensive copy."""

        return self._state.copy()

    @property
    def covariance(self) -> FloatArray:
        """Current error covariance as a defensive copy."""

        return self._covariance.copy()

    @property
    def process_noise_covariance(self) -> FloatArray:
        """Total discrete ``Q_g`` used in equation (34)."""

        return self._Q_g.copy()

    @property
    def load_random_walk_covariance(self) -> FloatArray:
        """The ``G_d``-mapped load-random-walk part of ``Q_g``."""

        return self._load_Q_g.copy()

    @property
    def measurement_noise_covariance(self) -> FloatArray:
        """Measurement covariance ``R_g`` in omega/mechanical-power order."""

        return self._R_g.copy()

    @property
    def measurement_matrix(self) -> FloatArray:
        """Measurement matrix ``C_g`` from equation (32)."""

        return self._C_g.copy()

    @property
    def innovation(self) -> FloatArray:
        """Most recent measurement innovation as a defensive copy."""

        return self._innovation.copy()

    @property
    def innovation_covariance(self) -> FloatArray:
        """Most recent innovation covariance as a defensive copy."""

        return self._innovation_covariance.copy()

    @property
    def kalman_gain(self) -> FloatArray:
        """Most recent Kalman gain as a defensive copy."""

        return self._kalman_gain.copy()

    @property
    def load_disturbance_estimate_pu(self) -> float:
        """Posterior fifth-state estimate ``d_hat`` in per unit."""

        return float(self._state[GridStateIndex.LOAD_DISTURBANCE_PU])

    def reset(
        self,
        initial_state: ArrayLike | None = None,
        initial_covariance: ArrayLike | None = None,
    ) -> FloatArray:
        """Reset state and covariance and return a defensive state copy."""

        state = (
            self._grid_model.zero_state()
            if initial_state is None
            else _vector(initial_state, GRID_STATE_SIZE, "initial_state")
        )
        covariance = (
            self._default_initial_covariance.copy()
            if initial_covariance is None
            else _covariance(
                initial_covariance,
                GRID_STATE_SIZE,
                "initial_covariance",
                positive_definite=False,
            )
        )
        self._state = state.copy()
        self._covariance = covariance.copy()
        self._innovation = np.zeros(GRID_MEASUREMENT_SIZE, dtype=np.float64)
        self._innovation_covariance = self._R_g.copy()
        self._kalman_gain = np.zeros(
            (GRID_STATE_SIZE, GRID_MEASUREMENT_SIZE), dtype=np.float64
        )
        self._last_p_ibr_pu = None
        return self.state

    def reset_from_measurement(
        self,
        measurement: Measurement,
        initial_covariance: ArrayLike | None = None,
    ) -> FloatArray:
        """Reset measured states from a controller-visible measurement.

        Unmeasured ``p_valve``, ``xi`` and load disturbance are initialized to
        zero and subsequently inferred.  The measured IBR power is cached only
        as the known input for the next prediction.
        """

        if not isinstance(measurement, Measurement):
            raise TypeError("measurement must be a Measurement")
        initial_state = self._grid_model.zero_state()
        initial_state[GridStateIndex.OMEGA_PU] = measurement.omega_pu
        initial_state[GridStateIndex.P_MECH_PU] = measurement.p_mech_pu
        result = self.reset(initial_state, initial_covariance)
        self._last_p_ibr_pu = measurement.p_ibr_pu
        return result

    def predict(
        self,
        u_sg_prev_pu: float,
        p_ibr_prev_pu: float,
        load_derivative_pu_per_s: float = 0.0,
    ) -> FloatArray:
        """Apply equations (33)-(34) and return the predicted state.

        The optional load derivative is a known deterministic input in pu/s;
        ordinary unknown random-walk evolution is represented by ``Q_g`` and
        therefore uses its default value of zero here.
        """

        command = _finite_real(u_sg_prev_pu, "u_sg_prev_pu")
        ibr_power = _finite_real(p_ibr_prev_pu, "p_ibr_prev_pu")
        load_rate = _finite_real(
            load_derivative_pu_per_s, "load_derivative_pu_per_s"
        )
        predicted_state = (
            self._A_d @ self._state
            + self._B_d[:, 0] * command
            + self._E_d[:, 0] * ibr_power
            + self._G_d[:, 0] * load_rate
        )
        predicted_covariance = (
            self._A_d @ self._covariance @ self._A_d.T + self._Q_g
        )
        if not np.all(np.isfinite(predicted_state)):
            raise FloatingPointError("predicted state became non-finite")
        self._state = predicted_state
        self._covariance = _stabilize_covariance(
            predicted_covariance, "predicted covariance"
        )
        return self.state

    def update(self, omega_pu: float, p_mech_pu: float) -> FloatArray:
        """Apply equations (35)-(37) for ``y=[omega,p_mech]``.

        The covariance uses the Joseph stabilized form, which is algebraically
        equivalent to equation (37) in exact arithmetic while preserving
        symmetry and positive semidefiniteness under finite precision.
        """

        measurement = np.array(
            [
                _finite_real(omega_pu, "omega_pu"),
                _finite_real(p_mech_pu, "p_mech_pu"),
            ],
            dtype=np.float64,
        )
        innovation = measurement - self._C_g @ self._state
        innovation_covariance = (
            self._C_g @ self._covariance @ self._C_g.T + self._R_g
        )
        try:
            # solve(S, C P).T equals P C.T inv(S), without forming an inverse.
            gain = np.linalg.solve(
                innovation_covariance, self._C_g @ self._covariance
            ).T
        except np.linalg.LinAlgError as exc:
            raise FloatingPointError("innovation covariance is singular") from exc

        updated_state = self._state + gain @ innovation
        identity = np.eye(GRID_STATE_SIZE, dtype=np.float64)
        residual_map = identity - gain @ self._C_g
        updated_covariance = (
            residual_map @ self._covariance @ residual_map.T
            + gain @ self._R_g @ gain.T
        )
        if not np.all(np.isfinite(updated_state)):
            raise FloatingPointError("updated state became non-finite")
        self._state = updated_state
        self._covariance = _stabilize_covariance(
            updated_covariance, "updated covariance"
        )
        self._innovation = innovation
        self._innovation_covariance = innovation_covariance
        self._kalman_gain = gain
        return self.state

    def step(
        self,
        omega_pu: float,
        p_mech_pu: float,
        u_sg_prev_pu: float,
        p_ibr_prev_pu: float,
    ) -> FloatArray:
        """Run one predict/update cycle using only controller-visible values."""

        # Validate every external scalar before mutating filter state.
        measured_omega = _finite_real(omega_pu, "omega_pu")
        measured_power = _finite_real(p_mech_pu, "p_mech_pu")
        command = _finite_real(u_sg_prev_pu, "u_sg_prev_pu")
        ibr_power = _finite_real(p_ibr_prev_pu, "p_ibr_prev_pu")
        self.predict(command, ibr_power)
        return self.update(measured_omega, measured_power)

    def update_from_measurement(self, measurement: Measurement) -> FloatArray:
        """Adapt a controller measurement to a complete Kalman ``step``.

        Call :meth:`reset_from_measurement` once at the initial control instant.
        Thereafter this method uses the cached previous IBR power in equation
        (33), then caches the current measured IBR power for the next instant.
        """

        if not isinstance(measurement, Measurement):
            raise TypeError("measurement must be a Measurement")
        if self._last_p_ibr_pu is None:
            raise RuntimeError(
                "reset_from_measurement must be called before "
                "update_from_measurement"
            )
        result = self.step(
            omega_pu=measurement.omega_pu,
            p_mech_pu=measurement.p_mech_pu,
            u_sg_prev_pu=measurement.u_sg_prev_pu,
            p_ibr_prev_pu=self._last_p_ibr_pu,
        )
        self._last_p_ibr_pu = measurement.p_ibr_pu
        return result


__all__ = [
    "FloatArray",
    "GRID_MEASUREMENT_MATRIX",
    "GRID_MEASUREMENT_NAMES",
    "GRID_MEASUREMENT_SIZE",
    "GridKalmanFilter",
]
