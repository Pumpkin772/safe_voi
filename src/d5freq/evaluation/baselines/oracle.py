"""Evaluation-only ARX Oracle upper bound with explicit information access.

The final B4 baseline does **not** linearize the private physical IBR model.
It selects among equation-(17) ARX models fitted by pooling identification-
training data under evaluator-owned labels.  That supervised fitting artifact
and the sole label-bearing runtime method remain isolated in this evaluation
module.  An unseen evaluation key triggers immediate truth-informed LQI
fallback and is reported as an Oracle upper-bound qualification.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
from numbers import Integral, Real
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from d5freq.controllers.base import GridStateEstimator
from d5freq.controllers.final_arx_mpc import (
    FinalARXMPCController,
    MutableSingletonProblemCache,
    single_model_mpc_config,
    singleton_mode_from_arx,
)
from d5freq.controllers.lqi_fallback import LQIFallbackConfig
from d5freq.controllers.sd_bmpc import SDBMPCControllerConfig
from d5freq.estimation.online_diagnostic import DiagnosticOutput
from d5freq.identification.model_library import ARXModeModel
from d5freq.interfaces import ControlAction, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel
from d5freq.optimization.mpc_problem import SDBMPCConfig


FloatArray = NDArray[np.float64]
ORACLE_ARX_SCHEMA_VERSION = "d5freq.oracle_arx_library.v1"
_TOP_KEYS = frozenset(
    {
        "schema_version",
        "model_family",
        "training_split",
        "fitting_protocol",
        "training_dataset_sha256",
        "config_sha256",
        "models",
    }
)
_MODEL_KEYS = frozenset({"evaluation_mode_key", "arx_model"})


def _sha(value: object, name: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return normalized


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{name} must be a string-keyed mapping")
    return value


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], name: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise ValueError(
            f"{name} keys mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


@dataclass(frozen=True, slots=True)
class OracleARXRecord:
    """One evaluator-keyed, supervised training-only ARX record."""

    evaluation_mode_key: str
    arx_model: ARXModeModel

    def __post_init__(self) -> None:
        key = str(self.evaluation_mode_key).strip()
        if not key:
            raise ValueError("evaluation_mode_key must not be empty")
        if not isinstance(self.arx_model, ARXModeModel):
            raise TypeError("arx_model must be an ARXModeModel")
        if self.arx_model.component_id != 0:
            raise ValueError("Oracle artifact ARX records use local component ID zero")
        object.__setattr__(self, "evaluation_mode_key", key)

    def to_dict(self) -> dict[str, object]:
        return {
            "evaluation_mode_key": self.evaluation_mode_key,
            "arx_model": self.arx_model.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> "OracleARXRecord":
        mapping = _mapping(value, "Oracle ARX record")
        _exact_keys(mapping, _MODEL_KEYS, "Oracle ARX record")
        return cls(
            evaluation_mode_key=mapping["evaluation_mode_key"],
            arx_model=ARXModeModel.from_dict(mapping["arx_model"]),
        )


@dataclass(frozen=True, slots=True)
class OracleARXArtifact:
    """Strict proof that B4 models are supervised ARX fits, not physics."""

    training_dataset_sha256: str
    config_sha256: str
    models: tuple[OracleARXRecord, ...]
    schema_version: str = ORACLE_ARX_SCHEMA_VERSION
    model_family: str = "second_order_arx_eq17"
    training_split: str = "identification_train"
    fitting_protocol: str = "truth_labeled_pooled_ridge_eq83"

    def __post_init__(self) -> None:
        if self.schema_version != ORACLE_ARX_SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {ORACLE_ARX_SCHEMA_VERSION!r}")
        if self.model_family != "second_order_arx_eq17":
            raise ValueError("Oracle B4 must use equation-(17) second-order ARX")
        if self.training_split != "identification_train":
            raise ValueError("Oracle ARX fitting is restricted to identification_train")
        if self.fitting_protocol != "truth_labeled_pooled_ridge_eq83":
            raise ValueError("unexpected Oracle ARX fitting protocol")
        models = tuple(self.models)
        if not models or not all(isinstance(item, OracleARXRecord) for item in models):
            raise TypeError("models must be a non-empty tuple of OracleARXRecord")
        keys = tuple(item.evaluation_mode_key for item in models)
        if len(set(keys)) != len(keys):
            raise ValueError("Oracle evaluation mode keys must be unique")
        object.__setattr__(
            self,
            "training_dataset_sha256",
            _sha(self.training_dataset_sha256, "training_dataset_sha256"),
        )
        object.__setattr__(self, "config_sha256", _sha(self.config_sha256, "config_sha256"))
        object.__setattr__(self, "models", models)

    @property
    def models_by_key(self) -> Mapping[str, ARXModeModel]:
        return MappingProxyType(
            {item.evaluation_mode_key: item.arx_model for item in self.models}
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "model_family": self.model_family,
            "training_split": self.training_split,
            "fitting_protocol": self.fitting_protocol,
            "training_dataset_sha256": self.training_dataset_sha256,
            "config_sha256": self.config_sha256,
            "models": [item.to_dict() for item in self.models],
        }

    @classmethod
    def from_dict(cls, value: object) -> "OracleARXArtifact":
        mapping = _mapping(value, "Oracle ARX artifact")
        _exact_keys(mapping, _TOP_KEYS, "Oracle ARX artifact")
        raw_models = mapping["models"]
        if not isinstance(raw_models, list):
            raise TypeError("models must be a JSON array")
        return cls(
            schema_version=mapping["schema_version"],
            model_family=mapping["model_family"],
            training_split=mapping["training_split"],
            fitting_protocol=mapping["fitting_protocol"],
            training_dataset_sha256=mapping["training_dataset_sha256"],
            config_sha256=mapping["config_sha256"],
            models=tuple(OracleARXRecord.from_dict(item) for item in raw_models),
        )

    @classmethod
    def load_json(cls, path: str | Path) -> "OracleARXArtifact":
        def reject_nonfinite(token: str) -> None:
            raise ValueError(f"non-standard JSON number {token!r} is forbidden")

        payload = json.loads(
            Path(path).read_text(encoding="utf-8"), parse_constant=reject_nonfinite
        )
        return cls.from_dict(payload)


class _OracleRoutingDiagnostic:
    """Evaluation-controlled singleton OOD route; never imported by controllers."""

    __slots__ = ("_ood_active", "_sample_index", "_last_time_s")

    def __init__(self) -> None:
        self._ood_active = False
        self._sample_index = 0
        self._last_time_s: float | None = None

    def set_unseen(self, unseen: bool) -> None:
        self._ood_active = bool(unseen)

    def reset(self) -> None:
        self._sample_index = 0
        self._last_time_s = None

    def step(self, measurement: Measurement) -> DiagnosticOutput:
        if self._last_time_s is not None and measurement.time_s <= self._last_time_s:
            raise ValueError("measurement times must be strictly increasing")
        state = "OOD_ACTIVE" if self._ood_active else "KNOWN"
        output = DiagnosticOutput(
            time_s=measurement.time_s,
            sample_index=self._sample_index,
            valid_update=self._sample_index >= 2,
            mode_belief=np.ones(1),
            map_mode=0,
            belief_entropy=0.0,
            raw_belief_entropy=0.0,
            mode_predictions_pu=np.array([measurement.p_ibr_pu]),
            residuals_pu=np.zeros(1),
            innovation_variances_pu2=np.ones(1),
            nis=np.zeros(1),
            log_normalization_constant=0.0,
            ood_score=1.0 if self._ood_active else 0.0,
            ood_pvalue=0.0 if self._ood_active else 1.0,
            ood_active=self._ood_active,
            diagnostic_state=state,
        )
        self._sample_index += 1
        self._last_time_s = measurement.time_s
        return output


@dataclass(frozen=True, slots=True)
class OracleRoutingRecord:
    time_s: float
    requested_evaluation_key: str
    supervised_arx_available: bool
    truth_informed_fallback: bool


class OracleARXMPCBaseline:
    """B4 upper bound; deliberately does not satisfy ``FrequencyController``."""

    __slots__ = (
        "_artifact",
        "_grid_model",
        "_modes",
        "_inner",
        "_routing_diagnostic",
        "_current_key",
        "_last_measurement",
        "_last_key",
        "_last_action",
        "_routing_records",
    )

    def __init__(
        self,
        grid_model: GridFrequencyModel,
        artifact: OracleARXArtifact,
        *,
        mpc_config: SDBMPCConfig,
        controller_config: SDBMPCControllerConfig,
        estimator: GridStateEstimator | None = None,
        fallback_config: LQIFallbackConfig | None = None,
    ) -> None:
        if not isinstance(grid_model, GridFrequencyModel):
            raise TypeError("grid_model must be a GridFrequencyModel")
        if not isinstance(artifact, OracleARXArtifact):
            raise TypeError("artifact must be an OracleARXArtifact")
        modes = {
            key: singleton_mode_from_arx(grid_model, model)
            for key, model in artifact.models_by_key.items()
        }
        first_key = next(iter(modes))
        single_config = single_model_mpc_config(mpc_config)
        cache = MutableSingletonProblemCache(modes[first_key], single_config)
        diagnostic = _OracleRoutingDiagnostic()
        self._inner = FinalARXMPCController(
            grid_model,
            modes[first_key],
            mpc_config=single_config,
            controller_config=controller_config,
            estimator=estimator,
            fallback_config=fallback_config,
            method_state="ORACLE_ARX_MPC_EVALUATION_ONLY",
            mutable_cache=cache,
            diagnostic=diagnostic,
            enable_ood_fallback=True,
        )
        self._artifact = artifact
        self._grid_model = grid_model
        self._modes = MappingProxyType(modes)
        self._routing_diagnostic = diagnostic
        self._current_key = first_key
        self._last_measurement: Measurement | None = None
        self._last_key: str | None = None
        self._last_action: ControlAction | None = None
        self._routing_records: list[OracleRoutingRecord] = []

    @property
    def artifact(self) -> OracleARXArtifact:
        return self._artifact

    @property
    def routing_records(self) -> tuple[OracleRoutingRecord, ...]:
        return tuple(self._routing_records)

    @property
    def inner_controller(self) -> FinalARXMPCController:
        return self._inner

    def select_arx(self, true_mode_eval_only: str) -> ARXModeModel:
        try:
            return self._artifact.models_by_key[true_mode_eval_only]
        except KeyError as exc:
            raise KeyError(
                f"no supervised Oracle ARX for evaluation key {true_mode_eval_only!r}"
            ) from exc

    def reset(self, initial_measurement: Measurement) -> None:
        if not isinstance(initial_measurement, Measurement):
            raise TypeError("initial_measurement must be a Measurement")
        self._routing_diagnostic.set_unseen(False)
        self._inner.reset(initial_measurement)
        self._last_measurement = None
        self._last_key = None
        self._last_action = None
        self._routing_records.clear()

    def act_evaluation_only(
        self,
        measurement: Measurement,
        *,
        true_mode_eval_only: str,
    ) -> ControlAction:
        """Use evaluator information solely to route supervised ARX/fallback."""

        if not isinstance(measurement, Measurement):
            raise TypeError("measurement must be a Measurement")
        key = str(true_mode_eval_only)
        if self._last_measurement is not None:
            if measurement.time_s < self._last_measurement.time_s:
                raise ValueError("measurement times must be nondecreasing")
            if measurement.time_s == self._last_measurement.time_s:
                if measurement != self._last_measurement or key != self._last_key:
                    raise ValueError("an Oracle timestamp cannot be reused with changed data")
                assert self._last_action is not None
                return self._last_action

        available = key in self._modes
        self._routing_diagnostic.set_unseen(not available)
        if available and key != self._current_key:
            self._inner.replace_runtime_mode(self._modes[key])
            self._current_key = key
        action = self._inner.act(measurement)
        result = ControlAction(
            u_sg_pu=action.u_sg_pu,
            u_ibr_pu=action.u_ibr_pu,
            controller_state=(
                "ORACLE_ARX_TRUTH_INFORMED_OOD_FALLBACK"
                if not available
                else action.controller_state
            ),
            solver_status=action.solver_status,
            solve_time_s=action.solve_time_s,
            max_freq_slack_hz=action.max_freq_slack_hz,
        )
        self._routing_records.append(
            OracleRoutingRecord(
                time_s=measurement.time_s,
                requested_evaluation_key=key,
                supervised_arx_available=available,
                truth_informed_fallback=not available,
            )
        )
        self._last_measurement = measurement
        self._last_key = key
        self._last_action = result
        return result


# Final-study public name.  Keeping one name prevents the Phase-2 physical
# linearization baseline from being accidentally selected as B4.
OracleMPCBaseline = OracleARXMPCBaseline


__all__ = [
    "ORACLE_ARX_SCHEMA_VERSION",
    "OracleARXArtifact",
    "OracleARXMPCBaseline",
    "OracleARXRecord",
    "OracleMPCBaseline",
    "OracleRoutingRecord",
]
