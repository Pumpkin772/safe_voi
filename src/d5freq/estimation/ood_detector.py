"""Split-conformal OOD detection for controller-visible ARX residuals.

Equations (48)--(51) define the nonconformity score and p-value.  This
module deliberately accepts residuals and innovation variances only; neither
the detector nor its runtime result has a true-mode input or field.

The four-state hysteresis machine follows the state diagram in the Phase 4
specification literally:

* ``KNOWN`` enters ``SUSPECT`` on the ``L_on``-th consecutive observation
  with ``p < alpha_on``;
* ``SUSPECT`` enters ``OOD_ACTIVE`` on the next continuing low observation,
  returns to ``KNOWN`` on ``p > alpha_off``, and otherwise stays suspect;
* ``OOD_ACTIVE`` enters ``RECOVERY`` on the ``L_off``-th consecutive
  observation with ``p > alpha_off``;
* ``RECOVERY`` returns to ``KNOWN`` on the next continuing high observation,
  returns immediately to ``OOD_ACTIVE`` on ``p < alpha_on``, and otherwise
  remains in recovery.

Both comparisons are strict, as in equation (51) and the specification.
Values in the closed hysteresis band ``[alpha_on, alpha_off]`` therefore do
not advance either confirmation counter.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from numbers import Integral, Real
import re
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray


FloatArray = NDArray[np.float64]
OOD_CALIBRATION_SCHEMA_VERSION = "d5freq.ood_calibration.v2"
OOD_CALIBRATION_SPLIT = "ood_calibration"
KNOWN_MODE_POPULATION = "known_modes_only"
OOD_SCORE_DEFINITION = "min_m_abs_residual_over_sqrt_S_m"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_ARTIFACT_KEYS = frozenset(
    {
        "schema_version",
        "calibration_scores",
        "source_split",
        "source_population",
        "dataset_sha256",
        "split_manifest_sha256",
        "mode_library_sha256",
        "mode_library_logical_sha256",
        "source_trajectory_sha256",
        "known_component_ids",
        "covered_component_ids",
        "measurement_noise_variance_pu2",
        "variance_floor_pu2",
        "score_definition",
    }
)


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _positive_real(value: object, name: str) -> float:
    normalized = _finite_real(value, name)
    if normalized <= 0.0:
        raise ValueError(f"{name} must be strictly positive")
    return normalized


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized <= 0:
        raise ValueError(f"{name} must be strictly positive")
    return normalized


def _finite_vector(value: ArrayLike, name: str, *, nonnegative: bool) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise TypeError(f"{name} must be real-valued")
    try:
        vector = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real-valued vector") from exc
    if vector.ndim != 1 or vector.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional vector")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must contain only finite values")
    if nonnegative and np.any(vector < 0.0):
        raise ValueError(f"{name} must be non-negative")
    return vector.copy()


def _residual_matrix(value: ArrayLike) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise TypeError("residuals must be real-valued")
    try:
        matrix = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TypeError("residuals must be a real-valued matrix") from exc
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        raise ValueError("residuals must have shape (n_samples, n_modes), both nonzero")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("residuals must contain only finite values")
    return matrix.copy()


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _sha256_sequence(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence of SHA-256 digests")
    hashes = tuple(_sha256(item, f"{name}[{index}]") for index, item in enumerate(value))
    if not hashes:
        raise ValueError(f"{name} must be non-empty")
    if len(set(hashes)) != len(hashes):
        raise ValueError(f"{name} must not contain duplicates")
    return hashes


def _component_ids(value: object, name: str) -> tuple[int, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence of component IDs")
    identifiers: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, (bool, np.bool_)) or not isinstance(item, Integral):
            raise TypeError(f"{name}[{index}] must be an integer")
        identifier = int(item)
        if identifier < 0:
            raise ValueError(f"{name}[{index}] must be non-negative")
        identifiers.append(identifier)
    if not identifiers:
        raise ValueError(f"{name} must be non-empty")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(identifiers)


def minimum_standardized_residual_score(
    residuals: ArrayLike,
    innovation_variances: ArrayLike,
    *,
    variance_floor: float = 1.0e-12,
) -> float:
    """Return the equation-(48)/(49) minimum standardized residual.

    ``innovation_variances`` contains the complete ``S_m`` values, including
    measurement variance.  A strictly positive floor is applied only after
    validating that supplied variances are finite and non-negative.
    """

    residual = _finite_vector(residuals, "residuals", nonnegative=False)
    variances = _finite_vector(
        innovation_variances, "innovation_variances", nonnegative=True
    )
    if residual.shape != variances.shape:
        raise ValueError("residuals and innovation_variances must have equal shape")
    floor = _positive_real(variance_floor, "variance_floor")
    denominators = np.sqrt(np.maximum(variances, floor))
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        standardized = np.abs(residual) / denominators
    if not np.all(np.isfinite(standardized)):
        raise FloatingPointError("standardized residual became non-finite")
    return float(np.min(standardized))


def calibration_scores_from_residuals(
    residuals: ArrayLike,
    innovation_variances: ArrayLike,
    *,
    variance_floor: float = 1.0e-12,
) -> FloatArray:
    """Compute one equation-(48) score for every calibration observation."""

    matrix = _residual_matrix(residuals)
    variances = _finite_vector(
        innovation_variances, "innovation_variances", nonnegative=True
    )
    if matrix.shape[1] != variances.size:
        raise ValueError("innovation_variances must have one entry per mode")
    floor = _positive_real(variance_floor, "variance_floor")
    denominators = np.sqrt(np.maximum(variances, floor))[None, :]
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        standardized = np.abs(matrix) / denominators
    if not np.all(np.isfinite(standardized)):
        raise FloatingPointError("standardized calibration residual became non-finite")
    return np.asarray(np.min(standardized, axis=1), dtype=np.float64)


def split_conformal_pvalue(runtime_score: float, calibration_scores: ArrayLike) -> float:
    """Return equation-(50) p-value, including all calibration ties."""

    score = _finite_real(runtime_score, "runtime_score")
    if score < 0.0:
        raise ValueError("runtime_score must be non-negative")
    calibration = _finite_vector(
        calibration_scores, "calibration_scores", nonnegative=True
    )
    greater_or_equal = int(np.count_nonzero(calibration >= score))
    return float((1 + greater_or_equal) / (calibration.size + 1))


@dataclass(frozen=True, slots=True)
class OODCalibrationArtifact:
    """Serializable, provenance-bound known-mode conformal calibration.

    The exact split/population sentinels reject artifacts assembled from the
    held-out test split or from OOD regimes.  ``covered_component_ids`` must
    cover every native discovered component in ``known_component_ids``; no
    private reference-mode labels are stored.
    """

    calibration_scores: Sequence[float]
    dataset_sha256: str
    split_manifest_sha256: str
    mode_library_sha256: str
    mode_library_logical_sha256: str
    source_trajectory_sha256: Sequence[str]
    known_component_ids: Sequence[int]
    covered_component_ids: Sequence[int]
    measurement_noise_variance_pu2: float
    variance_floor_pu2: float
    schema_version: str = OOD_CALIBRATION_SCHEMA_VERSION
    source_split: str = OOD_CALIBRATION_SPLIT
    source_population: str = KNOWN_MODE_POPULATION
    score_definition: str = OOD_SCORE_DEFINITION

    def __post_init__(self) -> None:
        if self.schema_version != OOD_CALIBRATION_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {OOD_CALIBRATION_SCHEMA_VERSION!r}"
            )
        if self.source_split != OOD_CALIBRATION_SPLIT:
            raise ValueError(
                "source_split must be 'ood_calibration'; train, validation, "
                "test, and runtime OOD data are forbidden"
            )
        if self.source_population != KNOWN_MODE_POPULATION:
            raise ValueError("source_population must attest known modes only")
        if self.score_definition != OOD_SCORE_DEFINITION:
            raise ValueError(
                f"score_definition must equal {OOD_SCORE_DEFINITION!r}"
            )

        scores = _finite_vector(
            self.calibration_scores, "calibration_scores", nonnegative=True
        )
        score_tuple = tuple(float(value) for value in scores)
        trajectories = _sha256_sequence(
            self.source_trajectory_sha256, "source_trajectory_sha256"
        )
        known = _component_ids(self.known_component_ids, "known_component_ids")
        covered = _component_ids(
            self.covered_component_ids, "covered_component_ids"
        )
        if set(covered) != set(known):
            raise ValueError(
                "covered_component_ids must cover every and only known component"
            )

        object.__setattr__(self, "calibration_scores", score_tuple)
        object.__setattr__(
            self, "dataset_sha256", _sha256(self.dataset_sha256, "dataset_sha256")
        )
        object.__setattr__(
            self,
            "split_manifest_sha256",
            _sha256(self.split_manifest_sha256, "split_manifest_sha256"),
        )
        object.__setattr__(
            self,
            "mode_library_sha256",
            _sha256(self.mode_library_sha256, "mode_library_sha256"),
        )
        object.__setattr__(
            self,
            "mode_library_logical_sha256",
            _sha256(
                self.mode_library_logical_sha256,
                "mode_library_logical_sha256",
            ),
        )
        object.__setattr__(self, "source_trajectory_sha256", trajectories)
        object.__setattr__(self, "known_component_ids", known)
        object.__setattr__(self, "covered_component_ids", covered)
        object.__setattr__(
            self,
            "measurement_noise_variance_pu2",
            _finite_real(
                self.measurement_noise_variance_pu2,
                "measurement_noise_variance_pu2",
            ),
        )
        if self.measurement_noise_variance_pu2 < 0.0:
            raise ValueError("measurement_noise_variance_pu2 must be non-negative")
        object.__setattr__(
            self,
            "variance_floor_pu2",
            _positive_real(self.variance_floor_pu2, "variance_floor_pu2"),
        )

    def assert_disjoint_from(
        self,
        *,
        test_trajectory_sha256: Sequence[str],
        ood_trajectory_sha256: Sequence[str],
    ) -> None:
        """Reject any calibration hash reused by test or OOD episodes."""

        test_hashes = _sha256_sequence(
            test_trajectory_sha256, "test_trajectory_sha256"
        )
        ood_hashes = _sha256_sequence(
            ood_trajectory_sha256, "ood_trajectory_sha256"
        )
        calibration = set(self.source_trajectory_sha256)
        if calibration.intersection(test_hashes):
            raise ValueError("calibration and test trajectory hashes overlap")
        if calibration.intersection(ood_hashes):
            raise ValueError("calibration and OOD trajectory hashes overlap")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable dictionary with a strict schema."""

        return {
            "schema_version": self.schema_version,
            "calibration_scores": list(self.calibration_scores),
            "source_split": self.source_split,
            "source_population": self.source_population,
            "dataset_sha256": self.dataset_sha256,
            "split_manifest_sha256": self.split_manifest_sha256,
            "mode_library_sha256": self.mode_library_sha256,
            "mode_library_logical_sha256": self.mode_library_logical_sha256,
            "source_trajectory_sha256": list(self.source_trajectory_sha256),
            "known_component_ids": list(self.known_component_ids),
            "covered_component_ids": list(self.covered_component_ids),
            "measurement_noise_variance_pu2": self.measurement_noise_variance_pu2,
            "variance_floor_pu2": self.variance_floor_pu2,
            "score_definition": self.score_definition,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OODCalibrationArtifact":
        """Load a strict artifact dictionary, rejecting missing/extra fields."""

        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        fields = frozenset(payload)
        if fields != _ARTIFACT_KEYS:
            missing = sorted(_ARTIFACT_KEYS - fields)
            extra = sorted(fields - _ARTIFACT_KEYS)
            raise ValueError(
                f"calibration artifact fields mismatch; missing={missing}, extra={extra}"
            )
        return cls(
            calibration_scores=payload["calibration_scores"],
            dataset_sha256=payload["dataset_sha256"],
            split_manifest_sha256=payload["split_manifest_sha256"],
            mode_library_sha256=payload["mode_library_sha256"],
            mode_library_logical_sha256=payload[
                "mode_library_logical_sha256"
            ],
            source_trajectory_sha256=payload["source_trajectory_sha256"],
            known_component_ids=payload["known_component_ids"],
            covered_component_ids=payload["covered_component_ids"],
            measurement_noise_variance_pu2=payload[
                "measurement_noise_variance_pu2"
            ],
            variance_floor_pu2=payload["variance_floor_pu2"],
            schema_version=payload["schema_version"],
            source_split=payload["source_split"],
            source_population=payload["source_population"],
            score_definition=payload["score_definition"],
        )


@dataclass(frozen=True, slots=True)
class OODDetectorConfig:
    """Validated thresholds and confirmation lengths for equation (51)."""

    alpha_on: float = 0.01
    alpha_off: float = 0.10
    L_on: int = 3
    L_off: int = 5
    variance_floor: float = 1.0e-12

    def __post_init__(self) -> None:
        alpha_on = _finite_real(self.alpha_on, "alpha_on")
        alpha_off = _finite_real(self.alpha_off, "alpha_off")
        if not 0.0 < alpha_on < alpha_off < 1.0:
            raise ValueError("thresholds must satisfy 0 < alpha_on < alpha_off < 1")
        object.__setattr__(self, "alpha_on", alpha_on)
        object.__setattr__(self, "alpha_off", alpha_off)
        object.__setattr__(self, "L_on", _positive_integer(self.L_on, "L_on"))
        object.__setattr__(self, "L_off", _positive_integer(self.L_off, "L_off"))
        object.__setattr__(
            self,
            "variance_floor",
            _positive_real(self.variance_floor, "variance_floor"),
        )


class OODState(str, Enum):
    """Controller-visible diagnostic state."""

    KNOWN = "KNOWN"
    SUSPECT = "SUSPECT"
    OOD_ACTIVE = "OOD_ACTIVE"
    RECOVERY = "RECOVERY"


@dataclass(frozen=True, slots=True)
class OODStateUpdate:
    """One immutable p-value/state-machine update."""

    previous_state: OODState
    state: OODState
    ood_pvalue: float
    low_count: int
    high_count: int

    @property
    def ood_active(self) -> bool:
        """Whether the specification requires active OOD fallback now."""

        return self.state is OODState.OOD_ACTIVE


class OODHysteresisStateMachine:
    """Deterministic four-state machine with explicit confirmation counters."""

    __slots__ = ("_config", "_state", "_low_count", "_high_count")

    def __init__(self, config: OODDetectorConfig | None = None) -> None:
        if config is not None and not isinstance(config, OODDetectorConfig):
            raise TypeError("config must be an OODDetectorConfig")
        self._config = OODDetectorConfig() if config is None else config
        self.reset()

    @property
    def config(self) -> OODDetectorConfig:
        return self._config

    @property
    def state(self) -> OODState:
        return self._state

    @property
    def low_count(self) -> int:
        return self._low_count

    @property
    def high_count(self) -> int:
        return self._high_count

    @property
    def ood_active(self) -> bool:
        return self._state is OODState.OOD_ACTIVE

    def reset(self) -> None:
        """Return to ``KNOWN`` and clear both consecutive-step counters."""

        self._state = OODState.KNOWN
        self._low_count = 0
        self._high_count = 0

    def update(self, ood_pvalue: float) -> OODStateUpdate:
        """Advance exactly one sample using strict on/off comparisons."""

        pvalue = _finite_real(ood_pvalue, "ood_pvalue")
        if not 0.0 <= pvalue <= 1.0:
            raise ValueError("ood_pvalue must lie in [0, 1]")
        previous = self._state
        low = pvalue < self._config.alpha_on
        high = pvalue > self._config.alpha_off

        if previous is OODState.KNOWN:
            self._high_count = 0
            self._low_count = self._low_count + 1 if low else 0
            if self._low_count >= self._config.L_on:
                self._state = OODState.SUSPECT
        elif previous is OODState.SUSPECT:
            self._high_count = 0
            if low:
                self._low_count += 1
                self._state = OODState.OOD_ACTIVE
                self._low_count = 0
            elif high:
                self._state = OODState.KNOWN
                self._low_count = 0
            # A hysteresis-band value leaves SUSPECT and its low count intact.
        elif previous is OODState.OOD_ACTIVE:
            self._low_count = 0
            self._high_count = self._high_count + 1 if high else 0
            if self._high_count >= self._config.L_off:
                self._state = OODState.RECOVERY
        else:  # OODState.RECOVERY
            self._low_count = 0
            if low:
                self._state = OODState.OOD_ACTIVE
                self._high_count = 0
            elif high:
                self._state = OODState.KNOWN
                self._high_count = 0
            # A hysteresis-band value leaves RECOVERY/high count intact.

        return OODStateUpdate(
            previous_state=previous,
            state=self._state,
            ood_pvalue=pvalue,
            low_count=self._low_count,
            high_count=self._high_count,
        )


@dataclass(frozen=True, slots=True)
class OODDetection:
    """One runtime detector output containing controller-visible values only."""

    step_index: int
    ood_score: float
    ood_pvalue: float
    previous_state: OODState
    diagnostic_state: OODState
    low_count: int
    high_count: int

    @property
    def ood_active(self) -> bool:
        return self.diagnostic_state is OODState.OOD_ACTIVE


class ConformalOODDetector:
    """Equation-(48)--(51) scorer, conformal calibrator, and state machine."""

    __slots__ = ("_artifact", "_config", "_machine", "_step_index")

    def __init__(
        self,
        calibration_artifact: OODCalibrationArtifact,
        config: OODDetectorConfig | None = None,
    ) -> None:
        if not isinstance(calibration_artifact, OODCalibrationArtifact):
            raise TypeError("calibration_artifact must be an OODCalibrationArtifact")
        if config is not None and not isinstance(config, OODDetectorConfig):
            raise TypeError("config must be an OODDetectorConfig")
        self._artifact = calibration_artifact
        self._config = OODDetectorConfig() if config is None else config
        self._machine = OODHysteresisStateMachine(self._config)
        self._step_index = 0

    @property
    def calibration_artifact(self) -> OODCalibrationArtifact:
        return self._artifact

    @property
    def config(self) -> OODDetectorConfig:
        return self._config

    @property
    def state(self) -> OODState:
        return self._machine.state

    @property
    def ood_active(self) -> bool:
        return self._machine.ood_active

    def reset(self) -> None:
        self._machine.reset()
        self._step_index = 0

    def update(
        self,
        residuals: ArrayLike,
        innovation_variances: ArrayLike,
    ) -> OODDetection:
        """Score one runtime observation and advance the four-state machine."""

        residual_vector = _finite_vector(
            residuals,
            "residuals",
            nonnegative=False,
        )
        variance_vector = _finite_vector(
            innovation_variances,
            "innovation_variances",
            nonnegative=True,
        )
        expected_count = len(self._artifact.known_component_ids)
        if residual_vector.shape != (expected_count,) or variance_vector.shape != (
            expected_count,
        ):
            raise ValueError(
                "runtime residuals and innovation variances must have one entry "
                "per calibrated component"
            )
        score = minimum_standardized_residual_score(
            residual_vector,
            variance_vector,
            variance_floor=self._config.variance_floor,
        )
        pvalue = split_conformal_pvalue(score, self._artifact.calibration_scores)
        state_update = self._machine.update(pvalue)
        result = OODDetection(
            step_index=self._step_index,
            ood_score=score,
            ood_pvalue=pvalue,
            previous_state=state_update.previous_state,
            diagnostic_state=state_update.state,
            low_count=state_update.low_count,
            high_count=state_update.high_count,
        )
        self._step_index += 1
        return result


__all__ = [
    "FloatArray",
    "KNOWN_MODE_POPULATION",
    "OOD_SCORE_DEFINITION",
    "OOD_CALIBRATION_SCHEMA_VERSION",
    "OOD_CALIBRATION_SPLIT",
    "ConformalOODDetector",
    "OODCalibrationArtifact",
    "OODDetection",
    "OODDetectorConfig",
    "OODHysteresisStateMachine",
    "OODState",
    "OODStateUpdate",
    "calibration_scores_from_residuals",
    "minimum_standardized_residual_score",
    "split_conformal_pvalue",
]
