"""Numerically stable online Bayes belief update for discovered ARX modes.

This module implements equations (40)--(47).  Rows of the transition matrix
represent the previous component and columns the next component.  At runtime
the filter consumes only measured IBR power and its controller-visible ARX
history; simulator truth labels are deliberately absent from every API.

For a measurement at index ``k``, the second-order ARX predictor uses

``[p[k-1], p[k-2], u[k-1], u[k-2], omega[k-1], omega[k-2], 1]``

to predict ``p[k]``.  This is the one-index shift of the convention in
``d5freq.identification.arx`` and therefore preserves its parameter order
exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real

import numpy as np
from numpy.typing import ArrayLike, NDArray

from d5freq.identification.arx import ARX_PARAMETER_COUNT
from d5freq.identification.model_library import ModeLibrary


FloatArray = NDArray[np.float64]

_LOG_TWO_PI = math.log(2.0 * math.pi)
_FLOAT_MAX = float(np.finfo(np.float64).max)
_LOG_FLOAT_MAX = math.log(_FLOAT_MAX)


def _finite_real(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _integer(value: int, name: str, *, minimum: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return normalized


def _finite_vector(
    value: ArrayLike,
    name: str,
    *,
    size: int | None = None,
) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise ValueError(f"{name} must be real-valued")
    try:
        vector = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real-valued vector") from exc
    expected = "one-dimensional" if size is None else f"shape ({size},)"
    if vector.ndim != 1 or (size is not None and vector.shape != (size,)):
        raise ValueError(f"{name} must have {expected}, got {vector.shape}")
    if vector.size == 0:
        raise ValueError(f"{name} must not be empty")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must contain only finite values")
    return vector.copy()


def _readonly(value: ArrayLike) -> FloatArray:
    owned = np.array(value, dtype=np.float64, copy=True)
    owned.setflags(write=False)
    return owned


def _belief_floor(value: float, component_count: int) -> float:
    floor = _finite_real(value, "belief_floor")
    if floor <= 0.0:
        raise ValueError("belief_floor must be strictly positive")
    if component_count > 1 and floor >= 1.0 / component_count:
        raise ValueError("belief_floor must be less than 1 / component_count")
    if component_count == 1 and floor > 1.0:
        raise ValueError("belief_floor must not exceed one for a single mode")
    return floor


def _normalize_probability(
    value: ArrayLike,
    component_count: int,
    name: str,
    *,
    floor: float,
) -> FloatArray:
    probability = _finite_vector(value, name, size=component_count)
    if np.any(probability < 0.0):
        raise ValueError(f"{name} entries must be non-negative")
    total = float(np.sum(probability))
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError(f"{name} must have a strictly positive finite sum")
    probability /= total
    probability = np.maximum(probability, floor)
    probability /= float(np.sum(probability))
    if not np.all(np.isfinite(probability)) or np.any(probability <= 0.0):
        raise FloatingPointError(f"{name} normalization failed")
    return probability


def _transition_matrix(value: ArrayLike, component_count: int) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise ValueError("transition_matrix must be real-valued")
    try:
        matrix = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError("transition_matrix must be a real-valued matrix") from exc
    expected_shape = (component_count, component_count)
    if matrix.shape != expected_shape:
        raise ValueError(
            f"transition_matrix must have shape {expected_shape}, got {matrix.shape}"
        )
    if not np.all(np.isfinite(matrix)):
        raise ValueError("transition_matrix must contain only finite values")
    if np.any(matrix < 0.0):
        raise ValueError("transition_matrix entries must be non-negative")
    if not np.allclose(matrix.sum(axis=1), 1.0, rtol=0.0, atol=1.0e-12):
        raise ValueError("transition_matrix rows must sum to one")
    return matrix.copy()


def build_sticky_transition_matrix(
    component_count: int,
    epsilon_switch: float,
) -> FloatArray:
    """Return the exact equation-(40) symmetric sticky transition matrix.

    For ``K > 1``, off-diagonal entries equal ``epsilon_switch`` and the
    diagonal is ``1 - (K - 1) * epsilon_switch``.  ``K = 1`` safely reduces
    to the one-by-one identity matrix.
    """

    count = _integer(component_count, "component_count", minimum=1)
    epsilon = _finite_real(epsilon_switch, "epsilon_switch")
    if epsilon < 0.0:
        raise ValueError("epsilon_switch must be non-negative")
    if count == 1:
        if epsilon > 1.0:
            raise ValueError("epsilon_switch must not exceed one")
        return np.ones((1, 1), dtype=np.float64)
    maximum = 1.0 / (count - 1)
    if epsilon > maximum:
        raise ValueError(
            "epsilon_switch must not exceed 1 / (component_count - 1)"
        )
    transition = np.full((count, count), epsilon, dtype=np.float64)
    np.fill_diagonal(transition, 1.0 - (count - 1) * epsilon)
    return transition


def predict_mode_belief(
    previous_belief: ArrayLike,
    transition_matrix: ArrayLike,
    *,
    belief_floor: float = 1.0e-15,
) -> FloatArray:
    """Apply equation (41), including a positive floor and renormalization."""

    raw_transition = np.asarray(transition_matrix)
    if raw_transition.ndim != 2 or raw_transition.shape[0] != raw_transition.shape[1]:
        raise ValueError("transition_matrix must be a square matrix")
    count = int(raw_transition.shape[0])
    if count < 1:
        raise ValueError("transition_matrix must not be empty")
    floor = _belief_floor(belief_floor, count)
    transition = _transition_matrix(transition_matrix, count)
    previous = _normalize_probability(
        previous_belief,
        count,
        "previous_belief",
        floor=floor,
    )
    # Pi[j, m] = P(mode_k=m | mode_{k-1}=j), hence Pi.T @ b.
    predicted = transition.T @ previous
    return _normalize_probability(
        predicted,
        count,
        "predicted_belief",
        floor=floor,
    )


def build_online_arx_regressor(
    *,
    p_ibr_k_minus_1_pu: float,
    p_ibr_k_minus_2_pu: float,
    u_ibr_k_minus_1_pu: float,
    u_ibr_k_minus_2_pu: float,
    omega_k_minus_1_pu: float,
    omega_k_minus_2_pu: float,
) -> FloatArray:
    """Build the seven-term regressor that predicts measured ``p_ibr[k]``."""

    return np.array(
        [
            _finite_real(p_ibr_k_minus_1_pu, "p_ibr_k_minus_1_pu"),
            _finite_real(p_ibr_k_minus_2_pu, "p_ibr_k_minus_2_pu"),
            _finite_real(u_ibr_k_minus_1_pu, "u_ibr_k_minus_1_pu"),
            _finite_real(u_ibr_k_minus_2_pu, "u_ibr_k_minus_2_pu"),
            _finite_real(omega_k_minus_1_pu, "omega_k_minus_1_pu"),
            _finite_real(omega_k_minus_2_pu, "omega_k_minus_2_pu"),
            1.0,
        ],
        dtype=np.float64,
    )


def _gaussian_statistics(
    residuals_pu: ArrayLike,
    innovation_variances_pu2: ArrayLike,
    *,
    variance_floor_pu2: float,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    residuals = _finite_vector(residuals_pu, "residuals_pu")
    variances = _finite_vector(
        innovation_variances_pu2,
        "innovation_variances_pu2",
        size=residuals.size,
    )
    if np.any(variances < 0.0):
        raise ValueError("innovation_variances_pu2 entries must be non-negative")
    variance_floor = _finite_real(variance_floor_pu2, "variance_floor_pu2")
    if variance_floor <= 0.0:
        raise ValueError("variance_floor_pu2 must be strictly positive")
    variances = np.maximum(variances, variance_floor)

    # Compute r^2 / S through logarithms so extremely small likelihoods do
    # not overflow before reaching the log-domain Bayes update.  Saturating at
    # float max preserves the correct limiting behavior and keeps diagnostics
    # finite instead of producing NaN from an all-minus-infinity log vector.
    absolute_residuals = np.abs(residuals)
    nis = np.zeros(residuals.size, dtype=np.float64)
    nonzero = absolute_residuals > 0.0
    log_nis = np.empty(residuals.size, dtype=np.float64)
    log_nis.fill(-math.inf)
    log_nis[nonzero] = (
        2.0 * np.log(absolute_residuals[nonzero]) - np.log(variances[nonzero])
    )
    finite_square = nonzero & (log_nis < _LOG_FLOAT_MAX)
    nis[finite_square] = np.exp(log_nis[finite_square])
    nis[nonzero & ~finite_square] = _FLOAT_MAX
    log_likelihoods = -0.5 * (_LOG_TWO_PI + np.log(variances) + nis)
    if not np.all(np.isfinite(log_likelihoods)):
        raise FloatingPointError("Gaussian log likelihood became non-finite")
    return variances, nis, log_likelihoods


def _logsumexp(log_weights: FloatArray) -> float:
    maximum = float(np.max(log_weights))
    if not math.isfinite(maximum):
        raise FloatingPointError("all log belief weights became non-finite")
    shifted_sum = float(np.sum(np.exp(log_weights - maximum)))
    if not math.isfinite(shifted_sum) or shifted_sum <= 0.0:
        raise FloatingPointError("log-sum-exp normalization failed")
    result = maximum + math.log(shifted_sum)
    if not math.isfinite(result):
        raise FloatingPointError("log normalization constant became non-finite")
    return result


@dataclass(frozen=True, slots=True)
class ModeBeliefUpdate:
    """Immutable controller-visible result of one equations-(42)--(47) update."""

    predicted_belief: FloatArray
    mode_belief: FloatArray
    mode_predictions_pu: FloatArray
    residuals_pu: FloatArray
    innovation_variances_pu2: FloatArray
    normalized_innovation_squared: FloatArray
    log_likelihoods: FloatArray
    log_normalization_constant: float
    entropy: float
    normalized_entropy: float
    map_mode: int

    def __post_init__(self) -> None:
        predicted = _finite_vector(self.predicted_belief, "predicted_belief")
        count = int(predicted.size)
        posterior = _finite_vector(
            self.mode_belief, "mode_belief", size=count
        )
        for probability, name in (
            (predicted, "predicted_belief"),
            (posterior, "mode_belief"),
        ):
            if np.any(probability < 0.0):
                raise ValueError(f"{name} entries must be non-negative")
            if not math.isclose(
                float(np.sum(probability)), 1.0, rel_tol=0.0, abs_tol=1.0e-12
            ):
                raise ValueError(f"{name} must sum to one")
        arrays = [predicted, posterior]
        for value, name in (
            (self.mode_predictions_pu, "mode_predictions_pu"),
            (self.residuals_pu, "residuals_pu"),
            (self.innovation_variances_pu2, "innovation_variances_pu2"),
            (
                self.normalized_innovation_squared,
                "normalized_innovation_squared",
            ),
            (self.log_likelihoods, "log_likelihoods"),
        ):
            arrays.append(_finite_vector(value, name, size=count))
        if np.any(arrays[4] <= 0.0):
            raise ValueError("innovation_variances_pu2 must be positive")
        if np.any(arrays[5] < 0.0):
            raise ValueError("normalized_innovation_squared must be non-negative")

        log_normalization = _finite_real(
            self.log_normalization_constant,
            "log_normalization_constant",
        )
        entropy = _finite_real(self.entropy, "entropy")
        normalized_entropy = _finite_real(
            self.normalized_entropy,
            "normalized_entropy",
        )
        if entropy < 0.0 or not 0.0 <= normalized_entropy <= 1.0:
            raise ValueError("belief entropies are outside their valid range")
        map_mode = _integer(self.map_mode, "map_mode", minimum=0)
        if map_mode >= count:
            raise ValueError("map_mode is outside the component range")
        if map_mode != int(np.argmax(posterior)):
            raise ValueError("map_mode must be the posterior argmax")

        object.__setattr__(self, "predicted_belief", _readonly(arrays[0]))
        object.__setattr__(self, "mode_belief", _readonly(arrays[1]))
        object.__setattr__(self, "mode_predictions_pu", _readonly(arrays[2]))
        object.__setattr__(self, "residuals_pu", _readonly(arrays[3]))
        object.__setattr__(
            self, "innovation_variances_pu2", _readonly(arrays[4])
        )
        object.__setattr__(
            self, "normalized_innovation_squared", _readonly(arrays[5])
        )
        object.__setattr__(self, "log_likelihoods", _readonly(arrays[6]))
        object.__setattr__(self, "log_normalization_constant", log_normalization)
        object.__setattr__(self, "entropy", entropy)
        object.__setattr__(self, "normalized_entropy", normalized_entropy)
        object.__setattr__(self, "map_mode", map_mode)

    @property
    def nis(self) -> FloatArray:
        """Per-component normalized innovation squared as a defensive copy."""

        return self.normalized_innovation_squared.copy()

    @property
    def belief_entropy(self) -> float:
        """Normalized equation-(47) entropy used by controller logic."""

        return self.normalized_entropy

    @property
    def raw_belief_entropy(self) -> float:
        """Unnormalized equation-(46) entropy."""

        return self.entropy


def update_mode_belief(
    predicted_belief: ArrayLike,
    *,
    observed_p_ibr_pu: float,
    mode_predictions_pu: ArrayLike,
    innovation_variances_pu2: ArrayLike,
    belief_floor: float = 1.0e-15,
    variance_floor_pu2: float = 1.0e-12,
) -> ModeBeliefUpdate:
    """Apply equations (42)--(47) using log-sum-exp normalization."""

    raw_predictions = _finite_vector(mode_predictions_pu, "mode_predictions_pu")
    count = int(raw_predictions.size)
    floor = _belief_floor(belief_floor, count)
    prior = _normalize_probability(
        predicted_belief,
        count,
        "predicted_belief",
        floor=floor,
    )
    observed = _finite_real(observed_p_ibr_pu, "observed_p_ibr_pu")
    with np.errstate(over="ignore", invalid="ignore"):
        residuals = observed - raw_predictions
    # Finite operands can overflow only when their signs oppose.  Map that
    # limiting residual to the largest representable signed magnitude.
    residuals = np.nan_to_num(
        residuals,
        nan=0.0,
        posinf=_FLOAT_MAX,
        neginf=-_FLOAT_MAX,
    )
    variances, nis, log_likelihoods = _gaussian_statistics(
        residuals,
        innovation_variances_pu2,
        variance_floor_pu2=variance_floor_pu2,
    )
    log_weights = np.log(prior) + log_likelihoods
    log_normalization = _logsumexp(log_weights)
    posterior = np.exp(log_weights - log_normalization)
    posterior = _normalize_probability(
        posterior,
        count,
        "mode_belief",
        floor=floor,
    )

    entropy = float(-np.sum(posterior * np.log(posterior)))
    if count == 1:
        normalized_entropy = 0.0
    else:
        normalized_entropy = float(entropy / math.log(count))
        # Protect the documented [0, 1] range from last-bit roundoff.
        normalized_entropy = min(1.0, max(0.0, normalized_entropy))
    return ModeBeliefUpdate(
        predicted_belief=prior,
        mode_belief=posterior,
        mode_predictions_pu=raw_predictions,
        residuals_pu=residuals,
        innovation_variances_pu2=variances,
        normalized_innovation_squared=nis,
        log_likelihoods=log_likelihoods,
        log_normalization_constant=log_normalization,
        entropy=entropy,
        normalized_entropy=normalized_entropy,
        map_mode=int(np.argmax(posterior)),
    )


# A descriptive alias used by callers that emphasize the Bayes operation.
bayesian_mode_update = update_mode_belief


class ModeBeliefFilter:
    """Stateful online filter backed by a frozen label-free ``ModeLibrary``."""

    __slots__ = (
        "_thetas",
        "_residual_variances_pu2",
        "_transition_matrix",
        "_measurement_noise_variance_pu2",
        "_belief_floor",
        "_variance_floor_pu2",
        "_initial_belief",
        "_belief",
        "_pending_predicted_belief",
        "_last_update",
    )

    def __init__(
        self,
        mode_library: ModeLibrary,
        measurement_noise_variance_pu2: float = 0.0,
        *,
        initial_belief: ArrayLike | None = None,
        transition_matrix: ArrayLike | None = None,
        belief_floor: float = 1.0e-15,
        variance_floor_pu2: float = 1.0e-12,
    ) -> None:
        if not isinstance(mode_library, ModeLibrary):
            raise TypeError("mode_library must be a ModeLibrary")
        count = len(mode_library.models)
        floor = _belief_floor(belief_floor, count)
        variance_floor = _finite_real(variance_floor_pu2, "variance_floor_pu2")
        if variance_floor <= 0.0:
            raise ValueError("variance_floor_pu2 must be strictly positive")
        measurement_variance = _finite_real(
            measurement_noise_variance_pu2,
            "measurement_noise_variance_pu2",
        )
        if measurement_variance < 0.0:
            raise ValueError(
                "measurement_noise_variance_pu2 must be non-negative"
            )

        self._thetas = np.vstack([model.theta for model in mode_library.models])
        if self._thetas.shape != (count, ARX_PARAMETER_COUNT):
            raise ValueError("mode library contains an invalid ARX theta matrix")
        self._residual_variances_pu2 = np.array(
            [model.residual_variance for model in mode_library.models],
            dtype=np.float64,
        )
        selected_transition = (
            mode_library.transition_matrix
            if transition_matrix is None
            else transition_matrix
        )
        self._transition_matrix = _transition_matrix(selected_transition, count)
        self._measurement_noise_variance_pu2 = measurement_variance
        self._belief_floor = floor
        self._variance_floor_pu2 = variance_floor
        uniform = np.full(count, 1.0 / count, dtype=np.float64)
        self._initial_belief = _normalize_probability(
            uniform if initial_belief is None else initial_belief,
            count,
            "initial_belief",
            floor=floor,
        )
        self._belief = self._initial_belief.copy()
        self._pending_predicted_belief: FloatArray | None = None
        self._last_update: ModeBeliefUpdate | None = None

    @property
    def component_count(self) -> int:
        return int(self._belief.size)

    @property
    def mode_belief(self) -> FloatArray:
        return self._belief.copy()

    @property
    def transition_matrix(self) -> FloatArray:
        return self._transition_matrix.copy()

    @property
    def innovation_variances_pu2(self) -> FloatArray:
        variances = (
            self._residual_variances_pu2
            + self._measurement_noise_variance_pu2
        )
        return np.maximum(variances, self._variance_floor_pu2)

    @property
    def last_update(self) -> ModeBeliefUpdate | None:
        return self._last_update

    def reset(self, initial_belief: ArrayLike | None = None) -> FloatArray:
        """Reset the posterior, pending prior, and last diagnostic result."""

        self._belief = _normalize_probability(
            self._initial_belief if initial_belief is None else initial_belief,
            self.component_count,
            "initial_belief",
            floor=self._belief_floor,
        )
        self._pending_predicted_belief = None
        self._last_update = None
        return self.mode_belief

    def predict(self) -> FloatArray:
        """Apply equation (41) and cache the prior for a separate update."""

        predicted = predict_mode_belief(
            self._belief,
            self._transition_matrix,
            belief_floor=self._belief_floor,
        )
        self._pending_predicted_belief = predicted.copy()
        return predicted.copy()

    def predict_mode_outputs(
        self,
        *,
        p_ibr_k_minus_1_pu: float,
        p_ibr_k_minus_2_pu: float,
        u_ibr_k_minus_1_pu: float,
        u_ibr_k_minus_2_pu: float,
        omega_k_minus_1_pu: float,
        omega_k_minus_2_pu: float,
    ) -> FloatArray:
        """Predict ``p_ibr[k]`` for every native discovered component."""

        regressor = build_online_arx_regressor(
            p_ibr_k_minus_1_pu=p_ibr_k_minus_1_pu,
            p_ibr_k_minus_2_pu=p_ibr_k_minus_2_pu,
            u_ibr_k_minus_1_pu=u_ibr_k_minus_1_pu,
            u_ibr_k_minus_2_pu=u_ibr_k_minus_2_pu,
            omega_k_minus_1_pu=omega_k_minus_1_pu,
            omega_k_minus_2_pu=omega_k_minus_2_pu,
        )
        predictions = self._thetas @ regressor
        if not np.all(np.isfinite(predictions)):
            raise FloatingPointError("ARX mode predictions became non-finite")
        return np.asarray(predictions, dtype=np.float64)

    def update(
        self,
        *,
        p_ibr_k_pu: float,
        mode_predictions_pu: ArrayLike,
    ) -> ModeBeliefUpdate:
        """Use a cached equation-(41) prior in equations (42)--(47)."""

        if self._pending_predicted_belief is None:
            raise RuntimeError("predict must be called before update")
        # Validate and calculate before mutating the posterior.
        result = update_mode_belief(
            self._pending_predicted_belief,
            observed_p_ibr_pu=p_ibr_k_pu,
            mode_predictions_pu=_finite_vector(
                mode_predictions_pu,
                "mode_predictions_pu",
                size=self.component_count,
            ),
            innovation_variances_pu2=self.innovation_variances_pu2,
            belief_floor=self._belief_floor,
            variance_floor_pu2=self._variance_floor_pu2,
        )
        self._belief = result.mode_belief.copy()
        self._pending_predicted_belief = None
        self._last_update = result
        return result

    def step(
        self,
        *,
        p_ibr_k_pu: float,
        p_ibr_k_minus_1_pu: float,
        p_ibr_k_minus_2_pu: float,
        u_ibr_k_minus_1_pu: float,
        u_ibr_k_minus_2_pu: float,
        omega_k_minus_1_pu: float,
        omega_k_minus_2_pu: float,
    ) -> ModeBeliefUpdate:
        """Atomically predict and update from controller-visible ARX history."""

        # Validate all observation/history inputs before changing filter state.
        observed = _finite_real(p_ibr_k_pu, "p_ibr_k_pu")
        predictions = self.predict_mode_outputs(
            p_ibr_k_minus_1_pu=p_ibr_k_minus_1_pu,
            p_ibr_k_minus_2_pu=p_ibr_k_minus_2_pu,
            u_ibr_k_minus_1_pu=u_ibr_k_minus_1_pu,
            u_ibr_k_minus_2_pu=u_ibr_k_minus_2_pu,
            omega_k_minus_1_pu=omega_k_minus_1_pu,
            omega_k_minus_2_pu=omega_k_minus_2_pu,
        )
        predicted_belief = predict_mode_belief(
            self._belief,
            self._transition_matrix,
            belief_floor=self._belief_floor,
        )
        result = update_mode_belief(
            predicted_belief,
            observed_p_ibr_pu=observed,
            mode_predictions_pu=predictions,
            innovation_variances_pu2=self.innovation_variances_pu2,
            belief_floor=self._belief_floor,
            variance_floor_pu2=self._variance_floor_pu2,
        )
        self._belief = result.mode_belief.copy()
        self._pending_predicted_belief = None
        self._last_update = result
        return result


__all__ = [
    "FloatArray",
    "ModeBeliefFilter",
    "ModeBeliefUpdate",
    "bayesian_mode_update",
    "build_online_arx_regressor",
    "build_sticky_transition_matrix",
    "predict_mode_belief",
    "update_mode_belief",
]
