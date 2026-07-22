"""Frozen, resumable orchestration for the Phase-6 closed-loop experiments.

The module deliberately separates three information domains:

* :mod:`closed_loop_scenarios` parses the public experiment protocol;
* simulator-private known/OOD physical modes are loaded only while constructing
  :class:`~d5freq.simulation.hybrid_simulator.HiddenModeFrequencySimulator`;
* controllers are constructed exclusively from anonymous, hash-bound ARX
  libraries and calibrations.

Each attempted episode owns a new controller factory, controller, and simulator.
Workers publish one strict JSON envelope through ``PerRunExperimentStore``;
the parent process is the only writer of aggregate CSV files.  The final stage
is guarded by a content-addressed protocol lock before its first episode.

The runner can omit control/high-frequency trajectories and controller records
for the large final matrix.  The diagnostic evaluator still sees the in-memory
records before publication, and semantic component mappings are loaded only by
that evaluation branch after controller construction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from types import MappingProxyType
from typing import Any, Literal
from uuid import uuid4

import numpy as np
import pandas as pd

from d5freq.controllers.final_arx_mpc import FixedReferenceSelectionArtifact
from d5freq.evaluation.closed_loop_metrics import ClosedLoopMetricConfig
from d5freq.evaluation.closed_loop_scenarios import (
    ExperimentProtocol,
    load_experiment_protocol,
)
from d5freq.evaluation.experiment_store import (
    PerRunExperimentStore,
    RunIdentity,
    RunIntegrityError,
    StoredRun,
    strict_json_value,
)
from d5freq.evaluation.phase6_canonical_journal import (
    CANONICAL_DECISION_JOURNAL_PAYLOAD_KEY,
    load_and_verify_canonical_decision_journal,
    make_canonical_decision_journal_writer,
)
from d5freq.evaluation.results_schema import EpisodeResult, episode_results_frame
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.utils.config import config_sha256, load_yaml
from d5freq.utils.hashing import sha256_file, sha256_json


PHASE6_ORCHESTRATION_SCHEMA_VERSION = "d5freq.phase6_orchestration.v1"
PHASE6_PROTOCOL_LOCK_SCHEMA_VERSION = "d5freq.phase6_protocol_lock.v1"
PHASE6_RUN_PROVENANCE_SCHEMA_VERSION = "d5freq.phase6_run_provenance.v1"
PHASE6_RUNTIME_SOLVER_AUDIT_SCHEMA_VERSION = "d5freq.runtime_solver_audit.v1"
PHASE6_TUNING_SELECTION_SCHEMA_VERSION = "d5freq.phase6_tuning_selection.v1"
PHASE6_ATTEMPT_RECEIPT_SCHEMA_VERSION = "d5freq.phase6_attempt_receipt.v1"
EXPECTED_SCENARIO_COUNT = 21
EXPECTED_METHOD_COUNT = 12
EXPECTED_SMOKE_RUN_COUNT = 504
EXPECTED_TUNING_RUN_COUNT = 210
EXPECTED_FINAL_RUN_COUNT = 8_280
FROZEN_TUNING_FINAL_WORKER_COUNT = 4

Stage = Literal["smoke", "tuning", "final"]
LibraryKind = Literal["native_k6", "fixed_k4_unlabeled", "labeled_training_k4"]

_NATIVE_METHODS = frozenset(
    {
        "B0",
        "B1",
        "B2",
        "B3",
        "P",
        "no-worst",
        "no-OOD",
        "no-tightening",
        "no-transition-prior",
    }
)
_EXPECTED_METHOD_IDS = (
    "B0",
    "B1",
    "B2",
    "B3",
    "B4",
    "P",
    "no-worst",
    "no-OOD",
    "no-tightening",
    "fixed-K4-unlabeled",
    "labeled-library",
    "no-transition-prior",
)


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _require_file(path: Path, name: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{name} does not exist: {path}")
    return path


def resolve_repo_or_cwd_path(path: str | Path, repo_root: str | Path) -> Path:
    """Resolve a CLI input relative to the repository, then the current cwd."""

    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    repo_candidate = (_resolved(repo_root) / candidate).resolve()
    if repo_candidate.exists():
        return repo_candidate
    cwd_candidate = (Path.cwd() / candidate).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    # Return the repository-relative spelling so a subsequent FileNotFoundError
    # names the canonical expected project location.
    return repo_candidate


def _read_json_mapping(path: str | Path) -> Mapping[str, Any]:
    def reject_constant(token: str) -> None:
        raise ValueError(f"non-standard JSON constant {token!r} is forbidden")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    payload = json.loads(
        _resolved(path).read_text(encoding="utf-8"),
        parse_constant=reject_constant,
        object_pairs_hook=unique_object,
    )
    if not isinstance(payload, Mapping):
        raise TypeError(f"JSON artifact must be an object: {path}")
    return payload


def _atomic_write_text(path: Path, text: str) -> Path:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    return _atomic_write_text(path, serialized)


@dataclass(frozen=True, slots=True)
class Phase6Paths:
    """All frozen inputs and output locations used by the orchestrator."""

    repo_root: Path
    experiments_config: Path
    base_config: Path
    mpc_config: Path
    modes_known_config_eval_only: Path
    modes_ood_config_eval_only: Path
    native_library: Path
    native_calibration: Path
    native_ood_hysteresis_selection: Path
    native_component_mapping_eval_only: Path
    native_binding: Path
    fixed_k4_library: Path
    fixed_k4_calibration: Path
    fixed_k4_ood_hysteresis_selection: Path
    fixed_k4_component_mapping_eval_only: Path
    fixed_k4_binding: Path
    labeled_library: Path
    labeled_calibration: Path
    labeled_ood_hysteresis_selection: Path
    labeled_component_mapping_eval_only: Path
    labeled_binding: Path
    fixed_reference_selection: Path
    oracle_arx_artifact_eval_only: Path
    identification_subset_hashes: Path
    output_root: Path

    def __post_init__(self) -> None:
        for item in fields(self):
            object.__setattr__(self, item.name, _resolved(getattr(self, item.name)))

    @classmethod
    def from_repo(
        cls,
        repo_root: str | Path,
        *,
        output_root: str | Path | None = None,
    ) -> "Phase6Paths":
        root = _resolved(repo_root)
        ablations = root / "artifacts" / "phase6_library_ablations"
        bindings = root / "artifacts" / "phase6_library_bindings"
        return cls(
            repo_root=root,
            experiments_config=root / "configs" / "experiments.yaml",
            base_config=root / "configs" / "base.yaml",
            mpc_config=root / "configs" / "mpc.yaml",
            modes_known_config_eval_only=root / "configs" / "modes_known.yaml",
            modes_ood_config_eval_only=root / "configs" / "modes_ood.yaml",
            native_library=root / "artifacts" / "mode_discovery" / "mode_library.json",
            native_calibration=(
                root / "artifacts" / "online_diagnosis" / "ood_calibration_artifact.json"
            ),
            native_ood_hysteresis_selection=(
                root / "artifacts" / "online_diagnosis" / "ood_hysteresis_selection.json"
            ),
            native_component_mapping_eval_only=(
                root
                / "artifacts"
                / "online_diagnosis"
                / "component_reference_mapping_eval_only.json"
            ),
            native_binding=bindings / "native_k6_discovered.json",
            fixed_k4_library=ablations / "fixed_k4_unlabeled" / "mode_library.json",
            fixed_k4_calibration=(
                root
                / "artifacts"
                / "online_diagnosis_fixed_k4"
                / "ood_calibration_artifact.json"
            ),
            fixed_k4_ood_hysteresis_selection=(
                root
                / "artifacts"
                / "online_diagnosis_fixed_k4"
                / "ood_hysteresis_selection.json"
            ),
            fixed_k4_component_mapping_eval_only=(
                ablations
                / "fixed_k4_unlabeled"
                / "evaluation_only"
                / "component_mapping_eval_only.json"
            ),
            fixed_k4_binding=bindings / "fixed_k4_unlabeled.json",
            labeled_library=(
                ablations
                / "labeled_training_library"
                / "runtime"
                / "mode_library.json"
            ),
            labeled_calibration=(
                root
                / "artifacts"
                / "online_diagnosis_labeled"
                / "ood_calibration_artifact.json"
            ),
            labeled_ood_hysteresis_selection=(
                root
                / "artifacts"
                / "online_diagnosis_labeled"
                / "ood_hysteresis_selection.json"
            ),
            labeled_component_mapping_eval_only=(
                ablations
                / "labeled_training_library"
                / "evaluation_only"
                / "component_mapping_eval_only.json"
            ),
            labeled_binding=bindings / "labeled_training_only_k4.json",
            fixed_reference_selection=(
                ablations
                / "fixed_reference"
                / "runtime"
                / "fixed_reference_selection.json"
            ),
            oracle_arx_artifact_eval_only=(
                ablations / "evaluation_only" / "oracle_arx_artifact.json"
            ),
            identification_subset_hashes=(
                ablations / "provenance" / "identification_subset_hashes.json"
            ),
            output_root=(
                root / "results" / "phase6" if output_root is None else output_root
            ),
        )

    def stage_root(self, stage: Stage) -> Path:
        return self.output_root / stage

    def run_store_root(self, stage: Stage) -> Path:
        return self.stage_root(stage) / "per_run"

    def attempt_receipt_root(self, stage: Stage) -> Path:
        return self.stage_root(stage) / "attempt_receipts"

    @property
    def tuning_selection_record(self) -> Path:
        return self.stage_root("tuning") / "tuning_selection_record.json"

    @property
    def final_protocol_lock(self) -> Path:
        return self.stage_root("final") / "protocol_lock.json"

    def library_files(self, kind: LibraryKind) -> tuple[Path, Path, Path]:
        if kind == "native_k6":
            return self.native_library, self.native_calibration, self.native_binding
        if kind == "fixed_k4_unlabeled":
            return self.fixed_k4_library, self.fixed_k4_calibration, self.fixed_k4_binding
        if kind == "labeled_training_k4":
            return self.labeled_library, self.labeled_calibration, self.labeled_binding
        raise ValueError(f"unknown library kind {kind!r}")

    def component_mapping_file_eval_only(self, kind: LibraryKind) -> Path:
        if kind == "native_k6":
            return self.native_component_mapping_eval_only
        if kind == "fixed_k4_unlabeled":
            return self.fixed_k4_component_mapping_eval_only
        if kind == "labeled_training_k4":
            return self.labeled_component_mapping_eval_only
        raise ValueError(f"unknown library kind {kind!r}")

    def artifact_file_mapping(self) -> Mapping[str, Path]:
        return MappingProxyType(
            {
                "native_library": self.native_library,
                "native_calibration": self.native_calibration,
                "native_ood_hysteresis_selection": self.native_ood_hysteresis_selection,
                "native_component_mapping_eval_only": (
                    self.native_component_mapping_eval_only
                ),
                "native_binding": self.native_binding,
                "fixed_k4_library": self.fixed_k4_library,
                "fixed_k4_calibration": self.fixed_k4_calibration,
                "fixed_k4_ood_hysteresis_selection": (
                    self.fixed_k4_ood_hysteresis_selection
                ),
                "fixed_k4_component_mapping_eval_only": (
                    self.fixed_k4_component_mapping_eval_only
                ),
                "fixed_k4_binding": self.fixed_k4_binding,
                "labeled_library": self.labeled_library,
                "labeled_calibration": self.labeled_calibration,
                "labeled_ood_hysteresis_selection": (
                    self.labeled_ood_hysteresis_selection
                ),
                "labeled_component_mapping_eval_only": (
                    self.labeled_component_mapping_eval_only
                ),
                "labeled_binding": self.labeled_binding,
                "fixed_reference_selection": self.fixed_reference_selection,
                "oracle_arx_artifact_eval_only": self.oracle_arx_artifact_eval_only,
                "identification_subset_hashes": self.identification_subset_hashes,
            }
        )


@dataclass(frozen=True, slots=True)
class Phase6RunSpec:
    stage: Stage
    identity: RunIdentity
    solver_tier: str
    paths: Phase6Paths
    protocol_revision: str
    experiments_logical_sha256: str
    artifact_state_sha256: str
    provenance_material_json: str

    @property
    def library_kind(self) -> LibraryKind:
        return library_kind_for_method(self.identity.method)


@dataclass(frozen=True, slots=True)
class WorkerRunReceipt:
    run_id: str
    envelope_sha256: str
    resumed: bool
    scientific_success: bool


@dataclass(frozen=True, slots=True)
class Phase6StageResult:
    stage: Stage
    planned_run_count: int
    executed_or_resumed_count: int
    per_episode_metrics_path: Path
    experiment_ledger_path: Path
    protocol_snapshot_path: Path
    tuning_selection_record_path: Path | None = None
    protocol_lock_path: Path | None = None


class Phase6StageExecutionError(RuntimeError):
    """Infrastructure/setup failure that must not become a scientific row."""


@dataclass(frozen=True, slots=True)
class Phase6AttemptReceipt:
    """Verified, independent evidence for one failed infrastructure attempt."""

    attempt_id: str
    sha256: str
    path: Path
    body: Mapping[str, Any]


def _new_attempt_id() -> str:
    return uuid4().hex


def _checked_attempt_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("attempt_id must be 32 lowercase hexadecimal characters")
    return value


def _attempt_receipt_path(
    paths: Phase6Paths, stage: Stage, attempt_id: str
) -> Path:
    return paths.attempt_receipt_root(stage) / f"{_checked_attempt_id(attempt_id)}.json"


def _load_attempt_receipt_path(path: Path) -> Phase6AttemptReceipt:
    payload = _read_json_mapping(path)
    if set(payload) != {"schema_version", "sha256", "body"}:
        raise RunIntegrityError("attempt receipt envelope keys do not match schema")
    if payload["schema_version"] != PHASE6_ATTEMPT_RECEIPT_SCHEMA_VERSION:
        raise RunIntegrityError("attempt receipt schema_version mismatch")
    body = payload["body"]
    digest = payload["sha256"]
    if not isinstance(body, Mapping):
        raise RunIntegrityError("attempt receipt body must be an object")
    if not isinstance(digest, str) or len(digest) != 64:
        raise RunIntegrityError("attempt receipt SHA-256 is malformed")
    expected = sha256_json(
        {
            "schema_version": PHASE6_ATTEMPT_RECEIPT_SCHEMA_VERSION,
            "body": body,
        }
    )
    if digest != expected:
        raise RunIntegrityError("attempt receipt SHA-256 mismatch")
    attempt_id = _checked_attempt_id(body.get("attempt_id"))
    if path.stem != attempt_id:
        raise RunIntegrityError("attempt receipt filename differs from attempt_id")
    if body.get("status") != "failed_before_canonical_publication":
        raise RunIntegrityError("attempt receipt status is invalid")
    return Phase6AttemptReceipt(
        attempt_id=attempt_id,
        sha256=digest,
        path=path.resolve(),
        body=MappingProxyType(dict(body)),
    )


def write_phase6_attempt_receipt(
    *,
    paths: Phase6Paths,
    stage: Stage,
    attempt_id: str,
    failure_stage: str,
    origin: str,
    error: BaseException,
    spec: Phase6RunSpec | None,
) -> Phase6AttemptReceipt:
    """Persist one immutable failure receipt outside the canonical run store."""

    attempt_id = _checked_attempt_id(attempt_id)
    if stage not in {"smoke", "tuning", "final"}:
        raise ValueError("attempt receipt stage is invalid")
    if not isinstance(failure_stage, str) or not failure_stage.strip():
        raise ValueError("attempt receipt failure_stage must be non-empty")
    if not isinstance(origin, str) or not origin.strip():
        raise ValueError("attempt receipt origin must be non-empty")
    path = _attempt_receipt_path(paths, stage, attempt_id)
    if path.is_file():
        return _load_attempt_receipt_path(path)
    identity = None if spec is None else spec.identity.to_dict()
    provenance_sha = (
        None if spec is None else sha256_json(expected_provenance(spec))
    )
    message = str(error)
    if len(message) > 2_000:
        message = message[:1_999] + "…"
    body = {
        "attempt_id": attempt_id,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "failed_before_canonical_publication",
        "stage": stage,
        "failure_stage": failure_stage.strip(),
        "origin": origin.strip(),
        "failure_type": type(error).__name__,
        "failure_message": message,
        "process_id": os.getpid(),
        "run_identity": identity,
        "run_plan_provenance_sha256": provenance_sha,
        "canonical_run_envelope_written": False,
        "retryable_without_consuming_run_id": True,
    }
    normalized = strict_json_value(body)
    assert isinstance(normalized, Mapping)
    digest = sha256_json(
        {
            "schema_version": PHASE6_ATTEMPT_RECEIPT_SCHEMA_VERSION,
            "body": normalized,
        }
    )
    _atomic_write_json(
        path,
        {
            "schema_version": PHASE6_ATTEMPT_RECEIPT_SCHEMA_VERSION,
            "sha256": digest,
            "body": normalized,
        },
    )
    receipt = _load_attempt_receipt_path(path)
    if receipt.sha256 != digest:
        raise RunIntegrityError("atomic attempt receipt publication failed verification")
    return receipt


def load_phase6_attempt_receipts(
    paths: Phase6Paths, stage: Stage
) -> tuple[Phase6AttemptReceipt, ...]:
    """Load and authenticate every retained infrastructure-attempt receipt."""

    root = paths.attempt_receipt_root(stage)
    if not root.exists():
        return ()
    if not root.is_dir():
        raise RunIntegrityError("attempt receipt root is not a directory")
    return tuple(_load_attempt_receipt_path(path) for path in sorted(root.glob("*.json")))


def _stage_failure_with_receipt(
    *,
    message: str,
    receipt: Phase6AttemptReceipt,
    error: BaseException,
) -> Phase6StageExecutionError:
    failure = Phase6StageExecutionError(
        f"{message}; independent attempt receipt: {receipt.path}"
    )
    failure.__cause__ = error
    return failure


def _ensure_phase6_attempt_receipt(
    *,
    paths: Phase6Paths,
    stage: Stage,
    attempt_id: str,
    failure_stage: str,
    origin: str,
    error: BaseException,
    spec: Phase6RunSpec | None,
) -> Phase6AttemptReceipt:
    path = _attempt_receipt_path(paths, stage, attempt_id)
    if path.is_file():
        return _load_attempt_receipt_path(path)
    return write_phase6_attempt_receipt(
        paths=paths,
        stage=stage,
        attempt_id=attempt_id,
        failure_stage=failure_stage,
        origin=origin,
        error=error,
        spec=spec,
    )


def load_frozen_phase6_protocol(path: str | Path) -> ExperimentProtocol:
    """Load and additionally assert the preregistered 21-by-12 matrix."""

    protocol = load_experiment_protocol(path)
    method_ids = tuple(method.method_id for method in protocol.methods)
    if len(protocol.scenario_variants) != EXPECTED_SCENARIO_COUNT:
        raise ValueError("Phase-6 protocol must contain exactly 21 scenario variants")
    if len(protocol.methods) != EXPECTED_METHOD_COUNT:
        raise ValueError("Phase-6 protocol must contain exactly 12 methods")
    if method_ids != _EXPECTED_METHOD_IDS:
        raise ValueError(
            "Phase-6 method ordering/IDs differ from the frozen protocol: "
            f"{method_ids!r}"
        )
    if protocol.full_final_episode_count != EXPECTED_FINAL_RUN_COUNT:
        raise ValueError("Phase-6 final matrix must contain exactly 8,280 episodes")
    return protocol


def stable_run_id(
    *, stage: Stage, revision: str, scenario_id: str, method_id: str, seed: int
) -> str:
    """Return a readable stable ID; no filesystem path is embedded in it."""

    if stage not in {"smoke", "tuning", "final"}:
        raise ValueError("stage must be smoke, tuning, or final")
    for value, name in (
        (revision, "revision"),
        (scenario_id, "scenario_id"),
        (method_id, "method_id"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        if "::" in value:
            raise ValueError(f"{name} cannot contain the run-ID delimiter")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    return (
        f"phase6::{stage}::{revision}::{scenario_id}::{method_id}::seed-{seed:06d}"
    )


def library_kind_for_method(method_id: str) -> LibraryKind:
    if method_id in _NATIVE_METHODS:
        return "native_k6"
    if method_id == "fixed-K4-unlabeled":
        return "fixed_k4_unlabeled"
    if method_id in {"labeled-library", "B4"}:
        return "labeled_training_k4"
    raise KeyError(f"unknown frozen Phase-6 method {method_id!r}")


def _checked_sha256(value: object, name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return digest


def _canonical_json_object(value: Mapping[str, Any], name: str) -> str:
    normalized = strict_json_value(value)
    if not isinstance(normalized, Mapping):
        raise TypeError(f"{name} must normalize to a JSON object")
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _provenance_material_json(
    paths: Phase6Paths,
    protocol_material: Mapping[str, Any] | None,
) -> str:
    if protocol_material is None:
        config_paths = {
            "experiments": paths.experiments_config,
            "base": paths.base_config,
            "mpc": paths.mpc_config,
            "modes_known_eval_only": paths.modes_known_config_eval_only,
            "modes_ood_eval_only": paths.modes_ood_config_eval_only,
        }
        configs = {
            name: {
                "file_sha256": sha256_file(path),
                "logical_sha256": config_sha256(load_yaml(path)),
            }
            for name, path in config_paths.items()
        }
        code_files = dict(_code_manifest(paths))
        payload: Mapping[str, Any] = {
            "configs": configs,
            "artifacts": {},
            "code_sha256": sha256_json(code_files),
            "tuning_selection_record_sha256": None,
        }
    else:
        normalized = strict_json_value(protocol_material)
        if not isinstance(normalized, Mapping):
            raise TypeError("protocol_material must normalize to a JSON object")
        configs = normalized.get("configs")
        artifacts = normalized.get("artifacts")
        code = normalized.get("code")
        if not isinstance(configs, Mapping):
            raise TypeError("protocol material configs must be an object")
        if not isinstance(artifacts, Mapping):
            raise TypeError("protocol material artifacts must be an object")
        if not isinstance(code, Mapping):
            raise TypeError("protocol material code must be an object")
        payload = {
            "configs": dict(configs),
            "artifacts": dict(artifacts),
            "code_sha256": code.get("logical_sha256"),
            "tuning_selection_record_sha256": normalized.get(
                "tuning_selection_record_sha256"
            ),
        }
    return _canonical_json_object(payload, "provenance material")


def expected_provenance(spec: Phase6RunSpec) -> Mapping[str, Any]:
    """Return the sole accepted provenance object for one Phase-6 envelope."""

    try:
        material = json.loads(spec.provenance_material_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("run spec provenance material is invalid JSON") from exc
    if not isinstance(material, Mapping) or set(material) != {
        "configs",
        "artifacts",
        "code_sha256",
        "tuning_selection_record_sha256",
    }:
        raise ValueError("run spec provenance material has the wrong fields")
    configs = material["configs"]
    artifacts = material["artifacts"]
    if not isinstance(configs, Mapping) or not isinstance(artifacts, Mapping):
        raise TypeError("run spec provenance configs/artifacts must be objects")
    for required in ("experiments", "base", "mpc"):
        row = configs.get(required)
        if not isinstance(row, Mapping):
            raise ValueError(f"run provenance lacks {required} config hashes")
        _checked_sha256(row.get("file_sha256"), f"{required} file hash")
        logical = _checked_sha256(
            row.get("logical_sha256"), f"{required} logical hash"
        )
        if required == "experiments" and logical != spec.experiments_logical_sha256:
            raise ValueError("run spec experiments hash disagrees with provenance")
    for name, digest in artifacts.items():
        if not isinstance(name, str):
            raise TypeError("run provenance artifact names must be strings")
        _checked_sha256(digest, f"{name} artifact hash")
    code_sha = _checked_sha256(material["code_sha256"], "code hash")
    tuning_sha = material["tuning_selection_record_sha256"]
    if tuning_sha is not None:
        tuning_sha = _checked_sha256(tuning_sha, "tuning selection hash")
    artifact_state = _checked_sha256(
        spec.artifact_state_sha256, "artifact state hash"
    )
    payload = {
        "schema_version": PHASE6_RUN_PROVENANCE_SCHEMA_VERSION,
        "stage": spec.stage,
        "solver_tier": spec.solver_tier,
        "protocol_revision": spec.protocol_revision,
        "experiments_logical_sha256": spec.experiments_logical_sha256,
        "artifact_state_sha256": artifact_state,
        "protocol_material_sha256": artifact_state,
        "library_kind": spec.library_kind,
        "configs": dict(configs),
        "artifacts": dict(artifacts),
        "code_sha256": code_sha,
        "tuning_selection_record_sha256": tuning_sha,
    }
    normalized = strict_json_value(payload)
    assert isinstance(normalized, Mapping)
    return MappingProxyType(dict(normalized))


def _stored_provenance(
    stored: StoredRun,
    spec: Phase6RunSpec,
) -> Mapping[str, Any]:
    execution = stored.run_payload.get("execution")
    if (
        isinstance(execution, Mapping)
        and execution.get("orchestration_failure") is True
    ) or stored.episode_result.failure_stage in {
        "orchestration_setup",
        "worker_process",
    }:
        raise RunIntegrityError(
            "canonical per-run store contains an infrastructure/setup failure row"
        )
    raw = stored.run_payload.get("provenance")
    if not isinstance(raw, Mapping):
        raise RunIntegrityError(
            f"stored run {stored.identity.run_id!r} lacks Phase-6 provenance"
        )
    actual = strict_json_value(raw)
    if not isinstance(actual, Mapping) or actual != expected_provenance(spec):
        raise RunIntegrityError(
            f"stored run {stored.identity.run_id!r} provenance differs from its plan"
        )
    # External journals are part of the immutable canonical run.  Resume,
    # verification, and aggregation all pass through this boundary, so a
    # missing or modified Parquet file can never be silently accepted.
    load_and_verify_canonical_decision_journal(stored)
    return MappingProxyType(dict(actual))


def build_metric_config(base_config_path: str | Path) -> ClosedLoopMetricConfig:
    """Resolve every final metric threshold from the frozen base configuration."""

    base = load_yaml(base_config_path)
    grid = base.get("grid")
    ibr = base.get("ibr_command")
    if not isinstance(grid, Mapping) or not isinstance(ibr, Mapping):
        raise TypeError("base config requires grid and ibr_command mappings")
    expected = {
        "f0_hz": 50.0,
        "freq_limit_hz": 0.5,
        "rocof_limit_hz_per_s": 0.5,
        "u_sg_min_pu": -0.12,
        "u_sg_max_pu": 0.12,
        "u_sg_ramp_pu_per_s": 0.02,
    }
    for key, frozen in expected.items():
        value = float(grid[key])
        if not math.isclose(value, frozen, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError(f"base grid.{key} is frozen at {frozen}, got {value}")
    expected_ibr = {
        "u_min_pu": -0.08,
        "u_max_pu": 0.08,
        "ramp_pu_per_s": 0.04,
    }
    for key, frozen in expected_ibr.items():
        value = float(ibr[key])
        if not math.isclose(value, frozen, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError(f"base ibr_command.{key} is frozen at {frozen}, got {value}")
    return ClosedLoopMetricConfig(
        nominal_frequency_hz=float(grid["f0_hz"]),
        frequency_limit_hz=float(grid["freq_limit_hz"]),
        rocof_limit_hz_per_s=float(grid["rocof_limit_hz_per_s"]),
        safety_frequency_limit_hz=float(grid["freq_limit_hz"]),
        settling_band_hz=0.05,
        sg_command_min_pu=float(grid["u_sg_min_pu"]),
        sg_command_max_pu=float(grid["u_sg_max_pu"]),
        sg_slew_limit_pu_per_s=float(grid["u_sg_ramp_pu_per_s"]),
        ibr_command_min_pu=float(ibr["u_min_pu"]),
        ibr_command_max_pu=float(ibr["u_max_pu"]),
        ibr_slew_limit_pu_per_s=float(ibr["ramp_pu_per_s"]),
        command_sample_period_s=float(grid["control_period_s"]),
    )


def _method_subset(
    protocol: ExperimentProtocol,
    stage: Stage,
    method_ids: Sequence[str] | None,
) -> tuple[str, ...]:
    if stage == "tuning":
        if method_ids is not None:
            raise ValueError(
                "tuning uses only the frozen P candidate; method filters are forbidden"
            )
        return ("P",)
    all_ids = tuple(method.method_id for method in protocol.methods)
    if method_ids is None:
        return all_ids
    if stage != "smoke":
        raise ValueError("method filters are allowed only for smoke/debug runs")
    requested = tuple(dict.fromkeys(method_ids))
    unknown = set(requested) - set(all_ids)
    if unknown:
        raise KeyError(f"unknown method filter(s): {sorted(unknown)!r}")
    return tuple(method_id for method_id in all_ids if method_id in requested)


def _scenario_subset(
    protocol: ExperimentProtocol,
    stage: Stage,
    scenario_ids: Sequence[str] | None,
) -> tuple[str, ...]:
    all_ids = tuple(row.scenario_id for row in protocol.scenario_variants)
    if scenario_ids is None:
        return all_ids
    if stage != "smoke":
        raise ValueError("scenario filters are allowed only for smoke/debug runs")
    requested = tuple(dict.fromkeys(scenario_ids))
    unknown = set(requested) - set(all_ids)
    if unknown:
        raise KeyError(f"unknown scenario filter(s): {sorted(unknown)!r}")
    return tuple(scenario_id for scenario_id in all_ids if scenario_id in requested)


def build_run_plan(
    paths: Phase6Paths,
    *,
    stage: Stage,
    solver_tier: str | None = None,
    method_ids: Sequence[str] | None = None,
    scenario_ids: Sequence[str] | None = None,
    max_runs: int | None = None,
    artifact_state_sha256: str | None = None,
    protocol_material: Mapping[str, Any] | None = None,
) -> tuple[Phase6RunSpec, ...]:
    """Expand the frozen protocol into deterministic episode identities."""

    if stage not in {"smoke", "tuning", "final"}:
        raise ValueError("stage must be smoke, tuning, or final")
    protocol = load_frozen_phase6_protocol(paths.experiments_config)
    experiments_payload = load_yaml(paths.experiments_config)
    experiments_hash = config_sha256(experiments_payload)
    if protocol_material is None:
        resolved_artifact_state = (
            "0" * 64
            if artifact_state_sha256 is None
            else _checked_sha256(artifact_state_sha256, "artifact_state_sha256")
        )
    else:
        current_material_sha = protocol_material_sha256(protocol_material)
        if (
            artifact_state_sha256 is not None
            and _checked_sha256(
                artifact_state_sha256, "artifact_state_sha256"
            )
            != current_material_sha
        ):
            raise ValueError(
                "artifact_state_sha256 disagrees with protocol_material"
            )
        resolved_artifact_state = current_material_sha
    provenance_material_json = _provenance_material_json(paths, protocol_material)
    tier = (
        ("DEBUG" if stage == "smoke" else "FINAL")
        if solver_tier is None
        else str(solver_tier).upper()
    )
    if tier not in {"DEBUG", "FINAL"}:
        raise ValueError("solver_tier must be DEBUG or FINAL")
    if stage in {"tuning", "final"} and tier != "FINAL":
        raise ValueError(f"{stage} runs require the FINAL solver tier")
    if stage == "final" and any(
        value is not None for value in (method_ids, scenario_ids, max_runs)
    ):
        raise ValueError("final runs forbid method/scenario/max-runs subsets")
    if stage == "tuning" and (scenario_ids is not None or max_runs is not None):
        raise ValueError("tuning must cover all 21 scenarios and 10 frozen seeds")
    if max_runs is not None:
        if stage != "smoke":
            raise ValueError("max_runs is allowed only for smoke/debug runs")
        if isinstance(max_runs, bool) or not isinstance(max_runs, int) or max_runs <= 0:
            raise ValueError("max_runs must be a positive integer")

    methods = _method_subset(protocol, stage, method_ids)
    scenarios = _scenario_subset(protocol, stage, scenario_ids)
    specs: list[Phase6RunSpec] = []
    for scenario_id in scenarios:
        seeds = protocol.seeds_for(scenario_id, stage)
        for method_id in methods:
            for seed in seeds:
                identity = RunIdentity(
                    run_id=stable_run_id(
                        stage=stage,
                        revision=protocol.revision,
                        scenario_id=scenario_id,
                        method_id=method_id,
                        seed=seed,
                    ),
                    scenario_id=scenario_id,
                    method=method_id,
                    seed=seed,
                )
                specs.append(
                    Phase6RunSpec(
                        stage=stage,
                        identity=identity,
                        solver_tier=tier,
                        paths=paths,
                        protocol_revision=protocol.revision,
                        experiments_logical_sha256=experiments_hash,
                        artifact_state_sha256=resolved_artifact_state,
                        provenance_material_json=provenance_material_json,
                    )
                )
    if max_runs is not None:
        specs = specs[:max_runs]
    if method_ids is None and scenario_ids is None and max_runs is None:
        expected = {
            "smoke": EXPECTED_SMOKE_RUN_COUNT,
            "tuning": EXPECTED_TUNING_RUN_COUNT,
            "final": EXPECTED_FINAL_RUN_COUNT,
        }[stage]
        if len(specs) != expected:
            raise AssertionError(f"{stage} plan has {len(specs)} runs; expected {expected}")
    return tuple(specs)


def _subset_hashes(path: Path) -> tuple[str, str]:
    payload = _read_json_mapping(path)
    subsets = payload.get("subsets")
    if not isinstance(subsets, Mapping) or set(subsets) != {"train", "validation"}:
        raise ValueError("identification subset manifest must contain train/validation")
    values: list[str] = []
    for name in ("train", "validation"):
        row = subsets[name]
        if not isinstance(row, Mapping):
            raise TypeError(f"subset {name!r} must be an object")
        digest = str(row.get("canonical_sha256", "")).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"subset {name!r} canonical SHA-256 is malformed")
        values.append(digest)
    return values[0], values[1]


@dataclass(frozen=True, slots=True)
class ValidatedPhase6Artifacts:
    fixed_reference: FixedReferenceSelectionArtifact
    train_subset_sha256: str
    validation_subset_sha256: str
    binding_file_sha256_by_kind: Mapping[LibraryKind, str]


def validate_b1_selection(
    paths: Phase6Paths,
) -> tuple[FixedReferenceSelectionArtifact, str, str]:
    """Verify B1's protocol and validation-subset bindings without labels."""

    _require_file(paths.fixed_reference_selection, "fixed_reference_selection")
    _require_file(paths.identification_subset_hashes, "identification_subset_hashes")
    protocol_sha = config_sha256(load_yaml(paths.experiments_config))
    train_sha, validation_sha = _subset_hashes(paths.identification_subset_hashes)
    fixed_reference = FixedReferenceSelectionArtifact.load_json(
        paths.fixed_reference_selection
    )
    if fixed_reference.protocol_sha256 != protocol_sha:
        raise ValueError(
            "B1 selection protocol_sha256 differs from experiments.yaml logical hash"
        )
    if fixed_reference.selection_dataset_sha256 != validation_sha:
        raise ValueError(
            "B1 selection validation hash differs from the canonical validation subset"
        )
    return fixed_reference, train_sha, validation_sha


def validate_phase6_artifacts(paths: Phase6Paths) -> ValidatedPhase6Artifacts:
    """Verify all library/calibration bindings and the truth-free B1 choice."""

    from d5freq.evaluation.baselines.oracle import OracleARXArtifact
    from d5freq.evaluation.controller_factories import (
        FinalControllerFactory,
        LibraryArtifactBinding,
        LibraryConstructionProtocol,
        SolverExecutionTier,
    )

    for name, path in paths.artifact_file_mapping().items():
        _require_file(path, name)
    fixed_reference, train_sha, validation_sha = validate_b1_selection(paths)

    expected = {
        "native_k6": (LibraryConstructionProtocol.DISCOVERED_BIC_LABEL_FREE, 6),
        "fixed_k4_unlabeled": (LibraryConstructionProtocol.FIXED_K4_UNLABELED, 4),
        "labeled_training_k4": (LibraryConstructionProtocol.LABELED_TRAINING_ONLY, 4),
    }
    binding_hashes: dict[LibraryKind, str] = {}
    bindings: dict[LibraryKind, Any] = {}
    for kind in ("native_k6", "fixed_k4_unlabeled", "labeled_training_k4"):
        library_path, calibration_path, binding_path = paths.library_files(kind)
        binding = LibraryArtifactBinding.load_json(binding_path)
        required_protocol, required_count = expected[kind]
        if (
            binding.construction_protocol is not required_protocol
            or binding.component_count != required_count
        ):
            raise ValueError(f"{kind} binding has the wrong construction contract")
        if binding.identification_train_dataset_sha256 != train_sha:
            raise ValueError(f"{kind} binding has the wrong train subset hash")
        if binding.identification_validation_dataset_sha256 != validation_sha:
            raise ValueError(f"{kind} binding has the wrong validation subset hash")
        binding.validate_files(library_path, calibration_path)
        ood_selection_path = {
            "native_k6": paths.native_ood_hysteresis_selection,
            "fixed_k4_unlabeled": paths.fixed_k4_ood_hysteresis_selection,
            "labeled_training_k4": paths.labeled_ood_hysteresis_selection,
        }[kind]
        # Constructor validation binds the exact known-only hysteresis choice
        # (including K4's distinct hold length) before a protocol lock is made.
        FinalControllerFactory(
            base_config_path=paths.base_config,
            mpc_config_path=paths.mpc_config,
            mode_library_path=library_path,
            ood_calibration_path=calibration_path,
            ood_selection_path=ood_selection_path,
            library_binding=binding,
            solver_tier=SolverExecutionTier.DEBUG,
        )
        load_component_mapping_eval_only(paths, kind)
        binding_hashes[kind] = sha256_file(binding_path)
        bindings[kind] = binding

    native = bindings["native_k6"]
    if (
        fixed_reference.mode_library_file_sha256 != native.mode_library_file_sha256
        or fixed_reference.mode_library_logical_sha256
        != native.mode_library_logical_sha256
    ):
        raise ValueError("B1 selection is not bound to the native K6 library")
    oracle = OracleARXArtifact.load_json(paths.oracle_arx_artifact_eval_only)
    if len(oracle.models) != 4:
        raise ValueError("B4 Oracle artifact must contain four labeled-training ARX fits")
    return ValidatedPhase6Artifacts(
        fixed_reference=fixed_reference,
        train_subset_sha256=train_sha,
        validation_subset_sha256=validation_sha,
        binding_file_sha256_by_kind=MappingProxyType(binding_hashes),
    )


def _code_manifest(paths: Phase6Paths) -> Mapping[str, str]:
    candidates = list((paths.repo_root / "src" / "d5freq").rglob("*.py"))
    candidates.extend(
        paths.repo_root / "scripts" / name
        for name in ("04_run_smoke_experiments.py", "05_run_full_experiments.py")
    )
    files = sorted(
        (path.resolve() for path in candidates if path.is_file()),
        key=lambda path: path.relative_to(paths.repo_root).as_posix(),
    )
    return MappingProxyType(
        {
            path.relative_to(paths.repo_root).as_posix(): sha256_file(path)
            for path in files
        }
    )


def build_protocol_material(
    paths: Phase6Paths,
    *,
    include_tuning_selection: bool,
) -> Mapping[str, Any]:
    """Build the exact hash material repeated in snapshots and the final lock."""

    configs = {
        "experiments": paths.experiments_config,
        "base": paths.base_config,
        "mpc": paths.mpc_config,
        "modes_known_eval_only": paths.modes_known_config_eval_only,
        "modes_ood_eval_only": paths.modes_ood_config_eval_only,
    }
    config_hashes: dict[str, dict[str, str]] = {}
    for name, path in configs.items():
        _require_file(path, f"{name} config")
        config_hashes[name] = {
            "file_sha256": sha256_file(path),
            "logical_sha256": config_sha256(load_yaml(path)),
        }
    artifact_hashes = {
        name: sha256_file(_require_file(path, name))
        for name, path in paths.artifact_file_mapping().items()
    }
    tuning_hash: str | None = None
    if include_tuning_selection:
        tuning_hash = sha256_file(
            _require_file(paths.tuning_selection_record, "tuning selection record")
        )
    code_files = dict(_code_manifest(paths))
    material = {
        "schema_version": PHASE6_ORCHESTRATION_SCHEMA_VERSION,
        "configs": config_hashes,
        "artifacts": artifact_hashes,
        "tuning_selection_record_sha256": tuning_hash,
        "code": {
            "file_sha256": code_files,
            "logical_sha256": sha256_json(code_files),
        },
    }
    return MappingProxyType(material)


def protocol_material_sha256(material: Mapping[str, Any]) -> str:
    return sha256_json(material)


def _protocol_envelope(material: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": PHASE6_PROTOCOL_LOCK_SCHEMA_VERSION,
        "protocol_material_sha256": protocol_material_sha256(material),
        "material": dict(material),
    }


def ensure_final_protocol_lock(
    *,
    lock_path: str | Path,
    run_store_root: str | Path,
    tuning_selection_record_path: str | Path,
    material: Mapping[str, Any],
) -> Path:
    """Create/verify the immutable final lock before any final episode."""

    lock = _resolved(lock_path)
    store_root = _resolved(run_store_root)
    selection = _resolved(tuning_selection_record_path)
    if not selection.is_file():
        raise FileNotFoundError(
            "final stage requires tuning_selection_record.json before its first run"
        )
    expected = _protocol_envelope(material)
    store_nonempty = store_root.is_dir() and any(store_root.glob("*.json"))
    if lock.exists():
        actual = _read_json_mapping(lock)
        if actual != expected:
            qualifier = "non-empty final store" if store_nonempty else "existing lock"
            raise RuntimeError(
                f"Phase-6 final protocol changed after {qualifier}; resume is refused"
            )
        return lock
    if store_nonempty:
        raise RuntimeError("non-empty final store has no protocol lock; resume is refused")
    _atomic_write_json(lock, expected)
    if _read_json_mapping(lock) != expected:
        raise RuntimeError("newly written final protocol lock failed verification")
    return lock


def load_simulator_private_modes_eval_only(
    paths: Phase6Paths,
) -> Mapping[str, IBRModeParams]:
    """Load physical truth only for simulator construction (never a controller)."""

    known = load_yaml(paths.modes_known_config_eval_only)
    ood = load_yaml(paths.modes_ood_config_eval_only)
    if known.get("schema_version") != 1 or ood.get("schema_version") != 1:
        raise ValueError("simulator-private mode configs require schema_version 1")
    if known.get("truth_access") != "simulator_and_evaluation_only":
        raise ValueError("known-mode truth_access boundary is not declared")
    if ood.get("truth_access") != "simulator_and_evaluation_only":
        raise ValueError("OOD-mode truth_access boundary is not declared")
    if ood.get("exclude_from_identification_training") is not True:
        raise ValueError("OOD modes must be excluded from identification training")
    if ood.get("exclude_from_ood_calibration") is not True:
        raise ValueError("OOD modes must be excluded from OOD calibration")
    known_rows = known.get("known_modes")
    ood_rows = ood.get("ood_modes")
    if not isinstance(known_rows, Mapping) or not isinstance(ood_rows, Mapping):
        raise TypeError("mode configs require known_modes/ood_modes mappings")
    if set(known_rows) != {"nominal", "sluggish", "derated", "unavailable"}:
        raise ValueError("known simulator modes differ from the frozen four")
    if set(ood_rows) != {"asymmetric_limit", "time_varying_delay"}:
        raise ValueError("OOD simulator modes differ from the frozen two")
    if set(known_rows) & set(ood_rows):
        raise ValueError("known and OOD simulator mode names overlap")
    result: dict[str, IBRModeParams] = {}
    for name, values in (*known_rows.items(), *ood_rows.items()):
        if not isinstance(name, str) or not isinstance(values, Mapping):
            raise TypeError("mode name/definition has an invalid type")
        result[name] = IBRModeParams.from_mapping(name, values)
    return MappingProxyType(result)


def responsibility_event_time_eval_only(scenario: object) -> float | None:
    """Use the first hidden-mode switch for the preregistered transfer metric."""

    schedule = getattr(scenario, "mode_schedule", None)
    switches = tuple(getattr(schedule, "switches", ()))
    if not switches:
        return None
    first = float(getattr(switches[0], "time_s"))
    if not math.isfinite(first) or first < 0.0:
        raise ValueError("mode-switch responsibility event time is invalid")
    return first


def _normalized_component_mapping(
    raw: object,
    *,
    expected_count: int,
) -> Mapping[int, str]:
    from d5freq.evaluation.closed_loop_diagnostics import KNOWN_SEMANTIC_CLASSES

    if not isinstance(raw, Mapping):
        raise TypeError("evaluation-only component mapping must be an object")
    result: dict[int, str] = {}
    for key, value in raw.items():
        text = str(key).strip()
        if not text.isdigit() or str(int(text)) != text:
            raise ValueError("evaluation-only component IDs must be canonical integers")
        component = int(text)
        semantic = str(value).strip()
        if semantic not in KNOWN_SEMANTIC_CLASSES:
            raise ValueError("component mapping references an unknown semantic class")
        if component in result:
            raise ValueError("component mapping contains a duplicate component")
        result[component] = semantic
    if set(result) != set(range(expected_count)):
        raise ValueError(
            f"component mapping must exactly cover IDs 0..{expected_count - 1}"
        )
    return MappingProxyType(result)


def load_component_mapping_eval_only(
    paths: Phase6Paths,
    kind: LibraryKind,
) -> Mapping[int, str]:
    """Strictly load a semantic map for post-controller evaluation only."""

    path = paths.component_mapping_file_eval_only(kind)
    payload = _read_json_mapping(_require_file(path, f"{kind} component mapping"))
    if kind == "native_k6":
        if payload.get("schema_version") != "d5freq.phase4.v1":
            raise ValueError("native component mapping schema is unsupported")
        if payload.get("evaluation_only") is not True:
            raise ValueError("native component mapping must be evaluation-only")
        if payload.get("never_fed_to_runtime") is not True:
            raise ValueError("native component mapping lacks the runtime boundary")
        return _normalized_component_mapping(
            payload.get("component_to_reference_mode"), expected_count=6
        )
    if kind == "labeled_training_k4":
        if payload.get("schema_version") != "d5freq.labeled-training-library.v1":
            raise ValueError("labeled component mapping schema is unsupported")
        if payload.get("truth_access") != "evaluation_only":
            raise ValueError("labeled component mapping must be evaluation-only")
        return _normalized_component_mapping(
            payload.get("component_to_class"), expected_count=4
        )
    if kind != "fixed_k4_unlabeled":
        raise ValueError(f"unknown library kind {kind!r}")
    if (
        payload.get("schema_version")
        != "d5freq.fixed-k4-component-evaluation-mapping.v1"
    ):
        raise ValueError("fixed-K4 component mapping schema is unsupported")
    if (
        payload.get("scope") != "evaluation_only"
        or payload.get("runtime_consumable") is not False
        or payload.get("test_label_access") is not False
    ):
        raise ValueError("fixed-K4 component mapping violates its evaluation boundary")
    explicit = payload.get("component_to_class")
    components = payload.get("components")
    derived: dict[str, str] = {}
    if isinstance(components, Sequence) and not isinstance(
        components, (str, bytes, bytearray)
    ):
        for row in components:
            if not isinstance(row, Mapping):
                raise TypeError("fixed-K4 component evidence rows must be objects")
            component = row.get("component_id")
            if isinstance(component, bool) or not isinstance(component, int):
                raise TypeError("fixed-K4 component_id must be an integer")
            derived[str(component)] = str(
                row.get("selected_mode_name_eval_only", "")
            )
    raw_mapping = explicit if explicit is not None else derived
    normalized = _normalized_component_mapping(raw_mapping, expected_count=4)
    if explicit is not None and derived:
        evidence = _normalized_component_mapping(derived, expected_count=4)
        if dict(normalized) != dict(evidence):
            raise ValueError("fixed-K4 component_to_class disagrees with evidence rows")
    return normalized


def _diagnostic_config_from_base(paths: Phase6Paths):
    from d5freq.evaluation.closed_loop_diagnostics import ClosedLoopDiagnosticConfig

    base = load_yaml(paths.base_config)
    grid = base.get("grid")
    belief = base.get("belief")
    phase4 = base.get("phase4_evaluation")
    identification = base.get("identification")
    if not all(
        isinstance(value, Mapping)
        for value in (grid, belief, phase4, identification)
    ):
        raise TypeError("base config lacks diagnostic metric sections")
    assert isinstance(grid, Mapping)
    assert isinstance(belief, Mapping)
    assert isinstance(phase4, Mapping)
    assert isinstance(identification, Mapping)
    return ClosedLoopDiagnosticConfig(
        sample_time_s=float(grid["control_period_s"]),
        nominal_frequency_hz=float(grid["f0_hz"]),
        switch_belief_threshold=float(belief["detection_probability"]),
        switch_consecutive_steps=int(belief["detection_hold_steps"]),
        false_alarm_persistence_steps=int(belief["false_alarm_hold_steps"]),
        reliability_bin_count=int(phase4["reliability_bins"]),
        probability_floor=float(belief["probability_floor"]),
        warmup_steps=max(
            int(identification["arx_order_y"]),
            int(identification["arx_order_u"]),
            int(identification["arx_order_f"]),
        ),
    )


def _controller_for_spec(spec: Phase6RunSpec) -> tuple[object, object]:
    """Build one episode-local controller without loading simulator truth."""

    from d5freq.evaluation.baselines.oracle import OracleARXArtifact
    from d5freq.evaluation.controller_factories import (
        FinalControllerFactory,
        LibraryArtifactBinding,
        SDBMPCVariantConfig,
        SolverExecutionTier,
    )

    library_path, calibration_path, binding_path = spec.paths.library_files(
        spec.library_kind
    )
    ood_selection_path = {
        "native_k6": spec.paths.native_ood_hysteresis_selection,
        "fixed_k4_unlabeled": spec.paths.fixed_k4_ood_hysteresis_selection,
        "labeled_training_k4": spec.paths.labeled_ood_hysteresis_selection,
    }[spec.library_kind]
    factory = FinalControllerFactory(
        base_config_path=spec.paths.base_config,
        mpc_config_path=spec.paths.mpc_config,
        mode_library_path=library_path,
        ood_calibration_path=calibration_path,
        ood_selection_path=ood_selection_path,
        library_binding=LibraryArtifactBinding.load_json(binding_path),
        solver_tier=SolverExecutionTier(spec.solver_tier.lower()),
    )
    method = spec.identity.method
    selection: FixedReferenceSelectionArtifact | None = None
    if method in {"B1", "B2"}:
        selection = FixedReferenceSelectionArtifact.load_json(
            spec.paths.fixed_reference_selection
        )
    if method == "B0":
        build = factory.build_b0_lqi()
    elif method == "B1":
        assert selection is not None
        build = factory.build_b1_fixed_reference(selection)
    elif method == "B2":
        assert selection is not None
        build = factory.build_b2_rls(selection)
    elif method == "B3":
        build = factory.build_b3_hard_map()
    elif method == "B4":
        build = factory.build_b4_oracle(
            OracleARXArtifact.load_json(spec.paths.oracle_arx_artifact_eval_only)
        )
    else:
        variants = {
            "P": SDBMPCVariantConfig.proposed,
            "no-worst": SDBMPCVariantConfig.no_worst_mode,
            "no-OOD": SDBMPCVariantConfig.no_ood,
            "no-tightening": SDBMPCVariantConfig.no_tightening,
            "fixed-K4-unlabeled": SDBMPCVariantConfig.fixed_k4_unlabeled,
            "labeled-library": SDBMPCVariantConfig.labeled_library,
            "no-transition-prior": SDBMPCVariantConfig.no_transition_prior,
        }
        try:
            variant = variants[method]()
        except KeyError as exc:
            raise KeyError(f"unsupported Phase-6 method {method!r}") from exc
        build = factory.build_proposed_or_ablation(variant)
    return factory, build


def _runtime_solver_audit(
    records: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Summarize actual runtime solver identities without retaining all steps."""

    outcome_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    grouped: dict[tuple[str, str | None], dict[str, Any]] = {}
    attempted_count = 0
    named_attempt_count = 0
    not_run_count = 0

    def increment(target: dict[str, int], key: str) -> None:
        target[key] = target.get(key, 0) + 1

    for ordinal, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise TypeError(f"controller record {ordinal} must be an object")
        outcome = str(record.get("solver_outcome", "unknown")).strip().lower()
        status = str(record.get("solver_status", "unknown")).strip().lower()
        outcome = outcome or "unknown"
        status = status or "unknown"
        increment(outcome_counts, outcome)
        increment(status_counts, status)
        attempted = outcome not in {"none", "not_run", "skipped"}
        if not attempted:
            not_run_count += 1
            continue
        attempted_count += 1
        raw_name = record.get("solver_name")
        name = None if raw_name is None else str(raw_name).strip()
        raw_version = record.get("solver_version")
        version = None if raw_version is None else str(raw_version).strip()
        if not name:
            continue
        named_attempt_count += 1
        version = version or None
        group = grouped.setdefault(
            (name, version),
            {
                "solver_name": name,
                "solver_version": version,
                "attempt_count": 0,
                "outcome_counts": {},
                "status_counts": {},
            },
        )
        group["attempt_count"] += 1
        increment(group["outcome_counts"], outcome)
        increment(group["status_counts"], status)

    invocations: list[dict[str, Any]] = []
    for key in sorted(grouped, key=lambda item: (item[0], item[1] or "")):
        group = grouped[key]
        invocations.append(
            {
                **group,
                "outcome_counts": dict(sorted(group["outcome_counts"].items())),
                "status_counts": dict(sorted(group["status_counts"].items())),
            }
        )
    audit = {
        "schema_version": PHASE6_RUNTIME_SOLVER_AUDIT_SCHEMA_VERSION,
        "controller_record_count": len(records),
        "solver_attempt_count": attempted_count,
        "named_solver_attempt_count": named_attempt_count,
        "unnamed_solver_attempt_count": attempted_count - named_attempt_count,
        "solver_not_run_count": not_run_count,
        "solver_outcome_counts": dict(sorted(outcome_counts.items())),
        "solver_status_counts": dict(sorted(status_counts.items())),
        "solver_invocations": invocations,
    }
    normalized = strict_json_value(audit)
    assert isinstance(normalized, Mapping)
    return MappingProxyType(dict(normalized))


def _metadata_evaluator(metadata: object):
    from d5freq.evaluation.closed_loop_runner import EvaluationContribution

    def evaluate(data: object) -> EvaluationContribution:
        records = getattr(data, "controller_records", None)
        if not isinstance(records, Sequence) or isinstance(
            records, (str, bytes, bytearray)
        ):
            raise TypeError("episode evaluation data lacks controller records")
        return EvaluationContribution(
            artifacts={
                "controller_metadata": asdict(metadata),
                "runtime_solver_audit": _runtime_solver_audit(records),
            }
        )

    return evaluate


def _diagnostic_evaluator(
    spec: Phase6RunSpec,
):
    from d5freq.evaluation.closed_loop_diagnostics import (
        make_closed_loop_diagnostic_evaluator,
    )

    qualification = diagnostic_qualification_for_method(spec.identity.method)
    mapping = (
        None
        if qualification != "runtime"
        else load_component_mapping_eval_only(spec.paths, spec.library_kind)
    )
    return make_closed_loop_diagnostic_evaluator(
        component_to_semantic_eval_only=mapping,
        diagnostic_qualification=qualification,
        config=_diagnostic_config_from_base(spec.paths),
    )


def diagnostic_qualification_for_method(method_id: str) -> str:
    if method_id in {"B0", "B1", "B2"}:
        return "none"
    if method_id == "B4":
        return "truth_informed"
    if method_id in _EXPECTED_METHOD_IDS:
        return "runtime"
    raise KeyError(f"unknown frozen Phase-6 method {method_id!r}")


def _execute_run_spec(
    spec: Phase6RunSpec, attempt_id: str | None = None
) -> WorkerRunReceipt:
    """Process-safe worker with an independent pre-canonical failure receipt."""

    attempt_id = _new_attempt_id() if attempt_id is None else _checked_attempt_id(
        attempt_id
    )
    try:
        store = PerRunExperimentStore(spec.paths.run_store_root(spec.stage))
    except Exception as exc:
        receipt = write_phase6_attempt_receipt(
            paths=spec.paths,
            stage=spec.stage,
            attempt_id=attempt_id,
            failure_stage="run_store_setup",
            origin="worker",
            error=exc,
            spec=spec,
        )
        raise _stage_failure_with_receipt(
            message=f"run {spec.identity.run_id!r} store setup failed",
            receipt=receipt,
            error=exc,
        )
    existing = store.load(spec.identity)
    if existing is not None:
        _stored_provenance(existing, spec)
        return WorkerRunReceipt(
            run_id=spec.identity.run_id,
            envelope_sha256=existing.sha256,
            resumed=True,
            scientific_success=bool(existing.episode_result.scientific_success),
        )
    entered_runner = False
    try:
        from d5freq.evaluation.closed_loop_runner import (
            EpisodeRunnerConfig,
            oracle_action_from_truth,
            run_closed_loop_episode,
            scenario_truth_provider,
        )
        from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator

        protocol = load_frozen_phase6_protocol(spec.paths.experiments_config)
        scenario = protocol.build_scenario(spec.identity.scenario_id)
        factory, build = _controller_for_spec(spec)
        # Physical hidden-mode YAML is loaded on this evaluator/simulator branch
        # only.  Neither the factory nor the controller receives it.
        simulator = HiddenModeFrequencySimulator(
            factory.grid_model,
            load_simulator_private_modes_eval_only(spec.paths),
        )
        evaluators = (
            _metadata_evaluator(build.metadata),
            _diagnostic_evaluator(spec),
        )
        runner_config = EpisodeRunnerConfig(
            expected_duration_s=protocol.timebase.episode_duration_s,
            resume=True,
            replace_existing=False,
            persist_control_trajectory=False,
            persist_high_frequency_trace=False,
            persist_controller_records=False,
        )
        oracle_kwargs: dict[str, Any] = {}
        if spec.identity.method == "B4":
            oracle_kwargs = {
                "oracle_action_callback": oracle_action_from_truth,
                "truth_provider": scenario_truth_provider,
            }
        journal_writer = make_canonical_decision_journal_writer(
            stage_root=spec.paths.stage_root(spec.stage),
            stage=spec.stage,
            identity=spec.identity,
        )
        # From this call onward, controller/simulator/scientific failures are
        # episode outcomes and remain atomically persisted by the runner.  Only
        # an escaping infrastructure/artifact-publication error reaches this
        # worker boundary.
        entered_runner = True
        outcome = run_closed_loop_episode(
            identity=spec.identity,
            simulator=simulator,
            scenario=scenario,
            controller=build.controller,
            metric_config=build_metric_config(spec.paths.base_config),
            store=store,
            runner_config=runner_config,
            evaluators=evaluators,
            responsibility_event_time_s=responsibility_event_time_eval_only(
                scenario
            ),
            run_provenance=expected_provenance(spec),
            immutable_run_artifact_writer=journal_writer,
            **oracle_kwargs,
        )
    except Exception as exc:
        # Normal scientific/simulator/evaluator failures do not escape the
        # runner and therefore still produce their canonical EpisodeResult.
        receipt = write_phase6_attempt_receipt(
            paths=spec.paths,
            stage=spec.stage,
            attempt_id=attempt_id,
            failure_stage=(
                "episode_artifact_or_worker_escape"
                if entered_runner
                else "orchestration_setup"
            ),
            origin="worker",
            error=exc,
            spec=spec,
        )
        raise _stage_failure_with_receipt(
            message=f"run {spec.identity.run_id!r} failed before canonical publication",
            receipt=receipt,
            error=exc,
        )
    return WorkerRunReceipt(
        run_id=spec.identity.run_id,
        envelope_sha256=outcome.stored_run.sha256,
        resumed=outcome.resumed,
        scientific_success=bool(outcome.episode_result.scientific_success),
    )


def _store_identity_from_envelope(path: Path) -> RunIdentity:
    envelope = _read_json_mapping(path)
    body = envelope.get("body")
    if not isinstance(body, Mapping):
        raise ValueError(f"run envelope lacks body: {path.name}")
    identity = body.get("identity")
    if not isinstance(identity, Mapping):
        raise ValueError(f"run envelope lacks identity: {path.name}")
    return RunIdentity(**dict(identity))


def verified_stage_runs(
    specs: Sequence[Phase6RunSpec],
) -> tuple[StoredRun, ...]:
    """Load every present stage envelope through the strict public store API."""

    if not specs:
        return ()
    root = specs[0].paths.run_store_root(specs[0].stage)
    store = PerRunExperimentStore(root)
    expected = {spec.identity.run_id: spec for spec in specs}
    found: dict[str, StoredRun] = {}
    for path in sorted(root.glob("*.json")):
        identity = _store_identity_from_envelope(path)
        spec = expected.get(identity.run_id)
        if spec is None:
            raise ValueError(f"run store contains an unplanned run_id {identity.run_id!r}")
        if spec.identity != identity:
            raise ValueError("run store identity differs from the frozen run plan")
        stored = store.load(identity)
        if stored is None or stored.path != path.resolve():
            raise RuntimeError("verified store lookup disagrees with enumerated file")
        _stored_provenance(stored, spec)
        if identity.run_id in found:
            raise ValueError(f"duplicate stored run_id {identity.run_id!r}")
        found[identity.run_id] = stored
    return tuple(
        found[spec.identity.run_id]
        for spec in specs
        if spec.identity.run_id in found
    )


def _library_hash_columns(
    provenance: Mapping[str, Any], method_id: str
) -> dict[str, str]:
    kind = library_kind_for_method(method_id)
    prefix = {
        "native_k6": "native",
        "fixed_k4_unlabeled": "fixed_k4",
        "labeled_training_k4": "labeled",
    }[kind]
    artifacts = provenance.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise RunIntegrityError("stored run provenance lacks artifact hashes")

    def artifact(name: str) -> str:
        try:
            value = artifacts[name]
        except KeyError as exc:
            raise RunIntegrityError(
                f"stored run provenance lacks artifact hash {name!r}"
            ) from exc
        return _checked_sha256(value, f"{name} provenance hash")

    return {
        "mode_library_file_sha256": artifact(f"{prefix}_library"),
        "ood_calibration_file_sha256": artifact(f"{prefix}_calibration"),
        "ood_hysteresis_selection_file_sha256": artifact(
            f"{prefix}_ood_hysteresis_selection"
        ),
        "component_mapping_eval_only_file_sha256": artifact(
            f"{prefix}_component_mapping_eval_only"
        ),
        "library_binding_file_sha256": artifact(f"{prefix}_binding"),
    }


def _controller_metadata_columns(
    stored: StoredRun,
    spec: Phase6RunSpec,
) -> dict[str, Any]:
    artifacts = stored.run_payload.get("evaluation_artifacts")
    evaluator_zero = (
        artifacts.get("evaluator_0") if isinstance(artifacts, Mapping) else None
    )
    metadata = (
        evaluator_zero.get("controller_metadata")
        if isinstance(evaluator_zero, Mapping)
        else None
    )
    column_names = (
        "display_name",
        "evaluator_information_visible",
        "online_adaptation",
        "ood_policy",
        "eligible_for_final_solver_claims",
        "library_artifact_id",
        "library_construction_protocol",
        "qualifications",
    )
    if metadata is None:
        execution = stored.run_payload.get("execution")
        orchestration_failure = (
            execution.get("orchestration_failure")
            if isinstance(execution, Mapping)
            else None
        )
        if orchestration_failure is not True or stored.episode_result.failure_stage not in {
            "orchestration_setup",
            "worker_process",
        }:
            raise ValueError(
                "controller metadata may be absent only for a pre-controller "
                "orchestration failure"
            )
        return {
            "controller_metadata_status": "unavailable_pre_controller_failure",
            **{name: None for name in column_names},
        }
    if not isinstance(metadata, Mapping):
        raise TypeError("controller_metadata evaluator artifact must be an object")
    required = {
        "method_id",
        "display_name",
        "evaluator_information_visible",
        "online_adaptation",
        "ood_policy",
        "solver_tier",
        "eligible_for_final_solver_claims",
        "library_artifact_id",
        "library_construction_protocol",
        "library_file_sha256",
        "library_logical_sha256",
        "qualifications",
    }
    if set(metadata) != required:
        raise ValueError("controller_metadata keys do not match the frozen ledger schema")
    if metadata["method_id"] != stored.identity.method:
        raise ValueError("controller metadata method_id differs from run identity")
    if str(metadata["solver_tier"]).upper() != spec.solver_tier:
        raise ValueError("controller metadata solver tier differs from the run plan")
    for name in (
        "evaluator_information_visible",
        "eligible_for_final_solver_claims",
    ):
        if not isinstance(metadata[name], bool):
            raise TypeError(f"controller metadata {name} must be boolean")
    qualifications = metadata["qualifications"]
    if not isinstance(qualifications, Sequence) or isinstance(
        qualifications, (str, bytes, bytearray)
    ):
        raise TypeError("controller qualifications must be a sequence")
    if not all(isinstance(value, str) and value for value in qualifications):
        raise ValueError("controller qualifications must be non-empty strings")
    return {
        "controller_metadata_status": "verified",
        "display_name": metadata["display_name"],
        "evaluator_information_visible": metadata["evaluator_information_visible"],
        "online_adaptation": metadata["online_adaptation"],
        "ood_policy": metadata["ood_policy"],
        "eligible_for_final_solver_claims": metadata[
            "eligible_for_final_solver_claims"
        ],
        "library_artifact_id": metadata["library_artifact_id"],
        "library_construction_protocol": metadata[
            "library_construction_protocol"
        ],
        "qualifications": json.dumps(
            list(qualifications),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
    }


def _runtime_solver_audit_columns(stored: StoredRun) -> dict[str, Any]:
    artifacts = stored.run_payload.get("evaluation_artifacts")
    evaluator_zero = (
        artifacts.get("evaluator_0") if isinstance(artifacts, Mapping) else None
    )
    audit = (
        evaluator_zero.get("runtime_solver_audit")
        if isinstance(evaluator_zero, Mapping)
        else None
    )
    column_names = (
        "runtime_solver_record_count",
        "runtime_solver_attempt_count",
        "runtime_solver_named_attempt_count",
        "runtime_solver_unnamed_attempt_count",
        "runtime_solver_not_run_count",
        "runtime_solver_invocations_json",
        "runtime_solver_outcome_counts_json",
        "runtime_solver_status_counts_json",
    )
    if audit is None:
        execution = stored.run_payload.get("execution")
        pre_controller_failure = (
            isinstance(execution, Mapping)
            and execution.get("orchestration_failure") is True
            and stored.episode_result.failure_stage
            in {"orchestration_setup", "worker_process"}
        )
        if not pre_controller_failure:
            raise ValueError("verified controller metadata lacks runtime solver audit")
        return {
            "runtime_solver_audit_status": "unavailable_pre_controller_failure",
            **{name: None for name in column_names},
        }
    if not isinstance(audit, Mapping) or set(audit) != {
        "schema_version",
        "controller_record_count",
        "solver_attempt_count",
        "named_solver_attempt_count",
        "unnamed_solver_attempt_count",
        "solver_not_run_count",
        "solver_outcome_counts",
        "solver_status_counts",
        "solver_invocations",
    }:
        raise ValueError("runtime solver audit has the wrong fields")
    if audit["schema_version"] != PHASE6_RUNTIME_SOLVER_AUDIT_SCHEMA_VERSION:
        raise ValueError("runtime solver audit schema is unsupported")

    def count(name: str) -> int:
        value = audit[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"runtime solver audit {name} must be non-negative")
        return value

    record_count = count("controller_record_count")
    attempt_count = count("solver_attempt_count")
    named_count = count("named_solver_attempt_count")
    unnamed_count = count("unnamed_solver_attempt_count")
    not_run_count = count("solver_not_run_count")
    if named_count + unnamed_count != attempt_count:
        raise ValueError("runtime solver audit attempted counts are inconsistent")
    if attempt_count + not_run_count != record_count:
        raise ValueError("runtime solver audit record counts are inconsistent")

    def validated_counter(name: str) -> Mapping[str, int]:
        raw = audit[name]
        if not isinstance(raw, Mapping) or not all(
            isinstance(key, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
            for key, value in raw.items()
        ):
            raise ValueError(f"runtime solver audit {name} is malformed")
        if sum(raw.values()) != record_count:
            raise ValueError(f"runtime solver audit {name} count total is wrong")
        return raw

    outcomes = validated_counter("solver_outcome_counts")
    statuses = validated_counter("solver_status_counts")
    invocations = audit["solver_invocations"]
    if not isinstance(invocations, Sequence) or isinstance(
        invocations, (str, bytes, bytearray)
    ):
        raise ValueError("runtime solver audit invocations must be a sequence")
    if any(not isinstance(row, Mapping) for row in invocations):
        raise ValueError("runtime solver invocation rows must be objects")
    if sum(int(row.get("attempt_count", -1)) for row in invocations) != named_count:
        raise ValueError("runtime solver invocation count total is wrong")

    def compact(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    return {
        "runtime_solver_audit_status": "verified",
        "runtime_solver_record_count": record_count,
        "runtime_solver_attempt_count": attempt_count,
        "runtime_solver_named_attempt_count": named_count,
        "runtime_solver_unnamed_attempt_count": unnamed_count,
        "runtime_solver_not_run_count": not_run_count,
        "runtime_solver_invocations_json": compact(invocations),
        "runtime_solver_outcome_counts_json": compact(outcomes),
        "runtime_solver_status_counts_json": compact(statuses),
    }


def refresh_stage_aggregates(
    specs: Sequence[Phase6RunSpec],
    *,
    protocol_material: Mapping[str, Any],
) -> tuple[Path, Path]:
    """Atomically rebuild both CSVs from verified independent run envelopes."""

    if not specs:
        raise ValueError("cannot aggregate an empty run plan")
    stage = specs[0].stage
    if any(spec.stage != stage for spec in specs):
        raise ValueError("aggregate run specs must belong to one stage")
    execution_material = dict(strict_json_value(protocol_material))
    if stage == "tuning":
        execution_material["tuning_selection_record_sha256"] = None
    execution_material_sha = protocol_material_sha256(execution_material)
    if any(
        spec.artifact_state_sha256 != execution_material_sha for spec in specs
    ):
        raise RuntimeError(
            "aggregate protocol material differs from run execution provenance"
        )
    stored_runs = verified_stage_runs(specs)
    metrics = episode_results_frame(run.episode_result for run in stored_runs)
    stage_root = specs[0].paths.stage_root(specs[0].stage)
    metrics_path = stage_root / "per_episode_metrics.csv"
    _atomic_write_text(metrics_path, metrics.to_csv(index=False, lineterminator="\n"))

    material_sha = protocol_material_sha256(protocol_material)
    aggregate_tuning_selection_sha = protocol_material.get(
        "tuning_selection_record_sha256"
    )
    protocol_lock_sha = (
        sha256_file(specs[0].paths.final_protocol_lock)
        if specs[0].stage == "final" and specs[0].paths.final_protocol_lock.is_file()
        else None
    )
    protocol = load_frozen_phase6_protocol(specs[0].paths.experiments_config)
    truth_classes = {
        row.scenario_id: row.truth_class for row in protocol.scenario_variants
    }
    by_run_id = {spec.identity.run_id: spec for spec in specs}
    ledger_rows: list[dict[str, Any]] = []
    for stored in stored_runs:
        spec = by_run_id[stored.identity.run_id]
        provenance = _stored_provenance(stored, spec)
        config_rows = provenance["configs"]
        artifact_rows = provenance["artifacts"]
        assert isinstance(config_rows, Mapping)
        assert isinstance(artifact_rows, Mapping)
        journal_metadata = stored.run_payload[CANONICAL_DECISION_JOURNAL_PAYLOAD_KEY]
        assert isinstance(journal_metadata, Mapping)
        row = stored.episode_result.to_row()
        row.update(
            {
                "stage": provenance["stage"],
                "protocol_revision": provenance["protocol_revision"],
                "truth_class": truth_classes[spec.identity.scenario_id],
                "solver_tier": provenance["solver_tier"],
                "library_kind": provenance["library_kind"],
                "diagnostic_qualification": diagnostic_qualification_for_method(
                    spec.identity.method
                ),
                "truth_informed_upper_bound": spec.identity.method == "B4",
                "per_run_envelope_sha256": stored.sha256,
                "protocol_material_sha256": provenance[
                    "protocol_material_sha256"
                ],
                "aggregate_protocol_material_sha256": material_sha,
                "execution_artifact_state_sha256": provenance[
                    "artifact_state_sha256"
                ],
                "experiments_config_sha256": config_rows["experiments"][
                    "logical_sha256"
                ],
                "base_config_sha256": config_rows["base"]["logical_sha256"],
                "mpc_config_sha256": config_rows["mpc"]["logical_sha256"],
                "code_sha256": provenance["code_sha256"],
                "fixed_reference_selection_sha256": artifact_rows[
                    "fixed_reference_selection"
                ],
                "tuning_selection_record_sha256": provenance[
                    "tuning_selection_record_sha256"
                ],
                "aggregate_tuning_selection_record_sha256": (
                    aggregate_tuning_selection_sha
                ),
                "final_protocol_lock_file_sha256": protocol_lock_sha,
                "canonical_decision_journal_schema_version": journal_metadata[
                    "schema_version"
                ],
                "canonical_decision_journal_schema_sha256": journal_metadata[
                    "schema_sha256"
                ],
                "canonical_decision_journal_relative_path": journal_metadata[
                    "relative_path"
                ],
                "canonical_decision_journal_sha256": journal_metadata["sha256"],
                "canonical_decision_journal_row_count": journal_metadata[
                    "row_count"
                ],
                "canonical_decision_journal_compression": journal_metadata[
                    "compression"
                ],
                **_controller_metadata_columns(stored, spec),
                **_runtime_solver_audit_columns(stored),
                **_library_hash_columns(provenance, spec.identity.method),
            }
        )
        ledger_rows.append(row)
    ledger = pd.DataFrame.from_records(ledger_rows)
    ledger_path = stage_root / "experiment_ledger.csv"
    _atomic_write_text(ledger_path, ledger.to_csv(index=False, lineterminator="\n"))
    return metrics_path, ledger_path


def _finite_metric(values: Iterable[float | None]) -> np.ndarray:
    retained = [float(value) for value in values if value is not None]
    result = np.asarray(retained, dtype=np.float64)
    if result.size and not np.all(np.isfinite(result)):
        raise ValueError("tuning metrics contain non-finite values")
    return result


def write_tuning_selection_record(
    *,
    path: str | Path,
    protocol: ExperimentProtocol,
    stored_runs: Sequence[StoredRun],
    experiments_logical_sha256: str,
    resolved_candidate_sha256: str,
) -> Path:
    """Select the single carried-forward P candidate using tuning runs only."""

    destination = _resolved(path)
    if len(stored_runs) != EXPECTED_TUNING_RUN_COUNT:
        raise RuntimeError(
            "tuning selection requires all 21 scenarios x 10 seeds (210 rows)"
        )
    if any(run.identity.method != "P" for run in stored_runs):
        raise ValueError("tuning store contains a method other than P")
    expected_ids = {
        stable_run_id(
            stage="tuning",
            revision=protocol.revision,
            scenario_id=scenario.scenario_id,
            method_id="P",
            seed=seed,
        )
        for scenario in protocol.scenario_variants
        for seed in protocol.seeds_for(scenario.scenario_id, "tuning")
    }
    if {run.identity.run_id for run in stored_runs} != expected_ids:
        raise ValueError("tuning store does not exactly match the frozen pairing keys")
    results = tuple(run.episode_result for run in stored_runs)
    iae = _finite_metric(result.freq_iae for result in results)
    maximum = _finite_metric(result.max_abs_freq_hz for result in results)
    solve = _finite_metric(result.solve_time_mean_s for result in results)
    objectives = {
        "catastrophic_failure_rate": float(
            np.mean([bool(result.catastrophic_failure) for result in results])
        ),
        "mean_frequency_iae_hz_s": None if not iae.size else float(np.mean(iae)),
        "q95_max_abs_frequency_deviation_hz": (
            None if not maximum.size else float(np.quantile(maximum, 0.95))
        ),
        "mean_solver_wall_time_s": (
            None if not solve.size else float(np.mean(solve))
        ),
    }
    envelope_hashes = {
        run.identity.run_id: run.sha256
        for run in sorted(stored_runs, key=lambda item: item.identity.run_id)
    }
    payload = {
        "schema_version": PHASE6_TUNING_SELECTION_SCHEMA_VERSION,
        "selection_split": "closed_loop_validation",
        "seed_set": "tuning",
        "final_test_feedback_used": False,
        "candidate_count": 1,
        "selected_candidate_id": "phase5_carried_forward_P",
        "selected_resolved_config_sha256": resolved_candidate_sha256,
        "experiments_logical_sha256": experiments_logical_sha256,
        "ordered_objectives": list(protocol.tuning_selection.ordered_objectives),
        "objective_values": objectives,
        "registered_run_count": EXPECTED_TUNING_RUN_COUNT,
        "retained_failure_row_count": sum(
            not result.run_completed for result in results
        ),
        "metric_nonmissing_counts": {
            "frequency_iae": int(iae.size),
            "max_abs_frequency_deviation": int(maximum.size),
            "solver_wall_time": int(solve.size),
        },
        "run_envelope_set_sha256": sha256_json(envelope_hashes),
    }
    if destination.exists():
        if _read_json_mapping(destination) != payload:
            raise RuntimeError("existing tuning selection record differs; overwrite refused")
        return destination
    _atomic_write_json(destination, payload)
    return destination


def frozen_tuning_candidate_sha256(paths: Phase6Paths) -> str:
    """Hash the one Phase-5-carried-forward P candidate without test feedback."""

    code_files = dict(_code_manifest(paths))
    return sha256_json(
        {
            "method_id": "P",
            "mpc_config_sha256": config_sha256(load_yaml(paths.mpc_config)),
            "base_config_sha256": config_sha256(load_yaml(paths.base_config)),
            "native_binding_file_sha256": sha256_file(paths.native_binding),
            "native_ood_hysteresis_selection_file_sha256": sha256_file(
                paths.native_ood_hysteresis_selection
            ),
            "phase6_code_sha256": sha256_json(code_files),
        }
    )


def validate_tuning_selection_record(paths: Phase6Paths) -> Path:
    """Recompute the selection record from all 210 verified tuning envelopes."""

    _require_file(paths.tuning_selection_record, "tuning selection record")
    protocol = load_frozen_phase6_protocol(paths.experiments_config)
    execution_material = build_protocol_material(
        paths, include_tuning_selection=False
    )
    tuning_specs = build_run_plan(
        paths,
        stage="tuning",
        solver_tier="FINAL",
        protocol_material=execution_material,
    )
    stored_runs = verified_stage_runs(tuning_specs)
    if len(stored_runs) != EXPECTED_TUNING_RUN_COUNT:
        raise RuntimeError(
            "final stage requires all 210 verified tuning per-run envelopes"
        )
    # The writer is idempotent and refuses the existing file unless every
    # recomputed objective and the complete envelope-set hash are identical.
    return write_tuning_selection_record(
        path=paths.tuning_selection_record,
        protocol=protocol,
        stored_runs=stored_runs,
        experiments_logical_sha256=config_sha256(
            load_yaml(paths.experiments_config)
        ),
        resolved_candidate_sha256=frozen_tuning_candidate_sha256(paths),
    )


def execute_run_plan(
    specs: Sequence[Phase6RunSpec],
    *,
    workers: int,
) -> tuple[WorkerRunReceipt, ...]:
    """Execute/resume a plan with auditable, non-canonical failed attempts."""

    if isinstance(workers, bool) or not isinstance(workers, int) or workers <= 0:
        raise ValueError("workers must be a positive integer")
    if not specs:
        return ()
    store = PerRunExperimentStore(specs[0].paths.run_store_root(specs[0].stage))
    receipts: list[WorkerRunReceipt] = []
    pending: list[Phase6RunSpec] = []
    for spec in specs:
        existing = store.load(spec.identity)
        if existing is None:
            pending.append(spec)
        else:
            _stored_provenance(existing, spec)
            receipts.append(
                WorkerRunReceipt(
                    run_id=spec.identity.run_id,
                    envelope_sha256=existing.sha256,
                    resumed=True,
                    scientific_success=bool(
                        existing.episode_result.scientific_success
                    ),
                )
            )
    if not pending:
        by_id = {receipt.run_id: receipt for receipt in receipts}
        return tuple(by_id[spec.identity.run_id] for spec in specs)
    if workers == 1:
        for spec in pending:
            attempt_id = _new_attempt_id()
            try:
                receipts.append(_execute_run_spec(spec, attempt_id))
            except Exception as exc:
                receipt = _ensure_phase6_attempt_receipt(
                    paths=spec.paths,
                    stage=spec.stage,
                    attempt_id=attempt_id,
                    failure_stage="single_worker_escape",
                    origin="parent",
                    error=exc,
                    spec=spec,
                )
                raise _stage_failure_with_receipt(
                    message=(
                        f"run {spec.identity.run_id!r} failed; canonical run_id "
                        "remains retryable"
                    ),
                    receipt=receipt,
                    error=exc,
                )
    else:
        paths = specs[0].paths
        stage = specs[0].stage
        try:
            executor = ProcessPoolExecutor(max_workers=workers)
        except Exception as exc:
            receipt = write_phase6_attempt_receipt(
                paths=paths,
                stage=stage,
                attempt_id=_new_attempt_id(),
                failure_stage="process_pool_creation",
                origin="parent",
                error=exc,
                spec=None,
            )
            raise _stage_failure_with_receipt(
                message="process-pool creation failed before any canonical publication",
                receipt=receipt,
                error=exc,
            )
        try:
            with executor:
                futures: dict[Any, tuple[Phase6RunSpec, str]] = {}
                for spec in pending:
                    attempt_id = _new_attempt_id()
                    try:
                        future = executor.submit(_execute_run_spec, spec, attempt_id)
                        futures[future] = (spec, attempt_id)
                    except Exception as exc:
                        for future in futures:
                            future.cancel()
                        receipt = _ensure_phase6_attempt_receipt(
                            paths=spec.paths,
                            stage=spec.stage,
                            attempt_id=attempt_id,
                            failure_stage="process_pool_submission",
                            origin="parent",
                            error=exc,
                            spec=spec,
                        )
                        raise _stage_failure_with_receipt(
                            message=(
                                f"submission failed for run {spec.identity.run_id!r}; "
                                "canonical run_id remains retryable"
                            ),
                            receipt=receipt,
                            error=exc,
                        )
                for future in as_completed(futures):
                    spec, attempt_id = futures[future]
                    try:
                        receipts.append(future.result())
                    except Exception as exc:
                        for pending_future in futures:
                            pending_future.cancel()
                        receipt = _ensure_phase6_attempt_receipt(
                            paths=spec.paths,
                            stage=spec.stage,
                            attempt_id=attempt_id,
                            failure_stage="worker_future",
                            origin="parent",
                            error=exc,
                            spec=spec,
                        )
                        raise _stage_failure_with_receipt(
                            message=(
                                f"worker failed for run {spec.identity.run_id!r}; "
                                "canonical run_id remains retryable"
                            ),
                            receipt=receipt,
                            error=exc,
                        )
        except Phase6StageExecutionError:
            raise
        except Exception as exc:
            receipt = write_phase6_attempt_receipt(
                paths=paths,
                stage=stage,
                attempt_id=_new_attempt_id(),
                failure_stage="process_pool_runtime",
                origin="parent",
                error=exc,
                spec=None,
            )
            raise _stage_failure_with_receipt(
                message="process-pool runtime failed; canonical run_ids remain retryable",
                receipt=receipt,
                error=exc,
            )
    by_id = {receipt.run_id: receipt for receipt in receipts}
    if len(by_id) != len(specs):
        raise RuntimeError("run execution did not retain exactly one receipt per plan row")
    return tuple(by_id[spec.identity.run_id] for spec in specs)


def validate_stage_worker_count(stage: Stage, workers: int) -> int:
    """Freeze tuning/final process concurrency because wall-time limits matter."""

    if isinstance(workers, bool) or not isinstance(workers, int) or workers <= 0:
        raise ValueError("workers must be a positive integer")
    if stage not in {"smoke", "tuning", "final"}:
        raise ValueError("stage must be smoke, tuning, or final")
    if stage in {"tuning", "final"} and workers != FROZEN_TUNING_FINAL_WORKER_COUNT:
        raise ValueError(
            "tuning/final execution requires the frozen worker count "
            f"{FROZEN_TUNING_FINAL_WORKER_COUNT}; solver wall-time limits make "
            "process concurrency part of the experiment protocol"
        )
    return workers


def run_phase6_stage(
    paths: Phase6Paths,
    *,
    stage: Stage,
    workers: int = 1,
    solver_tier: str | None = None,
    method_ids: Sequence[str] | None = None,
    scenario_ids: Sequence[str] | None = None,
    max_runs: int | None = None,
) -> Phase6StageResult:
    """Validate, lock (for final), execute, resume, and aggregate one stage."""

    validate_stage_worker_count(stage, workers)
    load_frozen_phase6_protocol(paths.experiments_config)
    validate_phase6_artifacts(paths)
    if stage == "final":
        validate_tuning_selection_record(paths)
    elif stage == "tuning" and paths.tuning_selection_record.is_file():
        # A completed tuning-stage resume starts from the same post-selection
        # snapshot written on its first successful completion.
        validate_tuning_selection_record(paths)
    # Tuning episodes never consume their subsequently generated selection
    # record.  Keep their execution provenance stable across a completed-stage
    # resume while publishing the post-selection snapshot separately.
    execution_include_tuning = stage == "final"
    execution_material = build_protocol_material(
        paths, include_tuning_selection=execution_include_tuning
    )
    execution_material_sha = protocol_material_sha256(execution_material)
    material = (
        build_protocol_material(paths, include_tuning_selection=True)
        if stage == "tuning" and paths.tuning_selection_record.is_file()
        else execution_material
    )
    specs = build_run_plan(
        paths,
        stage=stage,
        solver_tier=solver_tier,
        method_ids=method_ids,
        scenario_ids=scenario_ids,
        max_runs=max_runs,
        artifact_state_sha256=execution_material_sha,
        protocol_material=execution_material,
    )
    stage_root = paths.stage_root(stage)
    stage_root.mkdir(parents=True, exist_ok=True)
    snapshot_path = stage_root / "protocol_snapshot.json"
    snapshot = _protocol_envelope(material)
    if snapshot_path.exists() and _read_json_mapping(snapshot_path) != snapshot:
        if any(paths.run_store_root(stage).glob("*.json")):
            raise RuntimeError("stage protocol changed after its run store became non-empty")
    _atomic_write_json(snapshot_path, snapshot)

    lock_path: Path | None = None
    if stage == "final":
        lock_path = ensure_final_protocol_lock(
            lock_path=paths.final_protocol_lock,
            run_store_root=paths.run_store_root("final"),
            tuning_selection_record_path=paths.tuning_selection_record,
            material=material,
        )
    execute_run_plan(specs, workers=workers)
    stored_runs = verified_stage_runs(specs)
    if len(stored_runs) != len(specs):
        raise RuntimeError("one or more planned runs lack a verified per-run envelope")
    post_execution_material = build_protocol_material(
        paths, include_tuning_selection=execution_include_tuning
    )
    if (
        protocol_material_sha256(post_execution_material)
        != execution_material_sha
    ):
        raise RuntimeError(
            "Phase-6 inputs or code changed while the stage was executing; "
            "aggregate publication is refused"
        )

    tuning_path: Path | None = None
    if stage == "tuning":
        protocol = load_frozen_phase6_protocol(paths.experiments_config)
        candidate_hash = frozen_tuning_candidate_sha256(paths)
        tuning_path = write_tuning_selection_record(
            path=paths.tuning_selection_record,
            protocol=protocol,
            stored_runs=stored_runs,
            experiments_logical_sha256=config_sha256(
                load_yaml(paths.experiments_config)
            ),
            resolved_candidate_sha256=candidate_hash,
        )
        material = build_protocol_material(paths, include_tuning_selection=True)
        _atomic_write_json(snapshot_path, _protocol_envelope(material))

    metrics_path, ledger_path = refresh_stage_aggregates(
        specs, protocol_material=material
    )
    return Phase6StageResult(
        stage=stage,
        planned_run_count=len(specs),
        executed_or_resumed_count=len(stored_runs),
        per_episode_metrics_path=metrics_path,
        experiment_ledger_path=ledger_path,
        protocol_snapshot_path=snapshot_path,
        tuning_selection_record_path=tuning_path,
        protocol_lock_path=lock_path,
    )


def utc_timestamp() -> str:
    """Human-facing CLI timestamp; never included in scientific lock material."""

    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "EXPECTED_FINAL_RUN_COUNT",
    "EXPECTED_METHOD_COUNT",
    "EXPECTED_SCENARIO_COUNT",
    "EXPECTED_SMOKE_RUN_COUNT",
    "EXPECTED_TUNING_RUN_COUNT",
    "PHASE6_ATTEMPT_RECEIPT_SCHEMA_VERSION",
    "PHASE6_ORCHESTRATION_SCHEMA_VERSION",
    "PHASE6_PROTOCOL_LOCK_SCHEMA_VERSION",
    "PHASE6_RUN_PROVENANCE_SCHEMA_VERSION",
    "PHASE6_RUNTIME_SOLVER_AUDIT_SCHEMA_VERSION",
    "PHASE6_TUNING_SELECTION_SCHEMA_VERSION",
    "Phase6Paths",
    "Phase6AttemptReceipt",
    "Phase6RunSpec",
    "Phase6StageExecutionError",
    "Phase6StageResult",
    "ValidatedPhase6Artifacts",
    "WorkerRunReceipt",
    "build_metric_config",
    "build_protocol_material",
    "build_run_plan",
    "diagnostic_qualification_for_method",
    "ensure_final_protocol_lock",
    "execute_run_plan",
    "expected_provenance",
    "frozen_tuning_candidate_sha256",
    "library_kind_for_method",
    "load_component_mapping_eval_only",
    "load_frozen_phase6_protocol",
    "load_phase6_attempt_receipts",
    "load_simulator_private_modes_eval_only",
    "protocol_material_sha256",
    "refresh_stage_aggregates",
    "resolve_repo_or_cwd_path",
    "responsibility_event_time_eval_only",
    "run_phase6_stage",
    "stable_run_id",
    "utc_timestamp",
    "validate_b1_selection",
    "validate_phase6_artifacts",
    "validate_tuning_selection_record",
    "validate_stage_worker_count",
    "verified_stage_runs",
    "write_tuning_selection_record",
    "write_phase6_attempt_receipt",
]
