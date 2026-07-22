"""Synchronous-generator LQI fallback for equations (71)--(75).

The uncontrollable load random-walk state is excluded from the DARE.  Its
controller-side estimate is instead used to translate the four controllable
states to the instantaneous equilibrium in equation (73).  The class accepts
any estimator implementing :class:`~d5freq.controllers.base.GridStateEstimator`
and defaults to the project's augmented grid Kalman filter.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.linalg import solve_discrete_are

from d5freq.controllers.base import (
    GridStateEstimator,
    clip_with_rate_limit,
    withdraw_toward_zero,
)
from d5freq.estimation.grid_kalman_filter import GridKalmanFilter
from d5freq.interfaces import ControlAction, Measurement
from d5freq.models.grid_frequency import (
    GRID_STATE_SIZE,
    GridFrequencyModel,
    GridStateIndex,
)


FloatArray = NDArray[np.float64]
ComplexArray = NDArray[np.complex128]
REDUCED_STATE_SIZE = 4
DEFAULT_LQI_Q_WEIGHTS = (3000.0, 1.0, 1.0, 50.0)


def _finite_real(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _state_vector(value: ArrayLike, name: str = "estimated_state") -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise ValueError(f"{name} must be real-valued")
    try:
        vector = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real-valued vector") from exc
    if vector.shape != (GRID_STATE_SIZE,):
        raise ValueError(
            f"{name} must have shape ({GRID_STATE_SIZE},), got {vector.shape}"
        )
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must contain only finite values")
    return vector.copy()


def _state_cost_matrix(value: ArrayLike) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise ValueError("state_cost must be real-valued")
    try:
        matrix = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError("state_cost must be a real-valued vector or matrix") from exc
    if matrix.shape == (REDUCED_STATE_SIZE,):
        matrix = np.diag(matrix)
    if matrix.shape != (REDUCED_STATE_SIZE, REDUCED_STATE_SIZE):
        raise ValueError("state_cost must have shape (4,) or (4, 4)")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("state_cost must contain only finite values")
    scale = max(1.0, float(np.max(np.abs(matrix))))
    if not np.allclose(matrix, matrix.T, rtol=1.0e-12, atol=1.0e-12 * scale):
        raise ValueError("state_cost must be symmetric")
    symmetric = 0.5 * (matrix + matrix.T)
    eigenvalues = np.linalg.eigvalsh(symmetric)
    tolerance = 1.0e-12 * max(1.0, float(np.max(np.abs(eigenvalues))))
    if float(eigenvalues[0]) < -tolerance:
        raise ValueError("state_cost must be positive semidefinite")
    return symmetric


@dataclass(frozen=True, slots=True)
class LQIFallbackConfig:
    """LQI weights and executable fallback-command limits."""

    q_weights: tuple[float, float, float, float] = DEFAULT_LQI_Q_WEIGHTS
    r_sg: float = 1.0
    u_sg_min_pu: float = -0.12
    u_sg_max_pu: float = 0.12
    u_sg_ramp_pu_per_s: float = 0.02
    ibr_withdraw_rate_pu_per_s: float = 0.04

    def __post_init__(self) -> None:
        try:
            weights = tuple(float(value) for value in self.q_weights)
        except (TypeError, ValueError) as exc:
            raise TypeError("q_weights must contain four real values") from exc
        if len(weights) != REDUCED_STATE_SIZE:
            raise ValueError("q_weights must contain four values")
        if not all(math.isfinite(value) for value in weights):
            raise ValueError("q_weights must contain only finite values")
        if any(value < 0.0 for value in weights):
            raise ValueError("q_weights must be non-negative")
        object.__setattr__(self, "q_weights", weights)

        scalar_fields = (
            "r_sg",
            "u_sg_min_pu",
            "u_sg_max_pu",
            "u_sg_ramp_pu_per_s",
            "ibr_withdraw_rate_pu_per_s",
        )
        for field_name in scalar_fields:
            object.__setattr__(
                self, field_name, _finite_real(getattr(self, field_name), field_name)
            )
        if self.r_sg <= 0.0:
            raise ValueError("r_sg must be positive")
        if self.u_sg_min_pu >= self.u_sg_max_pu:
            raise ValueError("u_sg_min_pu must be less than u_sg_max_pu")
        if self.u_sg_ramp_pu_per_s < 0.0:
            raise ValueError("u_sg_ramp_pu_per_s must be non-negative")
        if self.ibr_withdraw_rate_pu_per_s < 0.0:
            raise ValueError("ibr_withdraw_rate_pu_per_s must be non-negative")


def reduced_discrete_grid_matrices(
    grid_model: GridFrequencyModel,
) -> tuple[FloatArray, FloatArray]:
    """Return equation-(72) ``A_red, B_red`` with the load state removed."""

    if not isinstance(grid_model, GridFrequencyModel):
        raise TypeError("grid_model must be a GridFrequencyModel")
    A_d, B_d, _, _ = grid_model.discrete_matrices()
    return (
        A_d[:REDUCED_STATE_SIZE, :REDUCED_STATE_SIZE].copy(),
        B_d[:REDUCED_STATE_SIZE, :].copy(),
    )


def _solve_lqi_design(
    grid_model: GridFrequencyModel,
    state_cost: ArrayLike,
    input_cost: float,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    A_reduced, B_reduced = reduced_discrete_grid_matrices(grid_model)
    Q = _state_cost_matrix(state_cost)
    r_value = _finite_real(input_cost, "input_cost")
    if r_value <= 0.0:
        raise ValueError("input_cost must be positive")
    R = np.array([[r_value]], dtype=np.float64)
    try:
        P = solve_discrete_are(A_reduced, B_reduced, Q, R)
    except (ValueError, np.linalg.LinAlgError) as exc:
        raise ValueError("the reduced grid LQI DARE has no finite solution") from exc
    P = 0.5 * (np.asarray(P, dtype=np.float64) + np.asarray(P, dtype=np.float64).T)
    if not np.all(np.isfinite(P)):
        raise FloatingPointError("the LQI Riccati solution is not finite")
    p_eigenvalues = np.linalg.eigvalsh(P)
    p_tolerance = 1.0e-12 * max(1.0, float(np.max(np.abs(p_eigenvalues))))
    if float(p_eigenvalues[0]) <= p_tolerance:
        raise ValueError("the LQI Riccati solution must be positive definite")

    normal_matrix = R + B_reduced.T @ P @ B_reduced
    try:
        gain = np.linalg.solve(normal_matrix, B_reduced.T @ P @ A_reduced)
    except np.linalg.LinAlgError as exc:
        raise ValueError("the LQI gain normal matrix is singular") from exc
    closed_loop_eigenvalues = np.linalg.eigvals(A_reduced - B_reduced @ gain)
    if not np.all(np.isfinite(closed_loop_eigenvalues)):
        raise FloatingPointError("the LQI closed-loop eigenvalues are not finite")
    if float(np.max(np.abs(closed_loop_eigenvalues))) >= 1.0:
        raise ValueError("the reduced-grid LQI design is not Schur stable")
    return gain, P, A_reduced, B_reduced


def design_lqi_gain(
    grid_model: GridFrequencyModel,
    state_cost: ArrayLike = DEFAULT_LQI_Q_WEIGHTS,
    input_cost: float = 1.0,
) -> FloatArray:
    """Compute equation-(75) gain for the four controllable grid states."""

    gain, _, _, _ = _solve_lqi_design(grid_model, state_cost, input_cost)
    return gain.copy()


class LQIFallbackController:
    """Controller-visible LQI fallback with constrained executable commands."""

    __slots__ = (
        "_grid_model",
        "_config",
        "_estimator",
        "_gain",
        "_riccati_solution",
        "_A_reduced",
        "_B_reduced",
        "_estimated_state",
        "_last_estimator_time_s",
        "_is_reset",
    )

    def __init__(
        self,
        grid_model: GridFrequencyModel,
        config: LQIFallbackConfig | None = None,
        estimator: GridStateEstimator | None = None,
    ) -> None:
        if not isinstance(grid_model, GridFrequencyModel):
            raise TypeError("grid_model must be a GridFrequencyModel")
        resolved_config = LQIFallbackConfig() if config is None else config
        if not isinstance(resolved_config, LQIFallbackConfig):
            raise TypeError("config must be an LQIFallbackConfig")
        resolved_estimator: GridStateEstimator = (
            GridKalmanFilter(grid_model) if estimator is None else estimator
        )
        if not isinstance(resolved_estimator, GridStateEstimator):
            raise TypeError(
                "estimator must provide reset_from_measurement and "
                "update_from_measurement"
            )

        gain, P, A_reduced, B_reduced = _solve_lqi_design(
            grid_model,
            resolved_config.q_weights,
            resolved_config.r_sg,
        )
        self._grid_model = grid_model
        self._config = resolved_config
        self._estimator = resolved_estimator
        self._gain = gain
        self._riccati_solution = P
        self._A_reduced = A_reduced
        self._B_reduced = B_reduced
        self._estimated_state: FloatArray | None = None
        self._last_estimator_time_s: float | None = None
        self._is_reset = False

    @property
    def config(self) -> LQIFallbackConfig:
        return self._config

    @property
    def estimator(self) -> GridStateEstimator:
        return self._estimator

    @property
    def gain(self) -> FloatArray:
        """Defensive copy of equation-(75) ``K_LQI``."""

        return self._gain.copy()

    @property
    def riccati_solution(self) -> FloatArray:
        return self._riccati_solution.copy()

    @property
    def reduced_state_matrix(self) -> FloatArray:
        return self._A_reduced.copy()

    @property
    def reduced_input_matrix(self) -> FloatArray:
        return self._B_reduced.copy()

    @property
    def closed_loop_eigenvalues(self) -> ComplexArray:
        return np.asarray(
            np.linalg.eigvals(self._A_reduced - self._B_reduced @ self._gain),
            dtype=np.complex128,
        ).copy()

    @property
    def estimated_state(self) -> FloatArray:
        if self._estimated_state is None:
            raise RuntimeError("controller must be reset before reading estimated_state")
        return self._estimated_state.copy()

    def reset(self, initial_measurement: Measurement) -> None:
        """Reset estimator/controller state from controller-visible signals."""

        if not isinstance(initial_measurement, Measurement):
            raise TypeError("initial_measurement must be a Measurement")
        if not (
            self._config.u_sg_min_pu
            <= initial_measurement.u_sg_prev_pu
            <= self._config.u_sg_max_pu
        ):
            raise ValueError("initial previous SG command is outside configured bounds")
        estimate = self._estimator.reset_from_measurement(initial_measurement)
        self._estimated_state = _state_vector(estimate)
        self._last_estimator_time_s = initial_measurement.time_s
        self._is_reset = True

    def unconstrained_sg_command(self, estimated_state: ArrayLike) -> float:
        """Equation (74) before SG amplitude and rate constraints."""

        state = _state_vector(estimated_state)
        controllable_state = state[:REDUCED_STATE_SIZE]
        disturbance_estimate = float(state[GridStateIndex.LOAD_DISTURBANCE_PU])
        equilibrium = np.array(
            [0.0, disturbance_estimate, disturbance_estimate, 0.0],
            dtype=np.float64,
        )
        deviation = controllable_state - equilibrium
        command = disturbance_estimate - float((self._gain @ deviation).item())
        if not math.isfinite(command):
            raise FloatingPointError("unconstrained LQI command is not finite")
        return command

    def action_from_estimate(
        self,
        measurement: Measurement,
        estimated_state: ArrayLike,
    ) -> ControlAction:
        """Build a fallback action from an already-updated visible estimate.

        This entry point lets a composite SD-BMPC controller reuse its single
        Kalman update when it switches to fallback, avoiding a duplicate
        predict/update cycle.
        """

        if not isinstance(measurement, Measurement):
            raise TypeError("measurement must be a Measurement")
        state = _state_vector(estimated_state)
        requested_sg = self.unconstrained_sg_command(state)
        sample_time = self._grid_model.params.control_period_s
        u_sg = clip_with_rate_limit(
            requested_sg,
            measurement.u_sg_prev_pu,
            self._config.u_sg_min_pu,
            self._config.u_sg_max_pu,
            self._config.u_sg_ramp_pu_per_s,
            sample_time,
        )
        u_ibr = withdraw_toward_zero(
            measurement.u_ibr_prev_pu,
            self._config.ibr_withdraw_rate_pu_per_s,
            sample_time,
        )
        return ControlAction(
            u_sg_pu=u_sg,
            u_ibr_pu=u_ibr,
            controller_state="LQI_FALLBACK",
            solver_status="fallback_lqi",
            solve_time_s=0.0,
            max_freq_slack_hz=0.0,
        )

    def act(self, measurement: Measurement) -> ControlAction:
        """Update the injected estimator once and return a fallback action."""

        if not isinstance(measurement, Measurement):
            raise TypeError("measurement must be a Measurement")
        if not self._is_reset or self._last_estimator_time_s is None:
            raise RuntimeError("reset must be called before act")
        if measurement.time_s < self._last_estimator_time_s:
            raise ValueError("measurement time must be nondecreasing")

        # The normal control loop calls reset(initial) followed by act(initial).
        # Reuse reset's posterior at that same instant; predicting here would
        # advance the estimator by a control period before the plant advances.
        if measurement.time_s > self._last_estimator_time_s:
            estimate = self._estimator.update_from_measurement(measurement)
            self._estimated_state = _state_vector(estimate)
            self._last_estimator_time_s = measurement.time_s
        assert self._estimated_state is not None
        return self.action_from_estimate(measurement, self._estimated_state)


__all__ = [
    "DEFAULT_LQI_Q_WEIGHTS",
    "LQIFallbackConfig",
    "LQIFallbackController",
    "REDUCED_STATE_SIZE",
    "design_lqi_gain",
    "reduced_discrete_grid_matrices",
]
