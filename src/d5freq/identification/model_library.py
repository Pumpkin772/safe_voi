"""Strict, truth-free JSON model library for discovered ARX components."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from numbers import Integral, Real
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray


FloatArray = NDArray[np.float64]
MODE_LIBRARY_SCHEMA_VERSION = "d5freq.mode_library.v2"
ARX_PARAMETER_COUNT = 7
FEATURE_DIMENSION = 8
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "models",
        "transition_matrix",
        "feature_scaler",
        "discovery_metadata",
    }
)
_MODEL_KEYS = frozenset(
    {
        "component_id",
        "theta",
        "residual_variance",
        "multi_step_power_error_quantiles_pu",
        "multi_step_frequency_error_quantiles_hz",
        "multi_step_rocof_error_quantiles_hz_per_s",
        "p_output_min_pu",
        "p_output_max_pu",
        "ramp_down_pu_per_s",
        "ramp_up_pu_per_s",
        "training_episode_count",
        "training_sample_count",
    }
)
_SCALER_KEYS = frozenset({"mean", "scale", "variance", "n_samples_seen"})
_DISCOVERY_KEYS = frozenset(
    {
        "selected_k",
        "candidate_k_min",
        "candidate_k_max",
        "covariance_type",
        "n_init",
        "random_seed",
        "bic_table",
    }
)
_BIC_KEYS = frozenset(
    {
        "component_count",
        "bic",
        "delta_bic",
        "converged",
        "iterations",
        "failure_reason",
    }
)


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _positive_real(value: object, name: str) -> float:
    normalized = _finite_real(value, name)
    if normalized <= 0.0:
        raise ValueError(f"{name} must be strictly positive")
    return normalized


def _nonnegative_real(value: object, name: str) -> float:
    normalized = _finite_real(value, name)
    if normalized < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return normalized


def _vector(value: ArrayLike, size: int, name: str) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise TypeError(f"{name} must be real-valued")
    vector = np.asarray(raw, dtype=np.float64)
    if vector.shape != (size,):
        raise ValueError(f"{name} must have shape ({size},)")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must contain only finite values")
    owned = vector.copy()
    owned.setflags(write=False)
    return owned


def _matrix(value: ArrayLike, shape: tuple[int, int], name: str) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise TypeError(f"{name} must be real-valued")
    matrix = np.asarray(raw, dtype=np.float64)
    if matrix.shape != shape:
        raise ValueError(f"{name} must have shape {shape}")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"{name} must contain only finite values")
    owned = matrix.copy()
    owned.setflags(write=False)
    return owned


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a JSON object")
    if not all(isinstance(key, str) for key in value):
        raise TypeError(f"{name} keys must be strings")
    return value


def _require_exact_keys(
    value: Mapping[str, object], expected: frozenset[str], name: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"{name} keys mismatch; missing={missing}, extra={extra}")


def _quantile_mapping(value: object, name: str) -> Mapping[int, float]:
    """Validate and freeze a one-based horizon-to-q95 mapping."""

    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    quantiles: dict[int, float] = {}
    for horizon, raw_quantile in value.items():
        normalized_horizon = _integer(horizon, "prediction horizon", minimum=1)
        if normalized_horizon in quantiles:
            raise ValueError("prediction horizons must be unique")
        quantiles[normalized_horizon] = _nonnegative_real(raw_quantile, name)
    return MappingProxyType(dict(sorted(quantiles.items())))


def _quantile_mapping_from_json(value: object, name: str) -> Mapping[int, object]:
    mapping = _mapping(value, name)
    quantiles: dict[int, object] = {}
    for raw_horizon, quantile in mapping.items():
        if not raw_horizon.isdigit() or raw_horizon.startswith("0"):
            raise ValueError("prediction horizon keys must be canonical positive integers")
        quantiles[int(raw_horizon)] = quantile
    return quantiles


@dataclass(frozen=True, slots=True)
class FeatureScalerState:
    """Serializable eight-dimensional training StandardScaler state."""

    mean: FloatArray
    scale: FloatArray
    variance: FloatArray
    n_samples_seen: int

    def __post_init__(self) -> None:
        mean = _vector(self.mean, FEATURE_DIMENSION, "mean")
        scale = _vector(self.scale, FEATURE_DIMENSION, "scale")
        variance = _vector(self.variance, FEATURE_DIMENSION, "variance")
        if np.any(scale <= 0.0):
            raise ValueError("feature scale entries must be strictly positive")
        if np.any(variance < 0.0):
            raise ValueError("feature variance entries must be non-negative")
        count = _integer(self.n_samples_seen, "n_samples_seen", minimum=1)
        object.__setattr__(self, "mean", mean)
        object.__setattr__(self, "scale", scale)
        object.__setattr__(self, "variance", variance)
        object.__setattr__(self, "n_samples_seen", count)

    def transform(self, features: ArrayLike) -> FloatArray:
        raw = np.asarray(features)
        if np.iscomplexobj(raw):
            raise TypeError("features must be real-valued")
        values = np.asarray(raw, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != FEATURE_DIMENSION:
            raise ValueError(f"features must have shape (n, {FEATURE_DIMENSION})")
        if not np.all(np.isfinite(values)):
            raise ValueError("features must contain only finite values")
        return np.asarray((values - self.mean) / self.scale, dtype=np.float64)

    def to_dict(self) -> dict[str, object]:
        return {
            "mean": self.mean.tolist(),
            "scale": self.scale.tolist(),
            "variance": self.variance.tolist(),
            "n_samples_seen": self.n_samples_seen,
        }

    @classmethod
    def from_dict(cls, value: object) -> "FeatureScalerState":
        mapping = _mapping(value, "feature_scaler")
        _require_exact_keys(mapping, _SCALER_KEYS, "feature_scaler")
        return cls(
            mean=mapping["mean"],
            scale=mapping["scale"],
            variance=mapping["variance"],
            n_samples_seen=mapping["n_samples_seen"],
        )


@dataclass(frozen=True, slots=True)
class BICRecord:
    component_count: int
    bic: float | None
    delta_bic: float | None
    converged: bool
    iterations: int
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        count = _integer(self.component_count, "component_count", minimum=1)
        iterations = _integer(self.iterations, "iterations", minimum=0)
        if not isinstance(self.converged, (bool, np.bool_)):
            raise TypeError("converged must be boolean")
        bic = None if self.bic is None else _finite_real(self.bic, "bic")
        delta = (
            None if self.delta_bic is None else _nonnegative_real(self.delta_bic, "delta_bic")
        )
        reason = self.failure_reason
        if reason is not None:
            reason = str(reason).strip()
            if not reason:
                raise ValueError("failure_reason must be non-empty when supplied")
        if reason is None and (bic is None or delta is None):
            raise ValueError("successful BIC records require bic and delta_bic")
        if reason is not None and (bic is not None or delta is not None or self.converged):
            raise ValueError("failed BIC records cannot contain scores or convergence")
        object.__setattr__(self, "component_count", count)
        object.__setattr__(self, "bic", bic)
        object.__setattr__(self, "delta_bic", delta)
        object.__setattr__(self, "converged", bool(self.converged))
        object.__setattr__(self, "iterations", iterations)
        object.__setattr__(self, "failure_reason", reason)

    def to_dict(self) -> dict[str, object]:
        return {
            "component_count": self.component_count,
            "bic": self.bic,
            "delta_bic": self.delta_bic,
            "converged": self.converged,
            "iterations": self.iterations,
            "failure_reason": self.failure_reason,
        }

    @classmethod
    def from_dict(cls, value: object) -> "BICRecord":
        mapping = _mapping(value, "bic_table entry")
        _require_exact_keys(mapping, _BIC_KEYS, "bic_table entry")
        return cls(**mapping)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class DiscoveryMetadata:
    """Only label-free fitting metadata permitted in the persisted library."""

    selected_k: int
    candidate_k_min: int
    candidate_k_max: int
    covariance_type: str
    n_init: int
    random_seed: int
    bic_table: tuple[BICRecord, ...]

    def __post_init__(self) -> None:
        selected = _integer(self.selected_k, "selected_k", minimum=1)
        minimum = _integer(self.candidate_k_min, "candidate_k_min", minimum=1)
        maximum = _integer(self.candidate_k_max, "candidate_k_max", minimum=1)
        if minimum > maximum or not minimum <= selected <= maximum:
            raise ValueError("candidate K range must contain selected_k")
        covariance = str(self.covariance_type)
        if covariance not in {"full", "tied", "diag", "spherical"}:
            raise ValueError("unsupported covariance_type")
        restarts = _integer(self.n_init, "n_init", minimum=2)
        seed = _integer(self.random_seed, "random_seed", minimum=0)
        records = tuple(self.bic_table)
        expected_counts = tuple(range(minimum, maximum + 1))
        if tuple(record.component_count for record in records) != expected_counts:
            raise ValueError("bic_table must contain the complete ordered candidate K range")
        selected_records = [record for record in records if record.component_count == selected]
        if len(selected_records) != 1 or selected_records[0].bic is None:
            raise ValueError("selected_k must have a successful BIC record")
        successful = [record for record in records if record.bic is not None]
        if not successful:
            raise ValueError("bic_table must contain at least one successful candidate")
        best = min(successful, key=lambda record: (float(record.bic), record.component_count))
        if best.component_count != selected:
            raise ValueError("selected_k must minimize BIC")
        object.__setattr__(self, "selected_k", selected)
        object.__setattr__(self, "candidate_k_min", minimum)
        object.__setattr__(self, "candidate_k_max", maximum)
        object.__setattr__(self, "covariance_type", covariance)
        object.__setattr__(self, "n_init", restarts)
        object.__setattr__(self, "random_seed", seed)
        object.__setattr__(self, "bic_table", records)

    def to_dict(self) -> dict[str, object]:
        return {
            "selected_k": self.selected_k,
            "candidate_k_min": self.candidate_k_min,
            "candidate_k_max": self.candidate_k_max,
            "covariance_type": self.covariance_type,
            "n_init": self.n_init,
            "random_seed": self.random_seed,
            "bic_table": [record.to_dict() for record in self.bic_table],
        }

    @classmethod
    def from_dict(cls, value: object) -> "DiscoveryMetadata":
        mapping = _mapping(value, "discovery_metadata")
        _require_exact_keys(mapping, _DISCOVERY_KEYS, "discovery_metadata")
        table = mapping["bic_table"]
        if not isinstance(table, list):
            raise TypeError("bic_table must be a JSON array")
        return cls(
            selected_k=mapping["selected_k"],
            candidate_k_min=mapping["candidate_k_min"],
            candidate_k_max=mapping["candidate_k_max"],
            covariance_type=mapping["covariance_type"],
            n_init=mapping["n_init"],
            random_seed=mapping["random_seed"],
            bic_table=tuple(BICRecord.from_dict(record) for record in table),
        )


@dataclass(frozen=True, slots=True)
class ARXModeModel:
    """One discovered component's ARX predictor and observed capabilities."""

    component_id: int
    theta: FloatArray
    residual_variance: float
    multi_step_power_error_quantiles_pu: Mapping[int, float]
    multi_step_frequency_error_quantiles_hz: Mapping[int, float]
    multi_step_rocof_error_quantiles_hz_per_s: Mapping[int, float]
    p_output_min_pu: float
    p_output_max_pu: float
    ramp_down_pu_per_s: float
    ramp_up_pu_per_s: float
    training_episode_count: int
    training_sample_count: int

    def __post_init__(self) -> None:
        component = _integer(self.component_id, "component_id", minimum=0)
        theta = _vector(self.theta, ARX_PARAMETER_COUNT, "theta")
        residual_variance = _positive_real(self.residual_variance, "residual_variance")
        power_quantiles = _quantile_mapping(
            self.multi_step_power_error_quantiles_pu,
            "multi_step_power_error_quantiles_pu",
        )
        frequency_quantiles = _quantile_mapping(
            self.multi_step_frequency_error_quantiles_hz,
            "multi_step_frequency_error_quantiles_hz",
        )
        rocof_quantiles = _quantile_mapping(
            self.multi_step_rocof_error_quantiles_hz_per_s,
            "multi_step_rocof_error_quantiles_hz_per_s",
        )
        if not (
            tuple(power_quantiles)
            == tuple(frequency_quantiles)
            == tuple(rocof_quantiles)
        ):
            raise ValueError(
                "power, frequency, and RoCoF quantiles must use identical horizons"
            )
        lower = _finite_real(self.p_output_min_pu, "p_output_min_pu")
        upper = _finite_real(self.p_output_max_pu, "p_output_max_pu")
        if lower > upper:
            raise ValueError("p_output_min_pu must not exceed p_output_max_pu")
        down = _nonnegative_real(self.ramp_down_pu_per_s, "ramp_down_pu_per_s")
        up = _nonnegative_real(self.ramp_up_pu_per_s, "ramp_up_pu_per_s")
        episode_count = _integer(
            self.training_episode_count, "training_episode_count", minimum=1
        )
        sample_count = _integer(
            self.training_sample_count, "training_sample_count", minimum=1
        )
        object.__setattr__(self, "component_id", component)
        object.__setattr__(self, "theta", theta)
        object.__setattr__(self, "residual_variance", residual_variance)
        object.__setattr__(
            self,
            "multi_step_power_error_quantiles_pu",
            power_quantiles,
        )
        object.__setattr__(
            self,
            "multi_step_frequency_error_quantiles_hz",
            frequency_quantiles,
        )
        object.__setattr__(
            self,
            "multi_step_rocof_error_quantiles_hz_per_s",
            rocof_quantiles,
        )
        object.__setattr__(self, "p_output_min_pu", lower)
        object.__setattr__(self, "p_output_max_pu", upper)
        object.__setattr__(self, "ramp_down_pu_per_s", down)
        object.__setattr__(self, "ramp_up_pu_per_s", up)
        object.__setattr__(self, "training_episode_count", episode_count)
        object.__setattr__(self, "training_sample_count", sample_count)

    @property
    def mode_id(self) -> int:
        """Compatibility alias; it remains the native component identifier."""

        return self.component_id

    @property
    def multi_step_error_quantiles(self) -> Mapping[int, float]:
        """Read-only v1 compatibility alias, explicitly frequency q95 in Hz."""

        return self.multi_step_frequency_error_quantiles_hz

    @property
    def A_b(self) -> FloatArray:
        a1, a2, _, b1, _, c1, intercept = self.theta
        return np.array(
            [
                [a1, a2, b1, c1, intercept],
                [1.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )

    @property
    def B_b(self) -> FloatArray:
        return np.array(
            [[self.theta[2]], [0.0], [1.0], [0.0], [0.0]], dtype=np.float64
        )

    @property
    def F_b(self) -> FloatArray:
        return np.array(
            [[self.theta[4]], [0.0], [0.0], [1.0], [0.0]], dtype=np.float64
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "theta": self.theta.tolist(),
            "residual_variance": self.residual_variance,
            "multi_step_power_error_quantiles_pu": {
                str(horizon): value
                for horizon, value in self.multi_step_power_error_quantiles_pu.items()
            },
            "multi_step_frequency_error_quantiles_hz": {
                str(horizon): value
                for horizon, value in self.multi_step_frequency_error_quantiles_hz.items()
            },
            "multi_step_rocof_error_quantiles_hz_per_s": {
                str(horizon): value
                for horizon, value in self.multi_step_rocof_error_quantiles_hz_per_s.items()
            },
            "p_output_min_pu": self.p_output_min_pu,
            "p_output_max_pu": self.p_output_max_pu,
            "ramp_down_pu_per_s": self.ramp_down_pu_per_s,
            "ramp_up_pu_per_s": self.ramp_up_pu_per_s,
            "training_episode_count": self.training_episode_count,
            "training_sample_count": self.training_sample_count,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ARXModeModel":
        mapping = _mapping(value, "model")
        _require_exact_keys(mapping, _MODEL_KEYS, "model")
        return cls(
            component_id=mapping["component_id"],
            theta=mapping["theta"],
            residual_variance=mapping["residual_variance"],
            multi_step_power_error_quantiles_pu=_quantile_mapping_from_json(
                mapping["multi_step_power_error_quantiles_pu"],
                "multi_step_power_error_quantiles_pu",
            ),
            multi_step_frequency_error_quantiles_hz=_quantile_mapping_from_json(
                mapping["multi_step_frequency_error_quantiles_hz"],
                "multi_step_frequency_error_quantiles_hz",
            ),
            multi_step_rocof_error_quantiles_hz_per_s=_quantile_mapping_from_json(
                mapping["multi_step_rocof_error_quantiles_hz_per_s"],
                "multi_step_rocof_error_quantiles_hz_per_s",
            ),
            p_output_min_pu=mapping["p_output_min_pu"],
            p_output_max_pu=mapping["p_output_max_pu"],
            ramp_down_pu_per_s=mapping["ramp_down_pu_per_s"],
            ramp_up_pu_per_s=mapping["ramp_up_pu_per_s"],
            training_episode_count=mapping["training_episode_count"],
            training_sample_count=mapping["training_sample_count"],
        )


def sticky_transition_matrix(component_count: int, stay_probability: float = 0.98) -> FloatArray:
    """Build a symmetric sticky row-stochastic prior without component relabeling."""

    count = _integer(component_count, "component_count", minimum=1)
    stay = _finite_real(stay_probability, "stay_probability")
    if not 0.0 <= stay <= 1.0:
        raise ValueError("stay_probability must lie in [0, 1]")
    if count == 1:
        return np.ones((1, 1), dtype=np.float64)
    transition = np.full((count, count), (1.0 - stay) / (count - 1), dtype=np.float64)
    np.fill_diagonal(transition, stay)
    return transition


@dataclass(frozen=True, slots=True)
class ModeLibrary:
    models: tuple[ARXModeModel, ...]
    transition_matrix: FloatArray
    feature_scaler: FeatureScalerState
    discovery_metadata: DiscoveryMetadata
    schema_version: str = MODE_LIBRARY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODE_LIBRARY_SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {MODE_LIBRARY_SCHEMA_VERSION!r}")
        models = tuple(self.models)
        if len(models) == 0 or not all(isinstance(model, ARXModeModel) for model in models):
            raise TypeError("models must be a non-empty sequence of ARXModeModel")
        component_ids = tuple(model.component_id for model in models)
        if component_ids != tuple(range(len(models))):
            raise ValueError("models must retain contiguous native component IDs in order")
        transition = _matrix(
            self.transition_matrix,
            (len(models), len(models)),
            "transition_matrix",
        )
        if np.any(transition < 0.0):
            raise ValueError("transition_matrix entries must be non-negative")
        if not np.allclose(transition.sum(axis=1), 1.0, rtol=0.0, atol=1.0e-12):
            raise ValueError("transition_matrix rows must sum to one")
        if not isinstance(self.feature_scaler, FeatureScalerState):
            raise TypeError("feature_scaler must be a FeatureScalerState")
        if not isinstance(self.discovery_metadata, DiscoveryMetadata):
            raise TypeError("discovery_metadata must be DiscoveryMetadata")
        if self.discovery_metadata.selected_k != len(models):
            raise ValueError("selected_k must equal the number of models")
        object.__setattr__(self, "models", models)
        object.__setattr__(self, "transition_matrix", transition)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "models": [model.to_dict() for model in self.models],
            "transition_matrix": self.transition_matrix.tolist(),
            "feature_scaler": self.feature_scaler.to_dict(),
            "discovery_metadata": self.discovery_metadata.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> "ModeLibrary":
        mapping = _mapping(value, "mode library")
        _require_exact_keys(mapping, _TOP_LEVEL_KEYS, "mode library")
        raw_models = mapping["models"]
        if not isinstance(raw_models, list):
            raise TypeError("models must be a JSON array")
        return cls(
            schema_version=mapping["schema_version"],
            models=tuple(ARXModeModel.from_dict(model) for model in raw_models),
            transition_matrix=mapping["transition_matrix"],
            feature_scaler=FeatureScalerState.from_dict(mapping["feature_scaler"]),
            discovery_metadata=DiscoveryMetadata.from_dict(mapping["discovery_metadata"]),
        )

    def save_json(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        payload = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        temporary.write_text(payload + "\n", encoding="utf-8", newline="\n")
        temporary.replace(destination)

    @classmethod
    def load_json(cls, path: str | Path) -> "ModeLibrary":
        def reject_nonfinite(token: str) -> None:
            raise ValueError(f"non-standard non-finite JSON value {token!r} is forbidden")

        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            parse_constant=reject_nonfinite,
        )
        return cls.from_dict(payload)


def mode_library_from_discovery(
    mode_models: Sequence[object],
    *,
    feature_scaler: object,
    discovery_metadata: DiscoveryMetadata,
    multi_step_power_error_quantiles_pu: Mapping[
        int, Mapping[int, float]
    ] | None = None,
    multi_step_frequency_error_quantiles_hz: Mapping[
        int, Mapping[int, float]
    ] | None = None,
    multi_step_rocof_error_quantiles_hz_per_s: Mapping[
        int, Mapping[int, float]
    ] | None = None,
    stay_probability: float = 0.98,
) -> ModeLibrary:
    """Convert label-free discovery records to the strict persisted library."""

    scaler = FeatureScalerState(
        mean=getattr(feature_scaler, "mean"),
        scale=getattr(feature_scaler, "scale"),
        variance=getattr(feature_scaler, "variance"),
        n_samples_seen=getattr(feature_scaler, "n_samples_seen"),
    )
    power_quantiles_by_component = multi_step_power_error_quantiles_pu or {}
    frequency_quantiles_by_component = multi_step_frequency_error_quantiles_hz or {}
    rocof_quantiles_by_component = (
        multi_step_rocof_error_quantiles_hz_per_s or {}
    )
    models: list[ARXModeModel] = []
    for discovered in mode_models:
        component_id = int(getattr(discovered, "component_id"))
        capability = getattr(discovered, "capability")
        models.append(
            ARXModeModel(
                component_id=component_id,
                theta=getattr(discovered, "theta"),
                residual_variance=getattr(discovered, "residual_variance"),
                multi_step_power_error_quantiles_pu=power_quantiles_by_component.get(
                    component_id, {}
                ),
                multi_step_frequency_error_quantiles_hz=(
                    frequency_quantiles_by_component.get(component_id, {})
                ),
                multi_step_rocof_error_quantiles_hz_per_s=(
                    rocof_quantiles_by_component.get(component_id, {})
                ),
                p_output_min_pu=getattr(capability, "p_output_min_pu"),
                p_output_max_pu=getattr(capability, "p_output_max_pu"),
                ramp_down_pu_per_s=getattr(capability, "ramp_down_pu_per_s"),
                ramp_up_pu_per_s=getattr(capability, "ramp_up_pu_per_s"),
                training_episode_count=getattr(discovered, "training_episode_count"),
                training_sample_count=getattr(discovered, "training_sample_count"),
            )
        )
    return ModeLibrary(
        models=tuple(models),
        transition_matrix=sticky_transition_matrix(
            len(models), stay_probability=stay_probability
        ),
        feature_scaler=scaler,
        discovery_metadata=discovery_metadata,
    )


def discovery_metadata_from_selection(
    selection: object,
    *,
    random_seed: int,
) -> DiscoveryMetadata:
    """Build strict persistence metadata from a GMM selection result."""

    scores = tuple(getattr(selection, "candidate_scores"))
    if not scores:
        raise ValueError("selection candidate_scores must not be empty")
    model = getattr(selection, "model")
    records = tuple(
        BICRecord(
            component_count=getattr(score, "component_count"),
            bic=getattr(score, "bic"),
            delta_bic=getattr(score, "delta_bic"),
            converged=getattr(score, "converged"),
            iterations=getattr(score, "iterations"),
            failure_reason=getattr(score, "failure_reason"),
        )
        for score in scores
    )
    return DiscoveryMetadata(
        selected_k=getattr(selection, "selected_k"),
        candidate_k_min=records[0].component_count,
        candidate_k_max=records[-1].component_count,
        covariance_type=getattr(model, "covariance_type"),
        n_init=getattr(model, "n_init"),
        random_seed=random_seed,
        bic_table=records,
    )


__all__ = [
    "ARXModeModel",
    "BICRecord",
    "DiscoveryMetadata",
    "FeatureScalerState",
    "MODE_LIBRARY_SCHEMA_VERSION",
    "ModeLibrary",
    "discovery_metadata_from_selection",
    "mode_library_from_discovery",
    "sticky_transition_matrix",
]
