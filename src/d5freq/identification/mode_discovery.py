"""Unlabeled trajectory-to-mode discovery from local ARX fits.

The discovery path deliberately accepts only controller-visible trajectory
signals.  External code injects the ARX regression and fitting functions, which
keeps this module independent of data storage and prevents metadata from
entering the estimator.  Equations (76)--(84) define the implemented pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import Callable, Protocol, Sequence, TypeVar

import numpy as np
from numpy.typing import ArrayLike, NDArray
from sklearn.mixture import GaussianMixture
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler


FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
ARX_PARAMETER_COUNT = 7
FEATURE_DIMENSION = ARX_PARAMETER_COUNT + 1


class UnlabeledTrajectory(Protocol):
    """Public trajectory surface consumed by mode discovery.

    ``trajectory_id`` is an opaque join key.  It is retained for outputs but is
    never parsed or used as a feature.
    """

    trajectory_id: str
    p_ibr_pu: ArrayLike
    u_ibr_pu: ArrayLike
    omega_pu: ArrayLike


class ARXFitLike(Protocol):
    """Structural result required from an injected ARX fitter."""

    theta: ArrayLike
    residuals: ArrayLike
    residual_variance: float
    condition_number: float
    n_regression_rows: int


BuildRegression = Callable[[ArrayLike, ArrayLike, ArrayLike], tuple[ArrayLike, ArrayLike]]
FitTrajectory = Callable[..., ARXFitLike]
FitRegression = Callable[..., ARXFitLike]
ValidateTrajectory = Callable[..., object]


@dataclass(frozen=True, slots=True)
class ARXFitterAPI:
    """Injected implementation of equations (76), (77), and (83)."""

    build_regression: BuildRegression
    fit_trajectory: FitTrajectory
    fit_from_regression: FitRegression

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if not callable(getattr(self, name)):
                raise TypeError(f"{name} must be callable")


def _finite_real(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _positive_real(value: float, name: str) -> float:
    normalized = _finite_real(value, name)
    if normalized <= 0.0:
        raise ValueError(f"{name} must be strictly positive")
    return normalized


def _nonnegative_real(value: float, name: str) -> float:
    normalized = _finite_real(value, name)
    if normalized < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def _positive_integer(value: int, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized < 1:
        raise ValueError(f"{name} must be positive")
    return normalized


def _finite_vector(value: ArrayLike, name: str, *, minimum_size: int = 1) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise TypeError(f"{name} must be real-valued")
    vector = np.asarray(raw, dtype=np.float64)
    if vector.ndim != 1 or vector.size < minimum_size:
        raise ValueError(f"{name} must be a one-dimensional vector of length >= {minimum_size}")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must contain only finite values")
    owned = vector.copy()
    owned.setflags(write=False)
    return owned


def _finite_matrix(
    value: ArrayLike,
    name: str,
    *,
    columns: int | None = None,
    minimum_rows: int = 1,
) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise TypeError(f"{name} must be real-valued")
    matrix = np.asarray(raw, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] < minimum_rows:
        raise ValueError(f"{name} must be a two-dimensional matrix with rows")
    if columns is not None and matrix.shape[1] != columns:
        raise ValueError(f"{name} must have {columns} columns")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"{name} must contain only finite values")
    owned = matrix.copy()
    owned.setflags(write=False)
    return owned


def _condition_number(value: float, name: str) -> float:
    """Accept positive infinity so non-identifiable regressions are reportable."""

    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if math.isnan(normalized) or normalized < 0.0:
        raise ValueError(f"{name} must be non-negative and not NaN")
    return normalized


def _trajectory_arrays(
    trajectory: UnlabeledTrajectory,
) -> tuple[str, FloatArray, FloatArray, FloatArray]:
    try:
        trajectory_id = str(trajectory.trajectory_id).strip()
        p_ibr = _finite_vector(trajectory.p_ibr_pu, "p_ibr_pu", minimum_size=4)
        u_ibr = _finite_vector(trajectory.u_ibr_pu, "u_ibr_pu", minimum_size=4)
        omega = _finite_vector(trajectory.omega_pu, "omega_pu", minimum_size=4)
    except AttributeError as exc:
        raise TypeError(
            "trajectory must expose trajectory_id, p_ibr_pu, u_ibr_pu, and omega_pu"
        ) from exc
    if not trajectory_id:
        raise ValueError("trajectory_id must not be empty")
    if not (p_ibr.size == u_ibr.size == omega.size):
        raise ValueError("trajectory signal vectors must have equal lengths")
    return trajectory_id, p_ibr, u_ibr, omega


def build_raw_feature(
    theta: ArrayLike,
    residual_variance: float,
    *,
    variance_epsilon: float = 1.0e-12,
) -> FloatArray:
    """Return the eight-dimensional pre-standardization feature in (79)."""

    coefficients = _finite_vector(theta, "theta", minimum_size=ARX_PARAMETER_COUNT)
    if coefficients.shape != (ARX_PARAMETER_COUNT,):
        raise ValueError(f"theta must have shape ({ARX_PARAMETER_COUNT},)")
    variance = _nonnegative_real(residual_variance, "residual_variance")
    epsilon = _positive_real(variance_epsilon, "variance_epsilon")
    feature = np.concatenate((coefficients, [math.log(variance + epsilon)]))
    feature.setflags(write=False)
    return feature


@dataclass(frozen=True, slots=True)
class FeatureStandardizer:
    """Immutable state learned by ``sklearn.preprocessing.StandardScaler``."""

    mean: FloatArray
    scale: FloatArray
    variance: FloatArray
    n_samples_seen: int

    def __post_init__(self) -> None:
        mean = _finite_vector(self.mean, "mean", minimum_size=FEATURE_DIMENSION)
        scale = _finite_vector(self.scale, "scale", minimum_size=FEATURE_DIMENSION)
        variance = _finite_vector(self.variance, "variance", minimum_size=FEATURE_DIMENSION)
        if mean.shape != (FEATURE_DIMENSION,):
            raise ValueError(f"mean must have shape ({FEATURE_DIMENSION},)")
        if scale.shape != mean.shape or variance.shape != mean.shape:
            raise ValueError("mean, scale, and variance must have identical shapes")
        if np.any(scale <= 0.0):
            raise ValueError("scale entries must be strictly positive")
        if np.any(variance < 0.0):
            raise ValueError("variance entries must be non-negative")
        count = _positive_integer(self.n_samples_seen, "n_samples_seen")
        object.__setattr__(self, "mean", mean)
        object.__setattr__(self, "scale", scale)
        object.__setattr__(self, "variance", variance)
        object.__setattr__(self, "n_samples_seen", count)

    @classmethod
    def fit(cls, training_features: ArrayLike) -> "FeatureStandardizer":
        """Fit once on training episodes; validation/test data are not accepted."""

        features = _finite_matrix(
            training_features,
            "training_features",
            columns=FEATURE_DIMENSION,
        )
        fitted = StandardScaler(copy=True, with_mean=True, with_std=True).fit(features)
        return cls(
            mean=np.asarray(fitted.mean_, dtype=np.float64),
            scale=np.asarray(fitted.scale_, dtype=np.float64),
            variance=np.asarray(fitted.var_, dtype=np.float64),
            n_samples_seen=int(fitted.n_samples_seen_),
        )

    def transform(self, features: ArrayLike) -> FloatArray:
        values = _finite_matrix(features, "features", columns=FEATURE_DIMENSION)
        transformed = (values - self.mean) / self.scale
        if not np.all(np.isfinite(transformed)):
            raise FloatingPointError("feature standardization produced non-finite values")
        return np.asarray(transformed, dtype=np.float64)

    def to_dict(self) -> dict[str, object]:
        return {
            "mean": self.mean.tolist(),
            "scale": self.scale.tolist(),
            "variance": self.variance.tolist(),
            "n_samples_seen": self.n_samples_seen,
        }


@dataclass(frozen=True, slots=True)
class EpisodeARXFit:
    """Local equation-(77) result and equation-(76) pooled-fit sufficient data."""

    trajectory_id: str
    theta: FloatArray
    residual_variance: float
    condition_number: float
    regression_matrix: FloatArray
    target: FloatArray
    raw_feature: FloatArray

    def __post_init__(self) -> None:
        trajectory_id = str(self.trajectory_id).strip()
        if not trajectory_id:
            raise ValueError("trajectory_id must not be empty")
        theta = _finite_vector(self.theta, "theta", minimum_size=ARX_PARAMETER_COUNT)
        if theta.shape != (ARX_PARAMETER_COUNT,):
            raise ValueError(f"theta must have shape ({ARX_PARAMETER_COUNT},)")
        variance = _nonnegative_real(self.residual_variance, "residual_variance")
        condition = _condition_number(self.condition_number, "condition_number")
        phi = _finite_matrix(
            self.regression_matrix,
            "regression_matrix",
            columns=ARX_PARAMETER_COUNT,
        )
        target = _finite_vector(self.target, "target")
        if target.shape != (phi.shape[0],):
            raise ValueError("target length must equal regression matrix row count")
        raw = _finite_vector(self.raw_feature, "raw_feature", minimum_size=FEATURE_DIMENSION)
        if raw.shape != (FEATURE_DIMENSION,):
            raise ValueError(f"raw_feature must have shape ({FEATURE_DIMENSION},)")
        object.__setattr__(self, "trajectory_id", trajectory_id)
        object.__setattr__(self, "theta", theta)
        object.__setattr__(self, "residual_variance", variance)
        object.__setattr__(self, "condition_number", condition)
        object.__setattr__(self, "regression_matrix", phi)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "raw_feature", raw)


def fit_local_episode_models(
    trajectories: Sequence[UnlabeledTrajectory],
    *,
    arx: ARXFitterAPI,
    ridge_lambda: float,
    variance_epsilon: float = 1.0e-12,
) -> tuple[EpisodeARXFit, ...]:
    """Fit one ARX model per unlabeled training trajectory (76)--(79)."""

    if not isinstance(arx, ARXFitterAPI):
        raise TypeError("arx must be an ARXFitterAPI")
    regularization = _nonnegative_real(ridge_lambda, "ridge_lambda")
    epsilon = _positive_real(variance_epsilon, "variance_epsilon")
    if len(trajectories) == 0:
        raise ValueError("at least one training trajectory is required")

    records: list[EpisodeARXFit] = []
    seen_ids: set[str] = set()
    for trajectory in trajectories:
        trajectory_id, p_ibr, u_ibr, omega = _trajectory_arrays(trajectory)
        if trajectory_id in seen_ids:
            raise ValueError("trajectory_id values must be unique")
        seen_ids.add(trajectory_id)

        phi_raw, target_raw = arx.build_regression(p_ibr, u_ibr, omega)
        phi = _finite_matrix(
            phi_raw,
            "regression_matrix",
            columns=ARX_PARAMETER_COUNT,
        )
        target = _finite_vector(target_raw, "target")
        if target.shape != (phi.shape[0],):
            raise ValueError("injected regression builder returned inconsistent dimensions")

        fit = arx.fit_trajectory(
            p_ibr,
            u_ibr,
            omega,
            ridge_lambda=regularization,
        )
        theta = _finite_vector(fit.theta, "fit.theta", minimum_size=ARX_PARAMETER_COUNT)
        if theta.shape != (ARX_PARAMETER_COUNT,):
            raise ValueError(f"fit.theta must have shape ({ARX_PARAMETER_COUNT},)")
        variance = _nonnegative_real(fit.residual_variance, "fit.residual_variance")
        condition = _condition_number(fit.condition_number, "fit.condition_number")
        reported_rows = _positive_integer(fit.n_regression_rows, "fit.n_regression_rows")
        if reported_rows != phi.shape[0]:
            raise ValueError("ARX fit row count disagrees with regression builder")
        records.append(
            EpisodeARXFit(
                trajectory_id=trajectory_id,
                theta=theta,
                residual_variance=variance,
                condition_number=condition,
                regression_matrix=phi,
                target=target,
                raw_feature=build_raw_feature(
                    theta,
                    variance,
                    variance_epsilon=epsilon,
                ),
            )
        )
    return tuple(records)


@dataclass(frozen=True, slots=True)
class GMMCandidateScore:
    component_count: int
    bic: float | None
    delta_bic: float | None
    converged: bool
    iterations: int
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "component_count",
            _positive_integer(self.component_count, "component_count"),
        )
        bic = None if self.bic is None else _finite_real(self.bic, "bic")
        delta = (
            None
            if self.delta_bic is None
            else _nonnegative_real(self.delta_bic, "delta_bic")
        )
        if isinstance(self.iterations, (bool, np.bool_)) or not isinstance(
            self.iterations, Integral
        ):
            raise TypeError("iterations must be an integer")
        iterations = int(self.iterations)
        if iterations < 0:
            raise ValueError("iterations must be non-negative")
        if not isinstance(self.converged, (bool, np.bool_)):
            raise TypeError("converged must be boolean")
        reason = self.failure_reason
        if reason is not None:
            reason = str(reason).strip()
            if not reason:
                raise ValueError("failure_reason must be non-empty when supplied")
        if reason is None and (bic is None or delta is None):
            raise ValueError("successful candidates require bic and delta_bic")
        if reason is not None and (bic is not None or delta is not None or self.converged):
            raise ValueError("failed candidates cannot contain scores or convergence")
        object.__setattr__(self, "bic", bic)
        object.__setattr__(self, "delta_bic", delta)
        object.__setattr__(self, "iterations", iterations)
        object.__setattr__(self, "converged", bool(self.converged))
        object.__setattr__(self, "failure_reason", reason)


class GMMSelectionError(RuntimeError):
    """Raised when every candidate fails, retaining failure records for audit."""

    def __init__(self, candidate_scores: Sequence[GMMCandidateScore]) -> None:
        super().__init__("all GMM candidates failed")
        self.candidate_scores = tuple(candidate_scores)


@dataclass(frozen=True, slots=True)
class GMMSelectionResult:
    """BIC-selected equation-(80) mixture with native component identifiers."""

    model: GaussianMixture
    labels: IntArray
    candidate_scores: tuple[GMMCandidateScore, ...]
    silhouette: float | None
    cluster_sizes: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.model, GaussianMixture):
            raise TypeError("model must be a fitted GaussianMixture")
        labels = np.asarray(self.labels, dtype=np.int64)
        if labels.ndim != 1 or labels.size == 0:
            raise ValueError("labels must be a non-empty one-dimensional vector")
        if np.any(labels < 0) or np.any(labels >= self.model.n_components):
            raise ValueError("labels contain an invalid mixture component identifier")
        owned = labels.copy()
        owned.setflags(write=False)
        if len(self.candidate_scores) == 0:
            raise ValueError("candidate_scores must not be empty")
        if len(self.cluster_sizes) != self.model.n_components:
            raise ValueError("cluster_sizes must have one entry per component")
        if sum(self.cluster_sizes) != labels.size or any(size < 0 for size in self.cluster_sizes):
            raise ValueError("cluster_sizes are inconsistent with labels")
        if self.silhouette is not None:
            score = _finite_real(self.silhouette, "silhouette")
            if not -1.0 <= score <= 1.0:
                raise ValueError("silhouette must lie in [-1, 1]")
            object.__setattr__(self, "silhouette", score)
        object.__setattr__(self, "labels", owned)

    @property
    def selected_k(self) -> int:
        return int(self.model.n_components)

    @property
    def component_centers(self) -> FloatArray:
        return np.asarray(self.model.means_, dtype=np.float64).copy()


def select_gmm_by_bic(
    standardized_features: ArrayLike,
    *,
    k_min: int = 1,
    k_max: int = 6,
    covariance_type: str = "full",
    n_init: int = 20,
    random_seed: int = 0,
    max_iter: int = 500,
    reg_covar: float = 1.0e-6,
) -> GMMSelectionResult:
    """Fit deterministic multi-restart GMM candidates and minimize (82)."""

    features = _finite_matrix(
        standardized_features,
        "standardized_features",
        columns=FEATURE_DIMENSION,
    )
    minimum = _positive_integer(k_min, "k_min")
    maximum = _positive_integer(k_max, "k_max")
    if minimum > maximum:
        raise ValueError("k_min must not exceed k_max")
    maximum = min(maximum, features.shape[0])
    if minimum > maximum:
        raise ValueError("number of episodes is smaller than k_min")
    restarts = _positive_integer(n_init, "n_init")
    if restarts < 2:
        raise ValueError("n_init must be at least 2 for deterministic multi-restart fitting")
    iterations = _positive_integer(max_iter, "max_iter")
    covariance = str(covariance_type)
    if covariance not in {"full", "tied", "diag", "spherical"}:
        raise ValueError("unsupported covariance_type")
    regularizer = _positive_real(reg_covar, "reg_covar")
    if isinstance(random_seed, (bool, np.bool_)) or not isinstance(random_seed, Integral):
        raise TypeError("random_seed must be an integer")
    seed = int(random_seed)
    if seed < 0:
        raise ValueError("random_seed must be non-negative")

    candidates: dict[int, GaussianMixture] = {}
    raw_scores: list[tuple[int, float | None, bool, int, str | None]] = []
    for component_count in range(minimum, maximum + 1):
        component_seed = int(
            np.random.SeedSequence([seed, component_count]).generate_state(1, dtype=np.uint32)[0]
        )
        try:
            model = GaussianMixture(
                n_components=component_count,
                covariance_type=covariance,
                n_init=restarts,
                max_iter=iterations,
                reg_covar=regularizer,
                random_state=component_seed,
                init_params="kmeans",
            )
            model.fit(features)
            bic = float(model.bic(features))
            if not math.isfinite(bic):
                raise FloatingPointError("GMM BIC is non-finite")
            candidates[component_count] = model
            raw_scores.append(
                (
                    component_count,
                    bic,
                    bool(model.converged_),
                    int(model.n_iter_),
                    None,
                )
            )
        except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
            reason = f"{type(exc).__name__}: {str(exc)}".replace("\n", " ")[:500]
            raw_scores.append((component_count, None, False, 0, reason))

    successful = [(count, bic) for count, bic, _, _, _ in raw_scores if bic is not None]
    if not successful:
        failure_scores = tuple(
            GMMCandidateScore(
                component_count=count,
                bic=None,
                delta_bic=None,
                converged=False,
                iterations=iterations_used,
                failure_reason=reason,
            )
            for count, _, _, iterations_used, reason in raw_scores
        )
        raise GMMSelectionError(failure_scores)
    selected_count, minimum_bic = min(successful, key=lambda item: (item[1], item[0]))
    selected = candidates[selected_count]
    scores = tuple(
        GMMCandidateScore(
            component_count=count,
            bic=bic,
            delta_bic=None if bic is None else max(0.0, bic - minimum_bic),
            converged=converged,
            iterations=iterations_used,
            failure_reason=reason,
        )
        for count, bic, converged, iterations_used, reason in raw_scores
    )
    labels = np.asarray(selected.predict(features), dtype=np.int64)
    sizes = tuple(int(np.count_nonzero(labels == index)) for index in range(selected.n_components))
    unique_count = int(np.unique(labels).size)
    silhouette: float | None
    if 1 < unique_count < labels.size:
        silhouette = float(silhouette_score(features, labels))
    else:
        silhouette = None
    return GMMSelectionResult(
        model=selected,
        labels=labels,
        candidate_scores=scores,
        silhouette=silhouette,
        cluster_sizes=sizes,
    )


@dataclass(frozen=True, slots=True)
class ModeCapabilityBounds:
    """Robust externally observed power and directional rate limits (84)."""

    p_output_min_pu: float
    p_output_max_pu: float
    ramp_down_pu_per_s: float
    ramp_up_pu_per_s: float

    def __post_init__(self) -> None:
        lower = _finite_real(self.p_output_min_pu, "p_output_min_pu")
        upper = _finite_real(self.p_output_max_pu, "p_output_max_pu")
        if lower > upper:
            raise ValueError("p_output_min_pu must not exceed p_output_max_pu")
        down = _nonnegative_real(self.ramp_down_pu_per_s, "ramp_down_pu_per_s")
        up = _nonnegative_real(self.ramp_up_pu_per_s, "ramp_up_pu_per_s")
        object.__setattr__(self, "p_output_min_pu", lower)
        object.__setattr__(self, "p_output_max_pu", upper)
        object.__setattr__(self, "ramp_down_pu_per_s", down)
        object.__setattr__(self, "ramp_up_pu_per_s", up)


def estimate_mode_capability_bounds(
    power_trajectories: Sequence[ArrayLike],
    *,
    sample_time_s: float,
    lower_power_quantile: float = 0.01,
    upper_power_quantile: float = 0.99,
    directional_rate_quantile: float = 0.99,
) -> ModeCapabilityBounds:
    """Estimate (84), preserving trajectory boundaries and rate direction."""

    sample_time = _positive_real(sample_time_s, "sample_time_s")
    lower_q = _finite_real(lower_power_quantile, "lower_power_quantile")
    upper_q = _finite_real(upper_power_quantile, "upper_power_quantile")
    rate_q = _finite_real(directional_rate_quantile, "directional_rate_quantile")
    if not 0.0 <= lower_q < upper_q <= 1.0:
        raise ValueError("power quantiles must satisfy 0 <= lower < upper <= 1")
    if not 0.0 <= rate_q <= 1.0:
        raise ValueError("directional_rate_quantile must lie in [0, 1]")
    if len(power_trajectories) == 0:
        raise ValueError("at least one power trajectory is required")

    powers: list[FloatArray] = []
    rates: list[FloatArray] = []
    for index, values in enumerate(power_trajectories):
        power = _finite_vector(values, f"power_trajectories[{index}]", minimum_size=2)
        powers.append(power)
        rates.append(np.diff(power) / sample_time)
    all_power = np.concatenate(powers)
    all_rates = np.concatenate(rates)
    upward = all_rates[all_rates > 0.0]
    downward_magnitude = -all_rates[all_rates < 0.0]
    ramp_up = 0.0 if upward.size == 0 else float(np.quantile(upward, rate_q))
    ramp_down = (
        0.0
        if downward_magnitude.size == 0
        else float(np.quantile(downward_magnitude, rate_q))
    )
    return ModeCapabilityBounds(
        p_output_min_pu=float(np.quantile(all_power, lower_q)),
        p_output_max_pu=float(np.quantile(all_power, upper_q)),
        ramp_down_pu_per_s=ramp_down,
        ramp_up_pu_per_s=ramp_up,
    )


@dataclass(frozen=True, slots=True)
class DiscoveredModeModel:
    """Global equation-(83) refit keyed by the native mixture component ID."""

    component_id: int
    theta: FloatArray
    residual_variance: float
    condition_number: float
    training_episode_count: int
    training_sample_count: int
    capability: ModeCapabilityBounds

    def __post_init__(self) -> None:
        if isinstance(self.component_id, (bool, np.bool_)) or not isinstance(
            self.component_id, Integral
        ):
            raise TypeError("component_id must be an integer")
        component_id = int(self.component_id)
        if component_id < 0:
            raise ValueError("component_id must be non-negative")
        theta = _finite_vector(self.theta, "theta", minimum_size=ARX_PARAMETER_COUNT)
        if theta.shape != (ARX_PARAMETER_COUNT,):
            raise ValueError(f"theta must have shape ({ARX_PARAMETER_COUNT},)")
        variance = _positive_real(self.residual_variance, "residual_variance")
        condition = _condition_number(self.condition_number, "condition_number")
        episode_count = _positive_integer(self.training_episode_count, "training_episode_count")
        sample_count = _positive_integer(self.training_sample_count, "training_sample_count")
        if not isinstance(self.capability, ModeCapabilityBounds):
            raise TypeError("capability must be a ModeCapabilityBounds")
        object.__setattr__(self, "component_id", component_id)
        object.__setattr__(self, "theta", theta)
        object.__setattr__(self, "residual_variance", variance)
        object.__setattr__(self, "condition_number", condition)
        object.__setattr__(self, "training_episode_count", episode_count)
        object.__setattr__(self, "training_sample_count", sample_count)


@dataclass(frozen=True, slots=True)
class ModeValidationMetrics:
    """Held-out open-loop errors and external-bound coverage for one component."""

    component_id: int
    validation_episode_count: int
    prediction_origin_count: int
    rmse_by_lead: FloatArray
    mae_by_lead: FloatArray
    abs_error_quantile_95_by_lead: FloatArray
    power_bound_coverage: float
    directional_rate_bound_coverage: float

    def __post_init__(self) -> None:
        if isinstance(self.component_id, (bool, np.bool_)) or not isinstance(
            self.component_id, Integral
        ):
            raise TypeError("component_id must be an integer")
        component_id = int(self.component_id)
        if component_id < 0:
            raise ValueError("component_id must be non-negative")
        episode_count = _positive_integer(
            self.validation_episode_count, "validation_episode_count"
        )
        origin_count = _positive_integer(
            self.prediction_origin_count, "prediction_origin_count"
        )
        rmse = _finite_vector(self.rmse_by_lead, "rmse_by_lead")
        mae = _finite_vector(self.mae_by_lead, "mae_by_lead")
        quantile = _finite_vector(
            self.abs_error_quantile_95_by_lead,
            "abs_error_quantile_95_by_lead",
        )
        if not (rmse.shape == mae.shape == quantile.shape):
            raise ValueError("per-lead validation vectors must have identical shapes")
        if np.any(rmse < 0.0) or np.any(mae < 0.0) or np.any(quantile < 0.0):
            raise ValueError("validation errors must be non-negative")
        power_coverage = _finite_real(self.power_bound_coverage, "power_bound_coverage")
        rate_coverage = _finite_real(
            self.directional_rate_bound_coverage,
            "directional_rate_bound_coverage",
        )
        if not 0.0 <= power_coverage <= 1.0 or not 0.0 <= rate_coverage <= 1.0:
            raise ValueError("coverage fractions must lie in [0, 1]")
        object.__setattr__(self, "component_id", component_id)
        object.__setattr__(self, "validation_episode_count", episode_count)
        object.__setattr__(self, "prediction_origin_count", origin_count)
        object.__setattr__(self, "rmse_by_lead", rmse)
        object.__setattr__(self, "mae_by_lead", mae)
        object.__setattr__(self, "abs_error_quantile_95_by_lead", quantile)
        object.__setattr__(self, "power_bound_coverage", power_coverage)
        object.__setattr__(self, "directional_rate_bound_coverage", rate_coverage)

    @property
    def error_quantiles_for_library(self) -> dict[int, float]:
        """Return one-based lead-to-95%-absolute-error entries for JSON output."""

        return {
            lead: float(value)
            for lead, value in enumerate(self.abs_error_quantile_95_by_lead, start=1)
        }


def evaluate_assigned_validation_episodes(
    trajectories: Sequence[UnlabeledTrajectory],
    assignments: ArrayLike,
    mode_models: Sequence[DiscoveredModeModel],
    *,
    sample_time_s: float,
    horizon: int,
    validate_trajectory: ValidateTrajectory,
) -> tuple[ModeValidationMetrics, ...]:
    """Score each global model on separately assigned held-out trajectories."""

    if len(trajectories) == 0:
        raise ValueError("at least one validation trajectory is required")
    if not callable(validate_trajectory):
        raise TypeError("validate_trajectory must be callable")
    sample_time = _positive_real(sample_time_s, "sample_time_s")
    prediction_horizon = _positive_integer(horizon, "horizon")
    labels = np.asarray(assignments)
    if labels.ndim != 1 or labels.shape[0] != len(trajectories):
        raise ValueError("assignments must have one entry per validation trajectory")
    if np.iscomplexobj(labels) or not np.issubdtype(labels.dtype, np.integer):
        raise TypeError("assignments must contain integer component identifiers")
    labels = np.asarray(labels, dtype=np.int64)
    models = tuple(mode_models)
    if not models or not all(isinstance(model, DiscoveredModeModel) for model in models):
        raise TypeError("mode_models must be a non-empty sequence of DiscoveredModeModel")
    if tuple(model.component_id for model in models) != tuple(range(len(models))):
        raise ValueError("mode_models must retain contiguous native component IDs")
    if np.any(labels < 0) or np.any(labels >= len(models)):
        raise ValueError("assignments contain an invalid component identifier")
    trajectory_data = [_trajectory_arrays(trajectory) for trajectory in trajectories]

    metrics: list[ModeValidationMetrics] = []
    for model in models:
        indices = np.flatnonzero(labels == model.component_id)
        if indices.size == 0:
            raise ValueError(
                f"validation data contain no episode assigned to component {model.component_id}"
            )
        error_blocks: list[FloatArray] = []
        all_power: list[FloatArray] = []
        all_rates: list[FloatArray] = []
        for index in indices.tolist():
            _, power, command, omega = trajectory_data[index]
            validation = validate_trajectory(
                model.theta,
                power,
                command,
                omega,
                horizon=prediction_horizon,
            )
            errors = _finite_matrix(
                getattr(validation, "errors"),
                "validation.errors",
                columns=prediction_horizon,
            )
            error_blocks.append(errors)
            all_power.append(power)
            all_rates.append(np.diff(power) / sample_time)
        errors = np.vstack(error_blocks)
        absolute = np.abs(errors)
        power = np.concatenate(all_power)
        rates = np.concatenate(all_rates)
        capability = model.capability
        power_covered = np.logical_and(
            power >= capability.p_output_min_pu,
            power <= capability.p_output_max_pu,
        )
        rate_covered = np.logical_and(
            rates >= -capability.ramp_down_pu_per_s,
            rates <= capability.ramp_up_pu_per_s,
        )
        metrics.append(
            ModeValidationMetrics(
                component_id=model.component_id,
                validation_episode_count=int(indices.size),
                prediction_origin_count=int(errors.shape[0]),
                rmse_by_lead=np.sqrt(np.mean(np.square(errors), axis=0)),
                mae_by_lead=np.mean(absolute, axis=0),
                abs_error_quantile_95_by_lead=np.quantile(absolute, 0.95, axis=0),
                power_bound_coverage=float(np.mean(power_covered)),
                directional_rate_bound_coverage=float(np.mean(rate_covered)),
            )
        )
    return tuple(metrics)


def refit_global_cluster_models(
    trajectories: Sequence[UnlabeledTrajectory],
    episode_fits: Sequence[EpisodeARXFit],
    assignments: ArrayLike,
    *,
    arx: ARXFitterAPI,
    ridge_lambda: float,
    sample_time_s: float,
    residual_variance_floor: float = 1.0e-12,
    lower_power_quantile: float = 0.01,
    upper_power_quantile: float = 0.99,
    directional_rate_quantile: float = 0.99,
) -> tuple[DiscoveredModeModel, ...]:
    """Pool each discovered component's samples and perform global refits."""

    if not isinstance(arx, ARXFitterAPI):
        raise TypeError("arx must be an ARXFitterAPI")
    if len(trajectories) == 0 or len(trajectories) != len(episode_fits):
        raise ValueError("trajectories and episode_fits must have equal non-zero lengths")
    labels = np.asarray(assignments)
    if labels.ndim != 1 or labels.shape[0] != len(trajectories):
        raise ValueError("assignments must have one entry per trajectory")
    if not np.issubdtype(labels.dtype, np.integer):
        raise TypeError("assignments must contain integer component identifiers")
    labels = np.asarray(labels, dtype=np.int64)
    if np.any(labels < 0):
        raise ValueError("component identifiers must be non-negative")
    regularization = _nonnegative_real(ridge_lambda, "ridge_lambda")
    sample_time = _positive_real(sample_time_s, "sample_time_s")
    variance_floor = _positive_real(residual_variance_floor, "residual_variance_floor")

    trajectory_data = [_trajectory_arrays(trajectory) for trajectory in trajectories]
    for data, local in zip(trajectory_data, episode_fits, strict=True):
        if data[0] != local.trajectory_id:
            raise ValueError("episode_fits must remain in trajectory order")

    component_ids = np.unique(labels)
    expected = np.arange(int(component_ids[-1]) + 1, dtype=np.int64)
    if not np.array_equal(component_ids, expected):
        raise ValueError("native component identifiers must be contiguous from zero")

    models: list[DiscoveredModeModel] = []
    for component_id in component_ids.tolist():
        indices = np.flatnonzero(labels == component_id)
        phi = np.vstack([episode_fits[index].regression_matrix for index in indices])
        target = np.concatenate([episode_fits[index].target for index in indices])
        fit = arx.fit_from_regression(phi, target, ridge_lambda=regularization)
        theta = _finite_vector(fit.theta, "global_fit.theta", minimum_size=ARX_PARAMETER_COUNT)
        if theta.shape != (ARX_PARAMETER_COUNT,):
            raise ValueError(f"global_fit.theta must have shape ({ARX_PARAMETER_COUNT},)")
        residuals = target - phi @ theta
        global_variance = max(float(np.var(residuals, ddof=0)), variance_floor)
        condition = _condition_number(fit.condition_number, "global_fit.condition_number")
        capability = estimate_mode_capability_bounds(
            [trajectory_data[index][1] for index in indices],
            sample_time_s=sample_time,
            lower_power_quantile=lower_power_quantile,
            upper_power_quantile=upper_power_quantile,
            directional_rate_quantile=directional_rate_quantile,
        )
        models.append(
            DiscoveredModeModel(
                component_id=int(component_id),
                theta=theta,
                residual_variance=global_variance,
                condition_number=condition,
                training_episode_count=int(indices.size),
                training_sample_count=int(phi.shape[0]),
                capability=capability,
            )
        )
    return tuple(models)


@dataclass(frozen=True, slots=True)
class ModeDiscoveryConfig:
    """Numerical settings for the required equation-(76)--(84) main chain."""

    ridge_lambda: float = 1.0e-6
    variance_epsilon: float = 1.0e-12
    residual_variance_floor: float = 1.0e-12
    k_min: int = 1
    k_max: int = 6
    covariance_type: str = "full"
    n_init: int = 20
    random_seed: int = 0
    max_iter: int = 500
    reg_covar: float = 1.0e-6
    lower_power_quantile: float = 0.01
    upper_power_quantile: float = 0.99
    directional_rate_quantile: float = 0.99

    def __post_init__(self) -> None:
        object.__setattr__(self, "ridge_lambda", _nonnegative_real(self.ridge_lambda, "ridge_lambda"))
        object.__setattr__(self, "variance_epsilon", _positive_real(self.variance_epsilon, "variance_epsilon"))
        object.__setattr__(
            self,
            "residual_variance_floor",
            _positive_real(self.residual_variance_floor, "residual_variance_floor"),
        )
        minimum = _positive_integer(self.k_min, "k_min")
        maximum = _positive_integer(self.k_max, "k_max")
        if minimum > maximum:
            raise ValueError("k_min must not exceed k_max")
        object.__setattr__(self, "k_min", minimum)
        object.__setattr__(self, "k_max", maximum)
        covariance = str(self.covariance_type)
        if covariance not in {"full", "tied", "diag", "spherical"}:
            raise ValueError("unsupported covariance_type")
        object.__setattr__(self, "covariance_type", covariance)
        restarts = _positive_integer(self.n_init, "n_init")
        if restarts < 2:
            raise ValueError("n_init must be at least 2")
        object.__setattr__(self, "n_init", restarts)
        object.__setattr__(self, "max_iter", _positive_integer(self.max_iter, "max_iter"))
        object.__setattr__(self, "reg_covar", _positive_real(self.reg_covar, "reg_covar"))
        if isinstance(self.random_seed, (bool, np.bool_)) or not isinstance(
            self.random_seed, Integral
        ):
            raise TypeError("random_seed must be an integer")
        seed = int(self.random_seed)
        if seed < 0:
            raise ValueError("random_seed must be non-negative")
        object.__setattr__(self, "random_seed", seed)
        lower = _finite_real(self.lower_power_quantile, "lower_power_quantile")
        upper = _finite_real(self.upper_power_quantile, "upper_power_quantile")
        rate = _finite_real(self.directional_rate_quantile, "directional_rate_quantile")
        if not 0.0 <= lower < upper <= 1.0:
            raise ValueError("power quantiles must satisfy 0 <= lower < upper <= 1")
        if not 0.0 <= rate <= 1.0:
            raise ValueError("directional_rate_quantile must lie in [0, 1]")
        object.__setattr__(self, "lower_power_quantile", lower)
        object.__setattr__(self, "upper_power_quantile", upper)
        object.__setattr__(self, "directional_rate_quantile", rate)


@dataclass(frozen=True, slots=True)
class ModeDiscoveryResult:
    episode_fits: tuple[EpisodeARXFit, ...]
    standardized_features: FloatArray
    feature_scaler: FeatureStandardizer
    mixture: GMMSelectionResult
    mode_models: tuple[DiscoveredModeModel, ...]

    def __post_init__(self) -> None:
        if len(self.episode_fits) == 0:
            raise ValueError("episode_fits must not be empty")
        features = _finite_matrix(
            self.standardized_features,
            "standardized_features",
            columns=FEATURE_DIMENSION,
        )
        if features.shape[0] != len(self.episode_fits):
            raise ValueError("standardized feature rows must match episode_fits")
        if not isinstance(self.feature_scaler, FeatureStandardizer):
            raise TypeError("feature_scaler must be a FeatureStandardizer")
        if not isinstance(self.mixture, GMMSelectionResult):
            raise TypeError("mixture must be a GMMSelectionResult")
        if len(self.mode_models) != self.mixture.selected_k:
            raise ValueError("mode_models count must equal selected component count")
        features.setflags(write=False)
        object.__setattr__(self, "standardized_features", features)


@dataclass(frozen=True, slots=True)
class EpisodeAssignmentResult:
    """Assignments made with frozen training scaler and mixture parameters."""

    episode_fits: tuple[EpisodeARXFit, ...]
    standardized_features: FloatArray
    component_ids: IntArray
    component_probabilities: FloatArray

    def __post_init__(self) -> None:
        if len(self.episode_fits) == 0:
            raise ValueError("episode_fits must not be empty")
        features = _finite_matrix(
            self.standardized_features,
            "standardized_features",
            columns=FEATURE_DIMENSION,
        )
        component_ids = np.asarray(self.component_ids)
        if np.iscomplexobj(component_ids) or not np.issubdtype(component_ids.dtype, np.integer):
            raise TypeError("component_ids must contain integers")
        component_ids = np.asarray(component_ids, dtype=np.int64)
        probabilities = _finite_matrix(
            self.component_probabilities,
            "component_probabilities",
        )
        row_count = len(self.episode_fits)
        if features.shape[0] != row_count:
            raise ValueError("standardized feature rows must match episode_fits")
        if component_ids.shape != (row_count,):
            raise ValueError("component_ids must have one entry per episode")
        if probabilities.shape[0] != row_count:
            raise ValueError("component_probabilities must have one row per episode")
        if np.any(component_ids < 0) or np.any(component_ids >= probabilities.shape[1]):
            raise ValueError("component_ids contain an invalid component")
        if np.any(probabilities < 0.0) or not np.allclose(
            probabilities.sum(axis=1), 1.0, rtol=0.0, atol=1.0e-12
        ):
            raise ValueError("component_probabilities must be row-stochastic")
        features.setflags(write=False)
        component_ids = component_ids.copy()
        component_ids.setflags(write=False)
        probabilities.setflags(write=False)
        object.__setattr__(self, "standardized_features", features)
        object.__setattr__(self, "component_ids", component_ids)
        object.__setattr__(self, "component_probabilities", probabilities)


def assign_episodes_with_frozen_discovery(
    trajectories: Sequence[UnlabeledTrajectory],
    *,
    arx: ARXFitterAPI,
    feature_scaler: FeatureStandardizer,
    mixture: GaussianMixture,
    ridge_lambda: float,
    variance_epsilon: float = 1.0e-12,
) -> EpisodeAssignmentResult:
    """Assign held-out episodes without refitting either preprocessing or GMM."""

    if not isinstance(feature_scaler, FeatureStandardizer):
        raise TypeError("feature_scaler must be a fitted FeatureStandardizer")
    if not isinstance(mixture, GaussianMixture) or not hasattr(mixture, "means_"):
        raise TypeError("mixture must be a fitted GaussianMixture")
    fits = fit_local_episode_models(
        trajectories,
        arx=arx,
        ridge_lambda=ridge_lambda,
        variance_epsilon=variance_epsilon,
    )
    raw_features = np.vstack([fit.raw_feature for fit in fits])
    standardized = feature_scaler.transform(raw_features)
    component_ids = np.asarray(mixture.predict(standardized), dtype=np.int64)
    probabilities = np.asarray(mixture.predict_proba(standardized), dtype=np.float64)
    return EpisodeAssignmentResult(
        episode_fits=fits,
        standardized_features=standardized,
        component_ids=component_ids,
        component_probabilities=probabilities,
    )


def discover_unlabeled_modes(
    trajectories: Sequence[UnlabeledTrajectory],
    *,
    sample_time_s: float,
    arx: ARXFitterAPI,
    config: ModeDiscoveryConfig | None = None,
) -> ModeDiscoveryResult:
    """Run the complete training-only, label-free discovery main chain."""

    settings = config if config is not None else ModeDiscoveryConfig()
    if not isinstance(settings, ModeDiscoveryConfig):
        raise TypeError("config must be a ModeDiscoveryConfig")
    fits = fit_local_episode_models(
        trajectories,
        arx=arx,
        ridge_lambda=settings.ridge_lambda,
        variance_epsilon=settings.variance_epsilon,
    )
    raw_features = np.vstack([fit.raw_feature for fit in fits])
    scaler = FeatureStandardizer.fit(raw_features)
    standardized = scaler.transform(raw_features)
    mixture = select_gmm_by_bic(
        standardized,
        k_min=settings.k_min,
        k_max=settings.k_max,
        covariance_type=settings.covariance_type,
        n_init=settings.n_init,
        random_seed=settings.random_seed,
        max_iter=settings.max_iter,
        reg_covar=settings.reg_covar,
    )
    mode_models = refit_global_cluster_models(
        trajectories,
        fits,
        mixture.labels,
        arx=arx,
        ridge_lambda=settings.ridge_lambda,
        sample_time_s=sample_time_s,
        residual_variance_floor=settings.residual_variance_floor,
        lower_power_quantile=settings.lower_power_quantile,
        upper_power_quantile=settings.upper_power_quantile,
        directional_rate_quantile=settings.directional_rate_quantile,
    )
    return ModeDiscoveryResult(
        episode_fits=fits,
        standardized_features=standardized,
        feature_scaler=scaler,
        mixture=mixture,
        mode_models=mode_models,
    )


__all__ = [
    "ARX_PARAMETER_COUNT",
    "FEATURE_DIMENSION",
    "ARXFitterAPI",
    "DiscoveredModeModel",
    "EpisodeARXFit",
    "EpisodeAssignmentResult",
    "FeatureStandardizer",
    "GMMCandidateScore",
    "GMMSelectionResult",
    "GMMSelectionError",
    "ModeCapabilityBounds",
    "ModeDiscoveryConfig",
    "ModeDiscoveryResult",
    "ModeValidationMetrics",
    "UnlabeledTrajectory",
    "build_raw_feature",
    "assign_episodes_with_frozen_discovery",
    "discover_unlabeled_modes",
    "estimate_mode_capability_bounds",
    "evaluate_assigned_validation_episodes",
    "fit_local_episode_models",
    "refit_global_cluster_models",
    "select_gmm_by_bic",
]
