"""Second-order black-box ARX identification and prediction algebra.

The fixed convention in equations (17)--(20) is

``phi_k = [p_k, p_{k-1}, u_k, u_{k-1}, omega_k, omega_{k-1}, 1]``

with target ``p_{k+1}``.  Power and frequency are per-unit quantities.  This
module intentionally depends only on externally observable trajectories; it
has no access to hidden IBR modes or truth-model parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real

import numpy as np
from numpy.typing import ArrayLike, NDArray


FloatArray = NDArray[np.float64]

ARX_PARAMETER_COUNT = 7
ARX_STATE_SIZE = 5
ARX_PARAMETER_NAMES: tuple[str, ...] = (
    "a1",
    "a2",
    "b0",
    "b1",
    "c0",
    "c1",
    "offset",
)


def _finite_scalar(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _one_dimensional_finite(value: ArrayLike, name: str) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise ValueError(f"{name} must be real-valued")
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real-valued vector") from exc
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array.copy()


def _theta_vector(theta: ArrayLike) -> FloatArray:
    raw = np.asarray(theta)
    if np.iscomplexobj(raw):
        raise ValueError("theta must be real-valued")
    try:
        vector = np.asarray(theta, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError("theta must be a real-valued vector") from exc
    if vector.shape != (ARX_PARAMETER_COUNT,):
        raise ValueError(
            "theta must have shape (7,) in the order "
            "[a1, a2, b0, b1, c0, c1, offset]"
        )
    if not np.all(np.isfinite(vector)):
        raise ValueError("theta must contain only finite values")
    return vector.copy()


def _positive_integer(value: int, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized <= 0:
        raise ValueError(f"{name} must be strictly positive")
    return normalized


def _readonly_copy(value: ArrayLike) -> FloatArray:
    owned = np.array(value, dtype=np.float64, copy=True)
    owned.setflags(write=False)
    return owned


@dataclass(frozen=True, slots=True)
class ARXFitResult:
    """Immutable output of an equation-(77) ridge fit.

    For a complete trajectory, ``residual_degrees_of_freedom`` follows the
    literal equation-(78) denominator ``N_e - 7``, where ``N_e`` is the raw
    aligned sample count. Direct regression-matrix fits may supply an explicit
    denominator; otherwise they use the conventional ``n_rows - 7``. Equation
    (77) is implemented literally, so all seven diagonal entries of
    ``lambda I`` are present, including the constant coefficient.
    """

    theta: FloatArray
    residuals: FloatArray
    residual_variance: float
    condition_number: float
    n_regression_rows: int
    residual_degrees_of_freedom: int
    ridge_lambda: float

    def __post_init__(self) -> None:
        theta = _theta_vector(self.theta)
        residuals = _one_dimensional_finite(self.residuals, "residuals")
        n_rows = _positive_integer(self.n_regression_rows, "n_regression_rows")
        if residuals.shape != (n_rows,):
            raise ValueError("residuals length must equal n_regression_rows")
        dof = self.residual_degrees_of_freedom
        if isinstance(dof, (bool, np.bool_)) or not isinstance(dof, Integral):
            raise TypeError("residual_degrees_of_freedom must be an integer")
        normalized_dof = int(dof)
        if normalized_dof <= 0:
            raise ValueError("residual_degrees_of_freedom must be positive")
        if normalized_dof > n_rows:
            raise ValueError(
                "residual_degrees_of_freedom must not exceed "
                "n_regression_rows"
            )

        variance = _finite_scalar(self.residual_variance, "residual_variance")
        if variance < 0.0:
            raise ValueError("residual_variance must be non-negative")
        ridge = _finite_scalar(self.ridge_lambda, "ridge_lambda")
        if ridge < 0.0:
            raise ValueError("ridge_lambda must be non-negative")

        condition = float(self.condition_number)
        if math.isnan(condition) or condition < 0.0:
            raise ValueError("condition_number must be non-negative or infinity")

        object.__setattr__(self, "theta", _readonly_copy(theta))
        object.__setattr__(self, "residuals", _readonly_copy(residuals))
        object.__setattr__(self, "residual_variance", variance)
        object.__setattr__(self, "condition_number", condition)
        object.__setattr__(self, "n_regression_rows", n_rows)
        object.__setattr__(self, "residual_degrees_of_freedom", normalized_dof)
        object.__setattr__(self, "ridge_lambda", ridge)


@dataclass(frozen=True, slots=True)
class MultiStepValidation:
    """Open-loop validation errors and per-lead summary statistics.

    Rows correspond to rollout origins and columns to lead times one through
    ``horizon``.  Errors use the convention ``observed - predicted``.
    """

    predictions: FloatArray
    errors: FloatArray
    rmse_by_lead: FloatArray
    mae_by_lead: FloatArray
    abs_error_quantile_95_by_lead: FloatArray

    def __post_init__(self) -> None:
        raw_predictions = np.asarray(self.predictions)
        raw_errors = np.asarray(self.errors)
        if np.iscomplexobj(raw_predictions) or np.iscomplexobj(raw_errors):
            raise ValueError("predictions and errors must be real-valued")
        try:
            predictions = np.asarray(self.predictions, dtype=np.float64)
            errors = np.asarray(self.errors, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise TypeError("predictions and errors must be real-valued arrays") from exc
        if predictions.ndim != 2 or predictions.shape != errors.shape:
            raise ValueError("predictions and errors must have the same 2-D shape")
        if predictions.shape[0] < 1 or predictions.shape[1] < 1:
            raise ValueError("multi-step arrays must not be empty")
        if not np.all(np.isfinite(predictions)) or not np.all(np.isfinite(errors)):
            raise ValueError("multi-step arrays must contain only finite values")

        horizon = predictions.shape[1]
        summaries: list[FloatArray] = []
        for value, name in (
            (self.rmse_by_lead, "rmse_by_lead"),
            (self.mae_by_lead, "mae_by_lead"),
            (
                self.abs_error_quantile_95_by_lead,
                "abs_error_quantile_95_by_lead",
            ),
        ):
            summary = _one_dimensional_finite(value, name)
            if summary.shape != (horizon,):
                raise ValueError(f"{name} must have shape ({horizon},)")
            if np.any(summary < 0.0):
                raise ValueError(f"{name} must be non-negative")
            summaries.append(summary)

        object.__setattr__(self, "predictions", _readonly_copy(predictions))
        object.__setattr__(self, "errors", _readonly_copy(errors))
        object.__setattr__(self, "rmse_by_lead", _readonly_copy(summaries[0]))
        object.__setattr__(self, "mae_by_lead", _readonly_copy(summaries[1]))
        object.__setattr__(
            self,
            "abs_error_quantile_95_by_lead",
            _readonly_copy(summaries[2]),
        )

    @property
    def horizon(self) -> int:
        """Number of open-loop prediction steps."""

        return int(self.predictions.shape[1])

    @property
    def n_origins(self) -> int:
        """Number of independently initialized rollout origins."""

        return int(self.predictions.shape[0])


def build_arx_regression(
    p_ibr_pu: ArrayLike,
    u_ibr_pu: ArrayLike,
    omega_pu: ArrayLike,
) -> tuple[FloatArray, FloatArray]:
    """Construct ``(Phi, Y)`` using equations (17), (18), and (76).

    For zero-based arrays, row ``j`` uses ``k = j + 1`` and therefore maps
    ``[p[k], p[k-1], u[k], u[k-1], omega[k], omega[k-1], 1]`` to
    ``p[k+1]``.  At least three aligned samples are required.
    """

    p = _one_dimensional_finite(p_ibr_pu, "p_ibr_pu")
    u = _one_dimensional_finite(u_ibr_pu, "u_ibr_pu")
    omega = _one_dimensional_finite(omega_pu, "omega_pu")
    if p.size != u.size or p.size != omega.size:
        raise ValueError("p_ibr_pu, u_ibr_pu, and omega_pu must have equal length")
    if p.size < 3:
        raise ValueError("at least three aligned trajectory samples are required")

    phi = np.column_stack(
        (
            p[1:-1],
            p[:-2],
            u[1:-1],
            u[:-2],
            omega[1:-1],
            omega[:-2],
            np.ones(p.size - 2, dtype=np.float64),
        )
    )
    targets = p[2:].copy()
    return phi, targets


def fit_arx_ridge_from_regression(
    design_matrix: ArrayLike,
    targets: ArrayLike,
    *,
    ridge_lambda: float,
    residual_degrees_of_freedom: int | None = None,
) -> ARXFitResult:
    """Fit equation (77) to an existing seven-column regression matrix.

    The solve is ``(Phi.T @ Phi + lambda * I_7) theta = Phi.T @ Y``.
    In particular, the constant column is penalized exactly as specified by
    equation (77). If no denominator is supplied, an arbitrary regression
    matrix uses the conventional ``n_rows - 7`` residual degrees of freedom.
    :func:`fit_arx_ridge` overrides it with the literal equation-(78)
    trajectory denominator ``raw_sample_count - 7``.
    """

    raw_phi = np.asarray(design_matrix)
    if np.iscomplexobj(raw_phi):
        raise ValueError("design_matrix must be real-valued")
    try:
        phi = np.asarray(design_matrix, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError("design_matrix must be a real-valued matrix") from exc
    if phi.ndim != 2 or phi.shape[1] != ARX_PARAMETER_COUNT:
        raise ValueError("design_matrix must have shape (n_rows, 7)")
    if not np.all(np.isfinite(phi)):
        raise ValueError("design_matrix must contain only finite values")
    phi = phi.copy()

    y = _one_dimensional_finite(targets, "targets")
    if y.shape != (phi.shape[0],):
        raise ValueError("targets must have shape (n_rows,)")
    n_rows = int(phi.shape[0])
    residual_dof = (
        n_rows - ARX_PARAMETER_COUNT
        if residual_degrees_of_freedom is None
        else _positive_integer(
            residual_degrees_of_freedom,
            "residual_degrees_of_freedom",
        )
    )
    if residual_dof <= 0:
        raise ValueError(
            "at least eight regression rows are required because residual "
            "variance uses n_regression_rows - 7 degrees of freedom"
        )
    if residual_dof > n_rows:
        raise ValueError(
            "residual_degrees_of_freedom must not exceed n_regression_rows"
        )

    ridge = _finite_scalar(ridge_lambda, "ridge_lambda")
    if ridge < 0.0:
        raise ValueError("ridge_lambda must be non-negative")

    normal_matrix = phi.T @ phi + ridge * np.eye(
        ARX_PARAMETER_COUNT, dtype=np.float64
    )
    normal_rhs = phi.T @ y
    try:
        theta = np.linalg.solve(normal_matrix, normal_rhs)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "ridge normal equations are singular; use a positive ridge_lambda "
            "or provide a persistently exciting trajectory"
        ) from exc

    residuals = y - phi @ theta
    residual_variance = float((residuals @ residuals) / residual_dof)
    condition_number = float(np.linalg.cond(phi))
    return ARXFitResult(
        theta=theta,
        residuals=residuals,
        residual_variance=residual_variance,
        condition_number=condition_number,
        n_regression_rows=n_rows,
        residual_degrees_of_freedom=residual_dof,
        ridge_lambda=ridge,
    )


def fit_arx_ridge(
    p_ibr_pu: ArrayLike,
    u_ibr_pu: ArrayLike,
    omega_pu: ArrayLike,
    *,
    ridge_lambda: float,
) -> ARXFitResult:
    """Build equations (18)/(76) and fit the trajectory by equation (77)."""

    p = _one_dimensional_finite(p_ibr_pu, "p_ibr_pu")
    phi, targets = build_arx_regression(p, u_ibr_pu, omega_pu)
    trajectory_dof = int(p.size) - ARX_PARAMETER_COUNT
    if trajectory_dof <= 0:
        raise ValueError(
            "at least eight aligned trajectory samples are required because "
            "equation (78) uses N_e - 7 degrees of freedom"
        )
    return fit_arx_ridge_from_regression(
        phi,
        targets,
        ridge_lambda=ridge_lambda,
        residual_degrees_of_freedom=trajectory_dof,
    )


def predict_arx_next(
    theta: ArrayLike,
    *,
    p_k: float,
    p_k_minus_1: float,
    u_k: float,
    u_k_minus_1: float,
    omega_k: float,
    omega_k_minus_1: float,
) -> float:
    """Return the deterministic equation-(20) prediction for ``p[k+1]``."""

    parameters = _theta_vector(theta)
    regressor = np.array(
        [
            _finite_scalar(p_k, "p_k"),
            _finite_scalar(p_k_minus_1, "p_k_minus_1"),
            _finite_scalar(u_k, "u_k"),
            _finite_scalar(u_k_minus_1, "u_k_minus_1"),
            _finite_scalar(omega_k, "omega_k"),
            _finite_scalar(omega_k_minus_1, "omega_k_minus_1"),
            1.0,
        ],
        dtype=np.float64,
    )
    return float(parameters @ regressor)


def predict_arx_one_step_series(
    theta: ArrayLike,
    p_ibr_pu: ArrayLike,
    u_ibr_pu: ArrayLike,
    omega_pu: ArrayLike,
) -> FloatArray:
    """One-step (teacher-initialized) predictions aligned with ``p[2:]``."""

    parameters = _theta_vector(theta)
    phi, _ = build_arx_regression(p_ibr_pu, u_ibr_pu, omega_pu)
    return np.asarray(phi @ parameters, dtype=np.float64)


def open_loop_arx_rollout(
    theta: ArrayLike,
    *,
    p_k: float,
    p_k_minus_1: float,
    u_k_minus_1: float,
    omega_k_minus_1: float,
    future_u_ibr_pu: ArrayLike,
    future_omega_pu: ArrayLike,
) -> FloatArray:
    """Roll equation (17) forward without future measured-power leakage.

    At lead ``i`` the supplied future command and frequency are used as the
    exogenous ``u[k+i]`` and ``omega[k+i]``.  For leads beyond one, both power
    lags are previous *predictions*, never future observed ``p`` values.
    """

    parameters = _theta_vector(theta)
    future_u = _one_dimensional_finite(future_u_ibr_pu, "future_u_ibr_pu")
    future_omega = _one_dimensional_finite(future_omega_pu, "future_omega_pu")
    if future_u.size != future_omega.size:
        raise ValueError("future_u_ibr_pu and future_omega_pu must have equal length")

    p_previous = _finite_scalar(p_k_minus_1, "p_k_minus_1")
    p_current = _finite_scalar(p_k, "p_k")
    u_previous = _finite_scalar(u_k_minus_1, "u_k_minus_1")
    omega_previous = _finite_scalar(omega_k_minus_1, "omega_k_minus_1")
    predictions = np.empty(future_u.size, dtype=np.float64)

    a1, a2, b0, b1, c0, c1, offset = parameters
    for index, (u_current, omega_current) in enumerate(
        zip(future_u, future_omega, strict=True)
    ):
        p_next = (
            a1 * p_current
            + a2 * p_previous
            + b0 * u_current
            + b1 * u_previous
            + c0 * omega_current
            + c1 * omega_previous
            + offset
        )
        predictions[index] = p_next
        p_previous, p_current = p_current, p_next
        u_previous = float(u_current)
        omega_previous = float(omega_current)

    return predictions


def validate_arx_multistep(
    theta: ArrayLike,
    p_ibr_pu: ArrayLike,
    u_ibr_pu: ArrayLike,
    omega_pu: ArrayLike,
    *,
    horizon: int,
) -> MultiStepValidation:
    """Evaluate true rolling-origin open-loop predictions on one trajectory.

    Each origin ``k`` is initialized only with data through ``k``.  The known
    validation command/frequency sequences over ``k .. k+horizon-1`` are used,
    while future measured IBR powers are reserved exclusively for scoring.
    """

    parameters = _theta_vector(theta)
    p = _one_dimensional_finite(p_ibr_pu, "p_ibr_pu")
    u = _one_dimensional_finite(u_ibr_pu, "u_ibr_pu")
    omega = _one_dimensional_finite(omega_pu, "omega_pu")
    if p.size != u.size or p.size != omega.size:
        raise ValueError("p_ibr_pu, u_ibr_pu, and omega_pu must have equal length")
    prediction_horizon = _positive_integer(horizon, "horizon")
    if p.size < prediction_horizon + 2:
        raise ValueError(
            "trajectory must contain at least horizon + 2 aligned samples"
        )

    n_origins = p.size - prediction_horizon - 1
    predictions = np.empty((n_origins, prediction_horizon), dtype=np.float64)
    observations = np.empty_like(predictions)
    for row, k in enumerate(range(1, p.size - prediction_horizon)):
        predictions[row] = open_loop_arx_rollout(
            parameters,
            p_k=float(p[k]),
            p_k_minus_1=float(p[k - 1]),
            u_k_minus_1=float(u[k - 1]),
            omega_k_minus_1=float(omega[k - 1]),
            future_u_ibr_pu=u[k : k + prediction_horizon],
            future_omega_pu=omega[k : k + prediction_horizon],
        )
        observations[row] = p[k + 1 : k + prediction_horizon + 1]

    errors = observations - predictions
    absolute_errors = np.abs(errors)
    return MultiStepValidation(
        predictions=predictions,
        errors=errors,
        rmse_by_lead=np.sqrt(np.mean(np.square(errors), axis=0)),
        mae_by_lead=np.mean(absolute_errors, axis=0),
        abs_error_quantile_95_by_lead=np.quantile(
            absolute_errors,
            0.95,
            axis=0,
        ),
    )


def arx_to_state_space(
    theta: ArrayLike,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """Convert equation (17) exactly to equations (21)--(25).

    The state is ``[p_k, p_{k-1}, u_{k-1}, omega_{k-1}, 1]``.  Returned
    matrices are independent, writable arrays owned by the caller.
    """

    a1, a2, b0, b1, c0, c1, offset = _theta_vector(theta)
    A_b = np.array(
        [
            [a1, a2, b1, c1, offset],
            [1.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    B_b = np.array([[b0], [0.0], [1.0], [0.0], [0.0]], dtype=np.float64)
    F_b = np.array([[c0], [0.0], [0.0], [1.0], [0.0]], dtype=np.float64)
    C_b = np.array([[1.0, 0.0, 0.0, 0.0, 0.0]], dtype=np.float64)
    return A_b, B_b, F_b, C_b


def arx_state_from_history(
    *,
    p_k: float,
    p_k_minus_1: float,
    u_k_minus_1: float,
    omega_k_minus_1: float,
) -> FloatArray:
    """Build the fixed equation-(21) state, including its constant one."""

    return np.array(
        [
            _finite_scalar(p_k, "p_k"),
            _finite_scalar(p_k_minus_1, "p_k_minus_1"),
            _finite_scalar(u_k_minus_1, "u_k_minus_1"),
            _finite_scalar(omega_k_minus_1, "omega_k_minus_1"),
            1.0,
        ],
        dtype=np.float64,
    )


__all__ = [
    "ARXFitResult",
    "ARX_PARAMETER_COUNT",
    "ARX_PARAMETER_NAMES",
    "ARX_STATE_SIZE",
    "MultiStepValidation",
    "arx_state_from_history",
    "arx_to_state_space",
    "build_arx_regression",
    "fit_arx_ridge",
    "fit_arx_ridge_from_regression",
    "open_loop_arx_rollout",
    "predict_arx_next",
    "predict_arx_one_step_series",
    "validate_arx_multistep",
]
