"""Hash-bound construction of final Phase-6 controllers and ablations.

This evaluation-layer module is the only place that assembles the complete
method matrix.  Controller modules remain free of evaluator labels.  Alternate
fixed-K4 and supervised-training libraries enter through the same strict
binding schema as the native K6 library; at runtime every model is addressed
only by contiguous anonymous component ID.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

import numpy as np

from d5freq.controllers.final_arx_mpc import (
    FinalARXMPCController,
    FixedReferenceSelectionArtifact,
    build_fixed_reference_arx_controller,
)
from d5freq.controllers.hard_map_mpc import HardMAPMPCController
from d5freq.controllers.lqi_fallback import LQIFallbackConfig, LQIFallbackController
from d5freq.controllers.rls_adaptive_mpc import RLSAdaptiveMPCController, RLSConfig
from d5freq.controllers.sd_bmpc import (
    SDBMPCController,
    SDBMPCControllerConfig,
    SDBMPCProvenance,
)
from d5freq.estimation.grid_kalman_filter import GridKalmanFilter
from d5freq.estimation.mode_belief_filter import build_sticky_transition_matrix
from d5freq.estimation.online_diagnostic import OnlineModeDiagnostic
from d5freq.estimation.ood_detector import OODCalibrationArtifact, OODDetectorConfig
from d5freq.evaluation.baselines.oracle import OracleARXArtifact, OracleARXMPCBaseline
from d5freq.identification.model_library import ModeLibrary
from d5freq.interfaces import ControlAction, FrequencyController, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.optimization.mpc_problem import (
    SDBMPCBounds,
    SDBMPCConfig,
    SDBMPCWeights,
    modes_from_library,
)
from d5freq.utils.config import config_sha256, load_yaml
from d5freq.utils.hashing import sha256_file, sha256_json


LIBRARY_BINDING_SCHEMA_VERSION = "d5freq.library_artifact_binding.v1"
IDENTIFICATION_SUBSET_HASH_SCHEMA_VERSION = "d5freq.identification_subset_hash.v1"
_BINDING_KEYS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "construction_protocol",
        "component_count",
        "mode_library_file_sha256",
        "mode_library_logical_sha256",
        "ood_calibration_file_sha256",
        "identification_train_dataset_sha256",
        "identification_validation_dataset_sha256",
        "runtime_label_access",
    }
)
_FINAL_SOLVERS = frozenset({"MOSEK", "GUROBI"})
_DEBUG_SOLVERS = frozenset({"CLARABEL", "SCS"})


def _sha(value: object, name: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return normalized


def _section(mapping: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = mapping.get(name)
    if not isinstance(value, Mapping):
        raise TypeError(f"configuration section {name!r} must be a mapping")
    return value


def _json_mapping(path: str | Path) -> Mapping[str, Any]:
    def reject_nonfinite(token: str) -> None:
        raise ValueError(f"non-standard JSON number {token!r} is forbidden")

    value = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject_nonfinite)
    if not isinstance(value, Mapping):
        raise TypeError("JSON artifact must contain a mapping")
    return value


class LibraryConstructionProtocol(str, Enum):
    DISCOVERED_BIC_LABEL_FREE = "discovered_bic_label_free"
    FIXED_K4_UNLABELED = "fixed_k4_unlabeled"
    LABELED_TRAINING_ONLY = "labeled_training_only"


class SolverExecutionTier(str, Enum):
    FINAL = "final"
    DEBUG = "debug"


@dataclass(frozen=True, slots=True)
class LibraryArtifactBinding:
    """Portable hashes and provenance for a runtime model/calibration pair.

    Both identification subset digests use one canonical logical definition::

        sha256_json({
          "schema_version": "d5freq.identification_subset_hash.v1",
          "split": "train" | "validation",
          "trajectory_sha256": sorted(unique_per_trajectory_parquet_file_sha256)
        })

    The trajectory digests are the exact Parquet file SHA-256 values recorded
    in ``split_manifest.csv``.  Sorting makes this binding independent of file
    paths and filesystem enumeration order, but it remains intentionally
    sensitive to Parquet byte layout (including row-group/layout changes).
    The artifact builder must reject duplicate hashes before computing this
    digest and persist the expanded hash input beside the generated library.
    """

    artifact_id: str
    construction_protocol: LibraryConstructionProtocol
    component_count: int
    mode_library_file_sha256: str
    mode_library_logical_sha256: str
    ood_calibration_file_sha256: str
    identification_train_dataset_sha256: str
    identification_validation_dataset_sha256: str
    runtime_label_access: str = "none"
    schema_version: str = LIBRARY_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LIBRARY_BINDING_SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {LIBRARY_BINDING_SCHEMA_VERSION!r}")
        artifact_id = str(self.artifact_id).strip()
        if not artifact_id:
            raise ValueError("artifact_id must not be empty")
        try:
            protocol = LibraryConstructionProtocol(self.construction_protocol)
        except ValueError as exc:
            raise ValueError("unknown library construction protocol") from exc
        if isinstance(self.component_count, bool) or int(self.component_count) != self.component_count:
            raise TypeError("component_count must be an integer")
        count = int(self.component_count)
        if count < 1:
            raise ValueError("component_count must be positive")
        if protocol in {
            LibraryConstructionProtocol.FIXED_K4_UNLABELED,
            LibraryConstructionProtocol.LABELED_TRAINING_ONLY,
        } and count != 4:
            raise ValueError(f"{protocol.value} must contain exactly K=4 components")
        if str(self.runtime_label_access).strip().lower() != "none":
            raise ValueError("runtime library access must remain label-free")
        for name in (
            "mode_library_file_sha256",
            "mode_library_logical_sha256",
            "ood_calibration_file_sha256",
            "identification_train_dataset_sha256",
            "identification_validation_dataset_sha256",
        ):
            object.__setattr__(self, name, _sha(getattr(self, name), name))
        object.__setattr__(self, "artifact_id", artifact_id)
        object.__setattr__(self, "construction_protocol", protocol)
        object.__setattr__(self, "component_count", count)
        object.__setattr__(self, "runtime_label_access", "none")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "construction_protocol": self.construction_protocol.value,
            "component_count": self.component_count,
            "mode_library_file_sha256": self.mode_library_file_sha256,
            "mode_library_logical_sha256": self.mode_library_logical_sha256,
            "ood_calibration_file_sha256": self.ood_calibration_file_sha256,
            "identification_train_dataset_sha256": self.identification_train_dataset_sha256,
            "identification_validation_dataset_sha256": (
                self.identification_validation_dataset_sha256
            ),
            "runtime_label_access": self.runtime_label_access,
        }

    @classmethod
    def from_dict(cls, value: object) -> "LibraryArtifactBinding":
        if not isinstance(value, Mapping):
            raise TypeError("library artifact binding must be a mapping")
        actual = frozenset(value)
        if actual != _BINDING_KEYS:
            raise ValueError(
                f"library binding keys mismatch; missing={sorted(_BINDING_KEYS - actual)}, "
                f"extra={sorted(actual - _BINDING_KEYS)}"
            )
        return cls(**value)  # type: ignore[arg-type]

    @classmethod
    def load_json(cls, path: str | Path) -> "LibraryArtifactBinding":
        return cls.from_dict(_json_mapping(path))

    def validate_files(
        self,
        mode_library_path: str | Path,
        ood_calibration_path: str | Path,
    ) -> tuple[ModeLibrary, OODCalibrationArtifact]:
        library = ModeLibrary.load_json(mode_library_path)
        calibration = OODCalibrationArtifact.from_dict(
            _json_mapping(ood_calibration_path)
        )
        file_hash = sha256_file(mode_library_path)
        logical_hash = sha256_json(library.to_dict())
        calibration_hash = sha256_file(ood_calibration_path)
        if file_hash != self.mode_library_file_sha256:
            raise ValueError("bound model-library file SHA-256 mismatch")
        if logical_hash != self.mode_library_logical_sha256:
            raise ValueError("bound model-library logical SHA-256 mismatch")
        if calibration_hash != self.ood_calibration_file_sha256:
            raise ValueError("bound OOD calibration file SHA-256 mismatch")
        if len(library.models) != self.component_count:
            raise ValueError("bound component_count differs from model library")
        expected_ids = tuple(range(self.component_count))
        if tuple(calibration.known_component_ids) != expected_ids:
            raise ValueError("OOD calibration does not cover ordered runtime components")
        if calibration.mode_library_sha256 != file_hash:
            raise ValueError("OOD calibration is bound to a different library file")
        if calibration.mode_library_logical_sha256 != logical_hash:
            raise ValueError("OOD calibration is bound to different library content")
        return library, calibration


@dataclass(frozen=True, slots=True)
class SDBMPCVariantConfig:
    """Frozen switches that reuse, rather than duplicate, the proposed code."""

    variant_id: str = "P"
    enable_worst_mode_term: bool = True
    hard_belief: bool = False
    enable_ood: bool = True
    use_constraint_tightening: bool = True
    use_transition_prior: bool = True

    def __post_init__(self) -> None:
        variant = str(self.variant_id).strip()
        if not variant:
            raise ValueError("variant_id must not be empty")
        for name in (
            "enable_worst_mode_term",
            "hard_belief",
            "enable_ood",
            "use_constraint_tightening",
            "use_transition_prior",
        ):
            if not isinstance(getattr(self, name), (bool, np.bool_)):
                raise TypeError(f"{name} must be boolean")
        object.__setattr__(self, "variant_id", variant)

    @classmethod
    def proposed(cls) -> "SDBMPCVariantConfig":
        return cls()

    @classmethod
    def no_worst_mode(cls) -> "SDBMPCVariantConfig":
        return cls(variant_id="no-worst", enable_worst_mode_term=False)

    @classmethod
    def hard_belief_only(cls) -> "SDBMPCVariantConfig":
        return cls(variant_id="hard-belief", hard_belief=True)

    @classmethod
    def no_ood(cls) -> "SDBMPCVariantConfig":
        return cls(variant_id="no-OOD", enable_ood=False)

    @classmethod
    def no_tightening(cls) -> "SDBMPCVariantConfig":
        return cls(variant_id="no-tightening", use_constraint_tightening=False)

    @classmethod
    def no_transition_prior(cls) -> "SDBMPCVariantConfig":
        return cls(variant_id="no-transition-prior", use_transition_prior=False)

    @classmethod
    def fixed_k4_unlabeled(cls) -> "SDBMPCVariantConfig":
        return cls(variant_id="fixed-K4-unlabeled")

    @classmethod
    def labeled_library(cls) -> "SDBMPCVariantConfig":
        return cls(variant_id="labeled-library")


@dataclass(frozen=True, slots=True)
class ControllerMetadata:
    method_id: str
    display_name: str
    evaluator_information_visible: bool
    online_adaptation: str
    ood_policy: str
    solver_tier: str
    eligible_for_final_solver_claims: bool
    library_artifact_id: str | None
    library_construction_protocol: str | None
    library_file_sha256: str | None
    library_logical_sha256: str | None
    qualifications: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ControllerBuild:
    controller: FrequencyController
    metadata: ControllerMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.controller, FrequencyController):
            raise TypeError("controller must satisfy FrequencyController")


@runtime_checkable
class EvaluationOracleController(Protocol):
    def reset(self, initial_measurement: Measurement) -> None: ...

    def act_evaluation_only(
        self, measurement: Measurement, *, true_mode_eval_only: str
    ) -> ControlAction: ...


@dataclass(frozen=True, slots=True)
class OracleControllerBuild:
    controller: EvaluationOracleController
    metadata: ControllerMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.controller, EvaluationOracleController):
            raise TypeError("controller must satisfy EvaluationOracleController")


class FinalControllerFactory:
    """Create fresh episode-local B0--B4/P controllers from bound artifacts."""

    def __init__(
        self,
        *,
        base_config_path: str | Path,
        mpc_config_path: str | Path,
        mode_library_path: str | Path,
        ood_calibration_path: str | Path,
        library_binding: LibraryArtifactBinding,
        ood_selection_path: str | Path | None = None,
        solver_tier: SolverExecutionTier = SolverExecutionTier.FINAL,
    ) -> None:
        if not isinstance(library_binding, LibraryArtifactBinding):
            raise TypeError("library_binding must be a LibraryArtifactBinding")
        try:
            tier = SolverExecutionTier(solver_tier)
        except ValueError as exc:
            raise ValueError("unknown solver execution tier") from exc
        self._base_path = Path(base_config_path).expanduser().resolve()
        self._mpc_path = Path(mpc_config_path).expanduser().resolve()
        self._library_path = Path(mode_library_path).expanduser().resolve()
        self._calibration_path = Path(ood_calibration_path).expanduser().resolve()
        self._ood_selection_path = (
            None
            if ood_selection_path is None
            else Path(ood_selection_path).expanduser().resolve()
        )
        for path in (
            self._base_path,
            self._mpc_path,
            self._library_path,
            self._calibration_path,
        ):
            if not path.is_file():
                raise FileNotFoundError(path)
        if self._ood_selection_path is not None and not self._ood_selection_path.is_file():
            raise FileNotFoundError(self._ood_selection_path)
        self._base = load_yaml(self._base_path)
        self._mpc_payload = load_yaml(self._mpc_path)
        if self._base.get("schema_version") != 1 or self._mpc_payload.get("schema_version") != 1:
            raise ValueError("base/MPC schema_version must equal 1")
        self._binding = library_binding
        self._library, self._calibration = library_binding.validate_files(
            self._library_path, self._calibration_path
        )
        self._solver_tier = tier
        self._grid_model = self._build_grid_model()
        self._mpc_config = self._build_mpc_config()
        self._controller_config = self._build_controller_config()
        self._fallback_config = self._build_fallback_config()
        self._validate_calibration_runtime_values()
        self._ood_runtime_config, self._ood_selection_sha256 = (
            self._load_ood_runtime_config()
        )

    @property
    def binding(self) -> LibraryArtifactBinding:
        return self._binding

    @property
    def grid_model(self) -> GridFrequencyModel:
        return self._grid_model

    @property
    def library(self) -> ModeLibrary:
        return self._library

    @property
    def solver_tier(self) -> SolverExecutionTier:
        return self._solver_tier

    def _build_grid_model(self) -> GridFrequencyModel:
        values = _section(self._base, "grid")
        return GridFrequencyModel(
            GridParams(
                f0_hz=values["f0_hz"],
                M_s=values["M_s"],
                D_pu=values["D_pu"],
                T_t_s=values["T_t_s"],
                T_g_s=values["T_g_s"],
                R_pu=values["R_pu"],
                control_period_s=values["control_period_s"],
                integration_step_s=values["integration_step_s"],
            )
        )

    def _build_mpc_config(self) -> SDBMPCConfig:
        values = _section(self._mpc_payload, "mpc")
        grid = _section(self._base, "grid")
        ibr = _section(self._base, "ibr_command")
        weights = SDBMPCWeights(
            q_freq=float(values["q_freq"]),
            q_integral=float(values["q_integral"]),
            q_rocof=float(values["q_rocof"]),
            r_sg=float(values["r_sg"]),
            r_ibr=float(values["r_ibr"]),
            s_delta_sg=float(values["s_delta_sg"]),
            s_delta_ibr=float(values["s_delta_ibr"]),
            q_terminal_freq=float(values["q_terminal_freq"]),
            q_terminal_integral=float(values["q_terminal_integral"]),
            lambda_worst_base=float(values["lambda_worst_base"]),
            lambda_worst_entropy=float(values["lambda_worst_entropy"]),
            rho_freq_slack=float(values["rho_freq_slack"]),
            rho_rocof_slack=float(values["rho_rocof_slack"]),
            rho_power_slack=float(values["rho_power_slack"]),
        )
        bounds = SDBMPCBounds(
            u_min_pu=(grid["u_sg_min_pu"], ibr["u_min_pu"]),
            u_max_pu=(grid["u_sg_max_pu"], ibr["u_max_pu"]),
            ramp_pu_per_s=(grid["u_sg_ramp_pu_per_s"], ibr["ramp_pu_per_s"]),
            freq_limit_hz=grid["freq_limit_hz"],
            rocof_limit_hz_per_s=grid["rocof_limit_hz_per_s"],
        )
        return SDBMPCConfig(
            horizon_steps=int(values["horizon_steps"]),
            sample_time_s=self._grid_model.params.control_period_s,
            f0_hz=self._grid_model.params.f0_hz,
            credible_mass=float(values["credible_mass"]),
            entropy_use_all_modes=float(values["entropy_use_all_modes"]),
            use_constraint_tightening=values["use_constraint_tightening"],
            weights=weights,
            bounds=bounds,
        )

    def _solver_priority(self) -> tuple[str, ...]:
        declared = tuple(
            str(value).strip().upper()
            for value in _section(self._mpc_payload, "mpc")["solver_priority"]
        )
        allowed = (
            _DEBUG_SOLVERS
            if self._solver_tier is SolverExecutionTier.DEBUG
            else _FINAL_SOLVERS
        )
        priority = tuple(value for value in declared if value in allowed)
        if not priority:
            required = (
                "CLARABEL or SCS"
                if self._solver_tier is SolverExecutionTier.DEBUG
                else "MOSEK or GUROBI"
            )
            raise ValueError(
                f"{self._solver_tier.value} solver tier requires {required}"
            )
        return priority

    def _require_library_contract(
        self,
        *,
        consumer: str,
        protocol: LibraryConstructionProtocol,
        component_count: int,
    ) -> None:
        binding = self._binding
        if (
            binding.construction_protocol is not protocol
            or binding.component_count != component_count
        ):
            raise ValueError(
                f"{consumer} requires {protocol.value} with K={component_count}; "
                f"received {binding.construction_protocol.value} with "
                f"K={binding.component_count}"
            )

    def _build_controller_config(self) -> SDBMPCControllerConfig:
        values = _section(self._mpc_payload, "mpc")
        fallback = _section(self._mpc_payload, "fallback")
        threshold = values["max_acceptable_slack_hz"]
        return SDBMPCControllerConfig(
            max_acceptable_freq_slack_hz=threshold,
            max_acceptable_rocof_slack_hz_per_s=threshold,
            max_acceptable_power_slack_pu=threshold,
            solve_timeout_s=values["solve_timeout_s"],
            warm_start=values["warm_start"],
            solver_priority=self._solver_priority(),
            solver_options=(
                {
                    "MOSEK": {
                        "mosek_params": {"MSK_IPAR_NUM_THREADS": 1}
                    },
                    "GUROBI": {"Threads": 1},
                }
                if self._solver_tier is SolverExecutionTier.FINAL
                else {}
            ),
            recovery_hold_steps=fallback["recovery_hold_steps"],
            return_blend_steps=fallback["return_blend_steps"],
        )

    def _build_fallback_config(self) -> LQIFallbackConfig:
        grid = _section(self._base, "grid")
        fallback = _section(self._mpc_payload, "fallback")
        return LQIFallbackConfig(
            u_sg_min_pu=grid["u_sg_min_pu"],
            u_sg_max_pu=grid["u_sg_max_pu"],
            u_sg_ramp_pu_per_s=grid["u_sg_ramp_pu_per_s"],
            ibr_withdraw_rate_pu_per_s=fallback["ibr_withdraw_rate_pu_per_s"],
        )

    def _measurement_variance(self) -> float:
        identification = _section(self._base, "identification")
        generation = _section(identification, "generation")
        return float(generation["power_measurement_noise_std_pu"]) ** 2

    def _variance_floor(self) -> float:
        return float(_section(self._base, "belief")["residual_variance_floor"])

    def _validate_calibration_runtime_values(self) -> None:
        if self._calibration.measurement_noise_variance_pu2 != self._measurement_variance():
            raise ValueError("runtime measurement variance differs from OOD calibration")
        if self._calibration.variance_floor_pu2 != self._variance_floor():
            raise ValueError("runtime variance floor differs from OOD calibration")

    def _load_ood_runtime_config(self) -> tuple[OODDetectorConfig, str | None]:
        """Load the known-only hysteresis selection bound by the Phase-6 lock.

        Older unit-level callers may omit the selection artifact and receive the
        preregistered values from ``base.yaml``.  Canonical Phase-6 construction
        always supplies the per-library selection path and records its SHA-256.
        """

        defaults = _section(self._base, "ood")
        values: Mapping[str, Any] = defaults
        selection_sha256: str | None = None
        if self._ood_selection_path is not None:
            payload = _json_mapping(self._ood_selection_path)
            if payload.get("schema_version") != "d5freq.phase4.v1":
                raise ValueError("OOD hysteresis selection has an unsupported schema")
            if payload.get("selection_population") != "known_modes_only":
                raise ValueError("OOD hysteresis selection must use known modes only")
            if payload.get("ood_data_used_for_selection") is not False:
                raise ValueError("OOD hysteresis selection must not use OOD test data")
            selected = payload.get("selected")
            if not isinstance(selected, Mapping):
                raise TypeError("OOD hysteresis selection lacks selected parameters")
            required = {
                "alpha_on",
                "alpha_off",
                "hold_on_steps",
                "hold_off_steps",
                "variance_floor",
            }
            if set(selected) != required:
                raise ValueError("OOD hysteresis selected-parameter keys are not exact")
            values = selected
            selection_sha256 = sha256_file(self._ood_selection_path)
        runtime = OODDetectorConfig(
            alpha_on=values["alpha_on"],
            alpha_off=values["alpha_off"],
            L_on=values["hold_on_steps"],
            L_off=values["hold_off_steps"],
            variance_floor=(
                values["variance_floor"]
                if "variance_floor" in values
                else self._variance_floor()
            ),
        )
        if runtime.variance_floor != self._variance_floor():
            raise ValueError("OOD hysteresis variance floor differs from runtime calibration")
        return runtime, selection_sha256

    def _new_estimator(self) -> GridKalmanFilter:
        estimation = _section(self._base, "estimation")
        values = _section(estimation, "grid_kalman")
        return GridKalmanFilter(
            self._grid_model,
            process_noise_covariance=np.diag(values["process_noise_diagonal"]),
            measurement_noise_covariance=np.diag(values["measurement_noise_diagonal"]),
            initial_covariance=np.diag(values["initial_covariance_diagonal"]),
            load_random_walk_std_pu_per_s=values["load_random_walk_std_pu_per_s"],
        )

    def _new_diagnostic(self, *, use_transition_prior: bool) -> OnlineModeDiagnostic:
        belief = _section(self._base, "belief")
        count = len(self._library.models)
        transition = (
            build_sticky_transition_matrix(count, belief["switch_epsilon"])
            if use_transition_prior
            else np.full((count, count), 1.0 / count, dtype=np.float64)
        )
        return OnlineModeDiagnostic(
            self._library,
            self._calibration,
            measurement_noise_variance_pu2=self._measurement_variance(),
            belief_floor=belief["probability_floor"],
            variance_floor_pu2=self._variance_floor(),
            ood_config=self._ood_runtime_config,
            transition_matrix=transition,
        )

    def _metadata(
        self,
        *,
        method_id: str,
        display_name: str,
        evaluator_visible: bool,
        adaptation: str,
        ood_policy: str,
        qualifications: tuple[str, ...] = (),
    ) -> ControllerMetadata:
        return ControllerMetadata(
            method_id=method_id,
            display_name=display_name,
            evaluator_information_visible=evaluator_visible,
            online_adaptation=adaptation,
            ood_policy=ood_policy,
            solver_tier=self._solver_tier.value,
            eligible_for_final_solver_claims=self._solver_tier is SolverExecutionTier.FINAL,
            library_artifact_id=self._binding.artifact_id,
            library_construction_protocol=self._binding.construction_protocol.value,
            library_file_sha256=self._binding.mode_library_file_sha256,
            library_logical_sha256=self._binding.mode_library_logical_sha256,
            qualifications=(
                qualifications
                + (
                    (
                        "ood_hysteresis_selection_sha256="
                        + self._ood_selection_sha256
                        if self._ood_selection_sha256 is not None
                        else "ood_hysteresis_selection=base_preregistered_default"
                    ),
                )
                + (
                    "solver_allowlist="
                    + ",".join(self._controller_config.solver_priority),
                )
                + (
                    ("solver_threads_per_episode=1",)
                    if self._solver_tier is SolverExecutionTier.FINAL
                    else ()
                )
            ),
        )

    def build_b0_lqi(self) -> ControllerBuild:
        controller = LQIFallbackController(
            self._grid_model,
            config=self._fallback_config,
            estimator=self._new_estimator(),
        )
        return ControllerBuild(
            controller,
            self._metadata(
                method_id="B0",
                display_name="LQI-only",
                evaluator_visible=False,
                adaptation="none",
                ood_policy="not_applicable",
                qualifications=("IBR command is rate-withdrawn toward zero",),
            ),
        )

    def build_b1_fixed_reference(
        self, selection: FixedReferenceSelectionArtifact
    ) -> ControllerBuild:
        self._require_library_contract(
            consumer="B1",
            protocol=LibraryConstructionProtocol.DISCOVERED_BIC_LABEL_FREE,
            component_count=6,
        )
        controller = build_fixed_reference_arx_controller(
            grid_model=self._grid_model,
            mode_library=self._library,
            mode_library_path=self._library_path,
            selection=selection,
            mpc_config=self._mpc_config,
            controller_config=self._controller_config,
            estimator=self._new_estimator(),
            fallback_config=self._fallback_config,
        )
        return ControllerBuild(
            controller,
            self._metadata(
                method_id="B1",
                display_name="Fixed reference ARX MPC",
                evaluator_visible=False,
                adaptation="none; validation-pre-registered component",
                ood_policy="none; solver/slack failures use LQI",
                qualifications=(
                    f"source_component_id={selection.selected_component_id}",
                    f"selection_split={selection.selection_split}",
                ),
            ),
        )

    def build_b2_rls(
        self, selection: FixedReferenceSelectionArtifact
    ) -> ControllerBuild:
        self._require_library_contract(
            consumer="B2",
            protocol=LibraryConstructionProtocol.DISCOVERED_BIC_LABEL_FREE,
            component_count=6,
        )
        selection.validate_library(self._library, self._library_path)
        values = _section(self._mpc_payload, "rls_baseline")
        rls_config = RLSConfig(
            forgetting_factor=values["forgetting_factor"],
            covariance_initial_scale=values["covariance_initial_scale"],
        )
        if rls_config.forgetting_factor != 0.995 or rls_config.covariance_initial_scale != 1000.0:
            raise ValueError("final B2 requires lambda=0.995 and P0=1000 I")
        controller = RLSAdaptiveMPCController(
            self._grid_model,
            self._library.models[selection.selected_component_id],
            mpc_config=self._mpc_config,
            controller_config=self._controller_config,
            rls_config=rls_config,
            estimator=self._new_estimator(),
            fallback_config=self._fallback_config,
        )
        return ControllerBuild(
            controller,
            self._metadata(
                method_id="B2",
                display_name="Single-model RLS-MPC",
                evaluator_visible=False,
                adaptation="equations 85-87; lambda=0.995; P0=1000 I",
                ood_policy="none; solver/slack failures use LQI",
                qualifications=("one precompiled parameterized DPP graph",),
            ),
        )

    def build_b3_hard_map(self, *, enable_ood_fallback: bool = True) -> ControllerBuild:
        self._require_library_contract(
            consumer="B3",
            protocol=LibraryConstructionProtocol.DISCOVERED_BIC_LABEL_FREE,
            component_count=6,
        )
        modes = modes_from_library(
            self._grid_model, self._library, expected_component_count=None
        )
        controller = HardMAPMPCController(
            self._grid_model,
            modes,
            self._new_diagnostic(use_transition_prior=True),
            mpc_config=self._mpc_config,
            controller_config=self._controller_config,
            estimator=self._new_estimator(),
            fallback_config=self._fallback_config,
            enable_ood_fallback=enable_ood_fallback,
        )
        return ControllerBuild(
            controller,
            self._metadata(
                method_id="B3",
                display_name="Hard MAP mode MPC",
                evaluator_visible=False,
                adaptation="diagnostic argmax; same frozen model library",
                ood_policy=("fallback" if enable_ood_fallback else "disabled"),
            ),
        )

    def build_b4_oracle(self, artifact: OracleARXArtifact) -> OracleControllerBuild:
        self._require_library_contract(
            consumer="B4",
            protocol=LibraryConstructionProtocol.LABELED_TRAINING_ONLY,
            component_count=4,
        )
        if not isinstance(artifact, OracleARXArtifact):
            raise TypeError("artifact must be an OracleARXArtifact")
        if len(artifact.models) != 4:
            raise ValueError("B4 requires exactly K=4 labeled Oracle ARX models")
        controller = OracleARXMPCBaseline(
            self._grid_model,
            artifact,
            mpc_config=self._mpc_config,
            controller_config=self._controller_config,
            estimator=self._new_estimator(),
            fallback_config=self._fallback_config,
        )
        return OracleControllerBuild(
            controller,
            self._metadata(
                method_id="B4",
                display_name="Supervised-ARX Oracle MPC",
                evaluator_visible=True,
                adaptation="perfect evaluator routing among training-label ARX fits",
                ood_policy="truth-informed immediate LQI for unavailable ARX",
                qualifications=(
                    "upper bound only",
                    "OOD fallback uses evaluator information and is separately flagged",
                    "no private physical-model linearization",
                ),
            ),
        )

    def build_proposed_or_ablation(
        self, variant: SDBMPCVariantConfig | None = None
    ) -> ControllerBuild:
        settings = SDBMPCVariantConfig.proposed() if variant is None else variant
        if not isinstance(settings, SDBMPCVariantConfig):
            raise TypeError("variant must be an SDBMPCVariantConfig")
        required_protocol = {
            "fixed-K4-unlabeled": LibraryConstructionProtocol.FIXED_K4_UNLABELED,
            "labeled-library": LibraryConstructionProtocol.LABELED_TRAINING_ONLY,
        }.get(
            settings.variant_id,
            LibraryConstructionProtocol.DISCOVERED_BIC_LABEL_FREE,
        )
        required_count = (
            4
            if required_protocol
            is not LibraryConstructionProtocol.DISCOVERED_BIC_LABEL_FREE
            else 6
        )
        self._require_library_contract(
            consumer=f"variant {settings.variant_id!r}",
            protocol=required_protocol,
            component_count=required_count,
        )
        mpc_config = replace(
            self._mpc_config,
            use_constraint_tightening=settings.use_constraint_tightening,
        )
        if not settings.enable_worst_mode_term:
            mpc_config = replace(
                mpc_config,
                weights=replace(
                    mpc_config.weights,
                    lambda_worst_base=0.0,
                    lambda_worst_entropy=0.0,
                ),
            )
        diagnostic = self._new_diagnostic(
            use_transition_prior=settings.use_transition_prior
        )
        modes = modes_from_library(
            self._grid_model, self._library, expected_component_count=None
        )
        if settings.hard_belief:
            controller: FrequencyController = HardMAPMPCController(
                self._grid_model,
                modes,
                diagnostic,
                mpc_config=mpc_config,
                controller_config=self._controller_config,
                estimator=self._new_estimator(),
                fallback_config=self._fallback_config,
                enable_ood_fallback=settings.enable_ood,
            )
        else:
            provenance = SDBMPCProvenance(
                base_config_sha256=config_sha256(self._base),
                mpc_config_sha256=config_sha256(self._mpc_payload),
                mode_library_file_sha256=self._binding.mode_library_file_sha256,
                mode_library_logical_sha256=self._binding.mode_library_logical_sha256,
                ood_calibration_file_sha256=self._binding.ood_calibration_file_sha256,
            )
            controller = SDBMPCController(
                self._grid_model,
                modes,
                diagnostic,
                mpc_config=mpc_config,
                controller_config=replace(
                    self._controller_config,
                    enable_ood_fallback=settings.enable_ood,
                ),
                estimator=self._new_estimator(),
                fallback_config=self._fallback_config,
                provenance=provenance,
            )
        return ControllerBuild(
            controller,
            self._metadata(
                method_id=settings.variant_id,
                display_name=(
                    "SD-BMPC" if settings.variant_id == "P" else f"SD-BMPC {settings.variant_id}"
                ),
                evaluator_visible=False,
                adaptation=("hard MAP" if settings.hard_belief else "soft belief"),
                ood_policy=(
                    "fallback"
                    if settings.enable_ood
                    else "diagnostic retained; OOD-triggered fallback disabled"
                ),
                qualifications=(
                    f"worst_mode_term={settings.enable_worst_mode_term}",
                    f"constraint_tightening={settings.use_constraint_tightening}",
                    f"transition_prior={settings.use_transition_prior}",
                ),
            ),
        )


__all__ = [
    "ControllerBuild",
    "ControllerMetadata",
    "EvaluationOracleController",
    "FinalControllerFactory",
    "IDENTIFICATION_SUBSET_HASH_SCHEMA_VERSION",
    "LIBRARY_BINDING_SCHEMA_VERSION",
    "LibraryArtifactBinding",
    "LibraryConstructionProtocol",
    "OracleControllerBuild",
    "SDBMPCVariantConfig",
    "SolverExecutionTier",
]
