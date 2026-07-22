"""Controller-visible orchestration of mode belief and conformal OOD state.

The first two samples are explicit ARX warm-up records.  From sample index two
onward, the current measured power is compared with predictions formed only
from previously available power/frequency and already-applied IBR commands.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from numbers import Integral

import numpy as np
from numpy.typing import ArrayLike, NDArray

from d5freq.identification.model_library import ModeLibrary
from d5freq.interfaces import Measurement
from d5freq.utils.hashing import sha256_json

from .mode_belief_filter import ModeBeliefFilter
from .ood_detector import (
    ConformalOODDetector,
    OODCalibrationArtifact,
    OODDetectorConfig,
    OODState,
)


FloatArray = NDArray[np.float64]


def _readonly_vector(value: ArrayLike, name: str, size: int) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise TypeError(f"{name} must be real-valued")
    array = np.asarray(raw, dtype=np.float64)
    if array.shape != (size,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain {size} finite values")
    result = array.copy()
    result.setflags(write=False)
    return result


@dataclass(frozen=True, slots=True)
class DiagnosticOutput:
    """One complete runtime diagnostic record with no simulator-only fields."""

    time_s: float
    sample_index: int
    valid_update: bool
    mode_belief: FloatArray
    map_mode: int
    belief_entropy: float
    raw_belief_entropy: float
    mode_predictions_pu: FloatArray
    residuals_pu: FloatArray
    innovation_variances_pu2: FloatArray
    nis: FloatArray
    log_normalization_constant: float
    ood_score: float
    ood_pvalue: float
    ood_active: bool
    diagnostic_state: str

    def __post_init__(self) -> None:
        time = float(self.time_s)
        if not math.isfinite(time) or time < 0.0:
            raise ValueError("time_s must be finite and non-negative")
        if isinstance(self.sample_index, (bool, np.bool_)) or not isinstance(
            self.sample_index, Integral
        ):
            raise TypeError("sample_index must be an integer")
        sample_index = int(self.sample_index)
        if sample_index < 0:
            raise ValueError("sample_index must be non-negative")
        if not isinstance(self.valid_update, (bool, np.bool_)):
            raise TypeError("valid_update must be boolean")
        belief_raw = np.asarray(self.mode_belief)
        if belief_raw.ndim != 1 or belief_raw.size == 0:
            raise ValueError("mode_belief must be a non-empty vector")
        count = int(belief_raw.size)
        belief = _readonly_vector(self.mode_belief, "mode_belief", count)
        if np.any(belief < 0.0) or not math.isclose(
            float(np.sum(belief)), 1.0, rel_tol=0.0, abs_tol=1.0e-12
        ):
            raise ValueError("mode_belief must be non-negative and sum to one")
        if isinstance(self.map_mode, (bool, np.bool_)) or not isinstance(
            self.map_mode, Integral
        ):
            raise TypeError("map_mode must be an integer")
        map_mode = int(self.map_mode)
        if map_mode < 0 or map_mode >= count or map_mode != int(np.argmax(belief)):
            raise ValueError("map_mode must be the mode_belief argmax")
        arrays = {
            "mode_predictions_pu": self.mode_predictions_pu,
            "residuals_pu": self.residuals_pu,
            "innovation_variances_pu2": self.innovation_variances_pu2,
            "nis": self.nis,
        }
        normalized_arrays = {
            name: _readonly_vector(value, name, count)
            for name, value in arrays.items()
        }
        if np.any(normalized_arrays["innovation_variances_pu2"] <= 0.0):
            raise ValueError("innovation variances must be positive")
        if np.any(normalized_arrays["nis"] < 0.0):
            raise ValueError("nis must be non-negative")
        finite_scalars = (
            self.belief_entropy,
            self.raw_belief_entropy,
            self.log_normalization_constant,
            self.ood_score,
            self.ood_pvalue,
        )
        if not all(math.isfinite(float(value)) for value in finite_scalars):
            raise ValueError("diagnostic scalar fields must be finite")
        if not 0.0 <= float(self.belief_entropy) <= 1.0:
            raise ValueError("belief_entropy must lie in [0, 1]")
        if float(self.raw_belief_entropy) < 0.0:
            raise ValueError("raw_belief_entropy must be non-negative")
        if float(self.ood_score) < 0.0 or not 0.0 <= float(self.ood_pvalue) <= 1.0:
            raise ValueError("OOD score/p-value are outside their valid ranges")
        if not isinstance(self.ood_active, (bool, np.bool_)):
            raise TypeError("ood_active must be boolean")
        try:
            state = OODState(str(self.diagnostic_state)).value
        except ValueError as exc:
            raise ValueError("diagnostic_state is not a valid OOD state") from exc
        expected_active = state == OODState.OOD_ACTIVE.value
        if bool(self.ood_active) != expected_active:
            raise ValueError("ood_active must agree with diagnostic_state")

        object.__setattr__(self, "time_s", time)
        object.__setattr__(self, "sample_index", sample_index)
        object.__setattr__(self, "valid_update", bool(self.valid_update))
        object.__setattr__(self, "mode_belief", belief)
        object.__setattr__(self, "map_mode", map_mode)
        for name, value in normalized_arrays.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "belief_entropy", float(self.belief_entropy))
        object.__setattr__(self, "raw_belief_entropy", float(self.raw_belief_entropy))
        object.__setattr__(
            self,
            "log_normalization_constant",
            float(self.log_normalization_constant),
        )
        object.__setattr__(self, "ood_score", float(self.ood_score))
        object.__setattr__(self, "ood_pvalue", float(self.ood_pvalue))
        object.__setattr__(self, "ood_active", bool(self.ood_active))
        object.__setattr__(self, "diagnostic_state", state)

    def to_log_record(self) -> dict[str, object]:
        """Serialize exactly the controller-visible runtime fields."""

        record: dict[str, object] = {
            "time_s": self.time_s,
            "sample_index": self.sample_index,
            "valid_update": self.valid_update,
            "map_mode": self.map_mode,
            "belief_entropy": self.belief_entropy,
            "raw_belief_entropy": self.raw_belief_entropy,
            "log_normalization_constant": self.log_normalization_constant,
            "ood_score": self.ood_score,
            "ood_pvalue": self.ood_pvalue,
            "ood_active": self.ood_active,
            "ood_state": self.diagnostic_state,
        }
        for index, value in enumerate(self.mode_belief):
            record[f"belief_{index}"] = float(value)
        for index, value in enumerate(self.mode_predictions_pu):
            record[f"prediction_{index}_pu"] = float(value)
        for index, value in enumerate(self.residuals_pu):
            record[f"residual_{index}_pu"] = float(value)
        for index, value in enumerate(self.innovation_variances_pu2):
            record[f"innovation_variance_{index}_pu2"] = float(value)
        for index, value in enumerate(self.nis):
            record[f"nis_{index}"] = float(value)
        return record


class OnlineModeDiagnostic:
    """Stateful runtime facade used later by every adaptive controller."""

    __slots__ = ("_belief_filter", "_ood_detector", "_history", "_sample_index")

    def __init__(
        self,
        mode_library: ModeLibrary,
        calibration_artifact: OODCalibrationArtifact,
        *,
        measurement_noise_variance_pu2: float,
        belief_floor: float,
        variance_floor_pu2: float,
        ood_config: OODDetectorConfig | None = None,
        transition_matrix: ArrayLike | None = None,
    ) -> None:
        belief_filter = ModeBeliefFilter(
            mode_library,
            measurement_noise_variance_pu2=measurement_noise_variance_pu2,
            transition_matrix=transition_matrix,
            belief_floor=belief_floor,
            variance_floor_pu2=variance_floor_pu2,
        )
        resolved_ood_config = (
            OODDetectorConfig(
                variance_floor=calibration_artifact.variance_floor_pu2
            )
            if ood_config is None
            else ood_config
        )
        ood_detector = ConformalOODDetector(
            calibration_artifact,
            resolved_ood_config,
        )
        component_ids = tuple(model.component_id for model in mode_library.models)
        if calibration_artifact.known_component_ids != component_ids:
            raise ValueError(
                "OOD calibration component IDs do not match the mode library"
            )
        logical_library_sha256 = sha256_json(mode_library.to_dict())
        if (
            calibration_artifact.mode_library_logical_sha256
            != logical_library_sha256
        ):
            raise ValueError("OOD calibration was built for a different mode library")
        if (
            calibration_artifact.measurement_noise_variance_pu2
            != float(measurement_noise_variance_pu2)
        ):
            raise ValueError(
                "runtime measurement-noise variance differs from OOD calibration"
            )
        if calibration_artifact.variance_floor_pu2 != float(variance_floor_pu2):
            raise ValueError("runtime variance floor differs from OOD calibration")
        if ood_detector.config.variance_floor != float(variance_floor_pu2):
            raise ValueError(
                "OOD detector variance floor differs from the calibrated score"
            )
        self._belief_filter = belief_filter
        self._ood_detector = ood_detector
        self._history: deque[Measurement] = deque(maxlen=2)
        self._sample_index = 0

    @property
    def mode_belief(self) -> FloatArray:
        return self._belief_filter.mode_belief

    @property
    def diagnostic_state(self) -> str:
        return self._ood_detector.state.value

    def reset(self) -> None:
        self._belief_filter.reset()
        self._ood_detector.reset()
        self._history.clear()
        self._sample_index = 0

    def _warmup_output(self, measurement: Measurement) -> DiagnosticOutput:
        belief = self._belief_filter.mode_belief
        count = belief.size
        entropy_raw = float(-np.sum(belief * np.log(belief)))
        entropy = 0.0 if count == 1 else float(entropy_raw / math.log(count))
        zeros = np.zeros(count, dtype=np.float64)
        return DiagnosticOutput(
            time_s=measurement.time_s,
            sample_index=self._sample_index,
            valid_update=False,
            mode_belief=belief,
            map_mode=int(np.argmax(belief)),
            belief_entropy=entropy,
            raw_belief_entropy=entropy_raw,
            mode_predictions_pu=zeros,
            residuals_pu=zeros,
            innovation_variances_pu2=self._belief_filter.innovation_variances_pu2,
            nis=zeros,
            log_normalization_constant=0.0,
            ood_score=0.0,
            ood_pvalue=1.0,
            ood_active=False,
            diagnostic_state=self._ood_detector.state.value,
        )

    def step(self, measurement: Measurement) -> DiagnosticOutput:
        """Consume one measurement without accepting any simulator metadata."""

        if not isinstance(measurement, Measurement):
            raise TypeError("measurement must be a Measurement")
        if self._history and measurement.time_s <= self._history[-1].time_s:
            raise ValueError("measurement times must be strictly increasing")
        if len(self._history) < 2:
            output = self._warmup_output(measurement)
        else:
            previous = self._history[-1]
            two_back = self._history[-2]
            belief = self._belief_filter.step(
                p_ibr_k_pu=measurement.p_ibr_pu,
                p_ibr_k_minus_1_pu=previous.p_ibr_pu,
                p_ibr_k_minus_2_pu=two_back.p_ibr_pu,
                u_ibr_k_minus_1_pu=measurement.u_ibr_prev_pu,
                u_ibr_k_minus_2_pu=previous.u_ibr_prev_pu,
                omega_k_minus_1_pu=previous.omega_pu,
                omega_k_minus_2_pu=two_back.omega_pu,
            )
            ood = self._ood_detector.update(
                belief.residuals_pu,
                belief.innovation_variances_pu2,
            )
            output = DiagnosticOutput(
                time_s=measurement.time_s,
                sample_index=self._sample_index,
                valid_update=True,
                mode_belief=belief.mode_belief,
                map_mode=belief.map_mode,
                belief_entropy=belief.normalized_entropy,
                raw_belief_entropy=belief.entropy,
                mode_predictions_pu=belief.mode_predictions_pu,
                residuals_pu=belief.residuals_pu,
                innovation_variances_pu2=belief.innovation_variances_pu2,
                nis=belief.normalized_innovation_squared,
                log_normalization_constant=belief.log_normalization_constant,
                ood_score=ood.ood_score,
                ood_pvalue=ood.ood_pvalue,
                ood_active=ood.ood_active,
                diagnostic_state=ood.diagnostic_state.value,
            )
        self._history.append(measurement)
        self._sample_index += 1
        return output


__all__ = ["DiagnosticOutput", "OnlineModeDiagnostic"]
