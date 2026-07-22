"""Authenticated canonical Phase-6 decisions and controller-free replay.

The final MPC solver deadline is intentionally a wall-clock deadline.  A
post-hoc controller replay can therefore choose a different action at a
deadline boundary even when every scientific input is identical.  This module
records the actions that were actually returned during the canonical episode,
plus the controller-visible and evaluator-only endpoint state needed to audit
a simulator-only replay.

Each journal is a content-addressed ZSTD Parquet file.  Its immutable metadata
is embedded in the per-run JSON envelope; loading validates the envelope
metadata, file digest, Arrow schema, Parquet compression, identity, and row
semantics before exposing any records.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path, PurePosixPath
import tempfile
from types import MappingProxyType
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from d5freq.evaluation.experiment_store import (
    RunIdentity,
    RunIntegrityError,
    StoredRun,
    strict_json_value,
)
from d5freq.evaluation.results_schema import EpisodeResult
from d5freq.interfaces import ControlAction, Measurement
from d5freq.utils.hashing import canonical_json_bytes, sha256_file, sha256_json


CANONICAL_DECISION_JOURNAL_SCHEMA_VERSION = (
    "d5freq.phase6_canonical_decision_journal.v1"
)
CANONICAL_DECISION_JOURNAL_PAYLOAD_KEY = "canonical_decision_journal"
CANONICAL_DECISION_JOURNAL_COMPRESSION = "zstd"
_JOURNAL_DIRECTORY = "j"
_FLOAT_TOLERANCE = 1.0e-12
_WINDOWS_SAFE_PATH_LIMIT = 250

_BASE_ARROW_SCHEMA = pa.schema(
    [
        pa.field("row_index", pa.int32(), nullable=False),
        pa.field("time_s", pa.float64(), nullable=False),
        pa.field("omega_measurement_pu", pa.float64(), nullable=False),
        pa.field("p_mech_measurement_pu", pa.float64(), nullable=False),
        pa.field("p_ibr_measurement_pu", pa.float64(), nullable=False),
        pa.field("u_sg_prev_measurement_pu", pa.float64(), nullable=False),
        pa.field("u_ibr_prev_measurement_pu", pa.float64(), nullable=False),
        pa.field("truth_available", pa.bool_(), nullable=False),
        pa.field("omega_true_pu", pa.float64()),
        pa.field("rocof_true_hz_per_s", pa.float64()),
        pa.field("p_mech_true_pu", pa.float64()),
        pa.field("p_ibr_true_pu", pa.float64()),
        pa.field("load_disturbance_pu", pa.float64()),
        pa.field("true_mode_eval_only", pa.string()),
        pa.field("action_returned", pa.bool_(), nullable=False),
        pa.field("step_completed", pa.bool_(), nullable=False),
        pa.field("u_sg_pu", pa.float64()),
        pa.field("u_ibr_pu", pa.float64()),
        pa.field("controller_state", pa.string()),
        pa.field("solver_status", pa.string()),
        pa.field("solver_outcome", pa.string()),
        pa.field("solve_time_s", pa.float64()),
        pa.field("max_freq_slack_hz", pa.float64()),
        pa.field("max_rocof_slack_hz_s", pa.float64()),
        pa.field("max_power_slack_pu", pa.float64()),
        pa.field("diagnostic_state", pa.string()),
        pa.field("controller_record_json", pa.string()),
        pa.field("terminal_endpoint", pa.bool_(), nullable=False),
    ]
)


def _schema_descriptor() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "name": field.name,
            "arrow_type": str(field.type),
            "nullable": field.nullable,
        }
        for field in _BASE_ARROW_SCHEMA
    )


CANONICAL_DECISION_JOURNAL_SCHEMA_SHA256 = sha256_json(_schema_descriptor())

_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "schema_sha256",
        "relative_path",
        "sha256",
        "size_bytes",
        "row_count",
        "compression",
        "stage",
        "run_id",
        "scenario_id",
        "method",
        "seed",
        "run_completed",
        "metrics_complete",
        "simulation_entered",
        "action_returned_count",
        "completed_step_count",
    }
)


@dataclass(frozen=True, slots=True)
class CanonicalDecisionJournal:
    """A fully verified journal bound to one immutable run envelope."""

    identity: RunIdentity
    path: Path
    metadata: Mapping[str, Any]
    rows: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class CanonicalJournalReplay:
    """Simulator-only replay output; no controller or solver is accepted."""

    identity: RunIdentity
    measurements: tuple[Measurement, ...]
    actions: tuple[ControlAction, ...]
    control_trajectory: tuple[Mapping[str, Any], ...]
    high_frequency_truth: tuple[Mapping[str, Any], ...]
    truth_intervals: tuple[Mapping[str, Any], ...]
    controller_records: tuple[Mapping[str, Any], ...]
    simulator_evaluations: tuple[Mapping[str, Any], ...]
    consistency_audit: Mapping[str, Any]


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RunIntegrityError(f"{name} must be a real number")
    result = float(value)
    if not math.isfinite(result):
        raise RunIntegrityError(f"{name} must be finite")
    return result


def _strict_record_json(record: Mapping[str, Any]) -> str:
    normalized = strict_json_value(record)
    if not isinstance(normalized, Mapping):
        raise TypeError("controller record must normalize to an object")
    return canonical_json_bytes(normalized).decode("utf-8")


def _record_json_value(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, str):
        raise RunIntegrityError(f"{name} must be a JSON object string")
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RunIntegrityError(f"{name} is invalid JSON: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise RunIntegrityError(f"{name} must decode to an object")
    if canonical_json_bytes(parsed).decode("utf-8") != value:
        raise RunIntegrityError(f"{name} is not canonical JSON")
    return MappingProxyType(dict(parsed))


def _solver_outcome(status: str) -> str:
    normalized = status.strip().lower()
    if normalized == "optimal":
        return "success"
    if normalized == "optimal_inaccurate":
        return "inaccurate"
    if normalized.startswith("infeasible"):
        return "infeasible"
    if normalized == "timeout":
        return "timeout"
    if normalized in {"fallback_lqi", "not_applicable", "not_run", "skipped"}:
        return "not_run"
    return "error"


def _truth_point_for_endpoint(
    endpoint_index: int,
    simulator_evaluations: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if not simulator_evaluations:
        return None
    evaluation_index = 0 if endpoint_index == 0 else endpoint_index - 1
    if evaluation_index >= len(simulator_evaluations):
        return None
    evaluation = simulator_evaluations[evaluation_index]
    raw = evaluation.get("true_trace_points_eval_only", ())
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise TypeError("true_trace_points_eval_only must be a sequence")
    if not raw:
        return None
    selected = raw[0] if endpoint_index == 0 else raw[-1]
    if not isinstance(selected, Mapping):
        raise TypeError("truth endpoint must be a mapping")
    return selected


def _nullable_truth(point: Mapping[str, Any] | None, name: str) -> Any:
    if point is None:
        return None
    if name not in point:
        raise KeyError(f"truth endpoint lacks {name}")
    return point[name]


def build_canonical_decision_rows(data: object) -> tuple[dict[str, Any], ...]:
    """Build the fixed-schema endpoint journal from runner evaluation data."""

    measurements = tuple(getattr(data, "measurements"))
    actions = tuple(getattr(data, "actions"))
    evaluations = tuple(getattr(data, "simulator_evaluations"))
    records = tuple(getattr(data, "controller_records"))
    run_completed = bool(getattr(data, "run_completed"))
    if len(evaluations) > len(actions):
        raise ValueError("simulator evaluation count exceeds returned action count")
    if len(measurements) not in {0, len(evaluations) + 1}:
        raise ValueError("measurement/evaluation endpoint counts are inconsistent")
    if records and len(records) > len(actions):
        raise ValueError("controller record count exceeds returned action count")

    rows: list[dict[str, Any]] = []
    for index, measurement in enumerate(measurements):
        if not isinstance(measurement, Measurement):
            raise TypeError("journal measurements must contain Measurement values")
        action = actions[index] if index < len(actions) else None
        if action is not None and not isinstance(action, ControlAction):
            raise TypeError("journal actions must contain ControlAction values")
        record = records[index] if index < len(records) else None
        if record is not None and not isinstance(record, Mapping):
            raise TypeError("journal controller records must be mappings")
        point = _truth_point_for_endpoint(index, evaluations)
        status = None if action is None else action.solver_status
        outcome = (
            None
            if action is None
            else str(
                (record or {}).get(
                    "solver_outcome", _solver_outcome(action.solver_status)
                )
            )
        )
        rows.append(
            {
                "row_index": index,
                "time_s": measurement.time_s,
                "omega_measurement_pu": measurement.omega_pu,
                "p_mech_measurement_pu": measurement.p_mech_pu,
                "p_ibr_measurement_pu": measurement.p_ibr_pu,
                "u_sg_prev_measurement_pu": measurement.u_sg_prev_pu,
                "u_ibr_prev_measurement_pu": measurement.u_ibr_prev_pu,
                "truth_available": point is not None,
                "omega_true_pu": _nullable_truth(point, "omega_true_pu"),
                "rocof_true_hz_per_s": _nullable_truth(
                    point, "rocof_true_hz_per_s"
                ),
                "p_mech_true_pu": _nullable_truth(point, "p_mech_true_pu"),
                "p_ibr_true_pu": _nullable_truth(point, "p_ibr_true_pu"),
                "load_disturbance_pu": _nullable_truth(
                    point, "load_disturbance_pu"
                ),
                "true_mode_eval_only": _nullable_truth(
                    point, "true_mode_eval_only"
                ),
                "action_returned": action is not None,
                "step_completed": index < len(evaluations),
                "u_sg_pu": None if action is None else action.u_sg_pu,
                "u_ibr_pu": None if action is None else action.u_ibr_pu,
                "controller_state": (
                    None if action is None else action.controller_state
                ),
                "solver_status": status,
                "solver_outcome": outcome,
                "solve_time_s": None if action is None else action.solve_time_s,
                "max_freq_slack_hz": (
                    None if action is None else action.max_freq_slack_hz
                ),
                "max_rocof_slack_hz_s": (
                    None
                    if action is None
                    else float(
                        (record or {}).get(
                            "max_rocof_slack_hz_s",
                            (record or {}).get(
                                "max_rocof_slack_hz_per_s", 0.0
                            ),
                        )
                    )
                ),
                "max_power_slack_pu": (
                    None
                    if action is None
                    else float((record or {}).get("max_power_slack_pu", 0.0))
                ),
                "diagnostic_state": (
                    None
                    if action is None
                    else str((record or {}).get("diagnostic_state", "UNSPECIFIED"))
                ),
                "controller_record_json": (
                    None if record is None else _strict_record_json(record)
                ),
                "terminal_endpoint": (
                    run_completed
                    and index == len(measurements) - 1
                    and action is None
                ),
            }
        )
    return tuple(rows)


def _arrow_schema_metadata(
    *, stage: str, identity: RunIdentity
) -> dict[bytes, bytes]:
    return {
        b"d5freq_schema_version": CANONICAL_DECISION_JOURNAL_SCHEMA_VERSION.encode(),
        b"d5freq_schema_sha256": CANONICAL_DECISION_JOURNAL_SCHEMA_SHA256.encode(),
        b"d5freq_stage": stage.encode("utf-8"),
        b"d5freq_run_id": identity.run_id.encode("utf-8"),
        b"d5freq_scenario_id": identity.scenario_id.encode("utf-8"),
        b"d5freq_method": identity.method.encode("utf-8"),
        b"d5freq_seed": str(identity.seed).encode("ascii"),
    }


def _fsync_file(path: Path) -> None:
    # Windows rejects ``fsync`` on a read-only descriptor.
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _validate_windows_path_budget(stage_root: Path) -> None:
    if os.name != "nt":
        return
    longest_target = stage_root / _JOURNAL_DIRECTORY / f"{'0' * 64}.parquet"
    length = len(str(longest_target))
    if length >= _WINDOWS_SAFE_PATH_LIMIT:
        raise RuntimeError(
            "canonical journal path would exceed the conservative Windows "
            f"path budget ({length} >= {_WINDOWS_SAFE_PATH_LIMIT}); choose a "
            "shorter Phase-6 output_root before starting the episode"
        )


def write_canonical_decision_journal(
    *,
    stage_root: str | Path,
    stage: str,
    identity: RunIdentity,
    data: object,
    episode_result: EpisodeResult,
) -> Mapping[str, Any]:
    """Atomically write a content-addressed ZSTD journal and return metadata."""

    if not isinstance(identity, RunIdentity):
        raise TypeError("identity must be a RunIdentity")
    if not isinstance(episode_result, EpisodeResult):
        raise TypeError("episode_result must be an EpisodeResult")
    if stage not in {"smoke", "tuning", "final"}:
        raise ValueError("stage must be smoke, tuning, or final")
    if getattr(data, "identity", None) != identity:
        raise ValueError("journal evaluation data identity differs from the run")
    if (
        episode_result.run_id,
        episode_result.scenario_id,
        episode_result.method,
        episode_result.seed,
    ) != (
        identity.run_id,
        identity.scenario_id,
        identity.method,
        identity.seed,
    ):
        raise ValueError("journal EpisodeResult identity differs from the run")

    rows = build_canonical_decision_rows(data)
    schema = _BASE_ARROW_SCHEMA.with_metadata(
        _arrow_schema_metadata(stage=stage, identity=identity)
    )
    table = pa.Table.from_pylist(list(rows), schema=schema)
    root = Path(stage_root).expanduser().resolve()
    # Fail before creating either the journal directory or a temporary file.
    _validate_windows_path_budget(root)
    run_directory = root / _JOURNAL_DIRECTORY
    run_directory.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".j.",
            suffix=".tmp",
            dir=run_directory,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        pq.write_table(
            table,
            temporary,
            compression=CANONICAL_DECISION_JOURNAL_COMPRESSION,
            use_dictionary=False,
            write_statistics=True,
        )
        _fsync_file(temporary)
        digest = sha256_file(temporary)
        destination = run_directory / f"{digest}.parquet"
        if destination.exists():
            if sha256_file(destination) != digest:
                raise RunIntegrityError(
                    "content-addressed journal destination has the wrong digest"
                )
            temporary.unlink()
            temporary = None
        else:
            os.replace(temporary, destination)
            temporary = None
        if sha256_file(destination) != digest:
            raise RunIntegrityError("atomic journal publication could not be verified")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    relative_path = destination.relative_to(root).as_posix()
    metadata = {
        "schema_version": CANONICAL_DECISION_JOURNAL_SCHEMA_VERSION,
        "schema_sha256": CANONICAL_DECISION_JOURNAL_SCHEMA_SHA256,
        "relative_path": relative_path,
        "sha256": digest,
        "size_bytes": destination.stat().st_size,
        "row_count": len(rows),
        "compression": CANONICAL_DECISION_JOURNAL_COMPRESSION,
        "stage": stage,
        "run_id": identity.run_id,
        "scenario_id": identity.scenario_id,
        "method": identity.method,
        "seed": identity.seed,
        "run_completed": episode_result.run_completed,
        "metrics_complete": episode_result.metrics_complete,
        "simulation_entered": bool(getattr(data, "measurements")),
        "action_returned_count": len(getattr(data, "actions")),
        "completed_step_count": len(getattr(data, "simulator_evaluations")),
    }
    normalized = strict_json_value(metadata)
    assert isinstance(normalized, Mapping)
    return MappingProxyType(dict(normalized))


def make_canonical_decision_journal_writer(
    *, stage_root: str | Path, stage: str, identity: RunIdentity
):
    """Return the runner callback that binds one journal to one run."""

    if stage not in {"smoke", "tuning", "final"}:
        raise ValueError("stage must be smoke, tuning, or final")
    if not isinstance(identity, RunIdentity):
        raise TypeError("identity must be a RunIdentity")
    resolved_stage_root = Path(stage_root).expanduser().resolve()
    # Phase-6 constructs this writer before entering the runner, so an unsafe
    # Windows output root fails before a 180-second episode does any work.
    _validate_windows_path_budget(resolved_stage_root)

    def write(data: object, episode_result: EpisodeResult) -> Mapping[str, Any]:
        metadata = write_canonical_decision_journal(
            stage_root=resolved_stage_root,
            stage=stage,
            identity=identity,
            data=data,
            episode_result=episode_result,
        )
        return {CANONICAL_DECISION_JOURNAL_PAYLOAD_KEY: metadata}

    return write


def _safe_journal_path(stage_root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise RunIntegrityError("journal relative_path must be a non-empty string")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise RunIntegrityError("journal relative_path is unsafe")
    if not pure.parts or pure.parts[0] != _JOURNAL_DIRECTORY:
        raise RunIntegrityError("journal relative_path is outside its journal directory")
    path = (stage_root / Path(*pure.parts)).resolve()
    try:
        path.relative_to(stage_root)
    except ValueError as exc:
        raise RunIntegrityError("journal relative_path escapes the stage root") from exc
    return path


def _validate_metadata(
    metadata: Mapping[str, Any], stored: StoredRun
) -> tuple[Path, str]:
    if frozenset(metadata) != _METADATA_KEYS:
        raise RunIntegrityError("canonical journal metadata keys do not match schema")
    if metadata["schema_version"] != CANONICAL_DECISION_JOURNAL_SCHEMA_VERSION:
        raise RunIntegrityError("canonical journal schema_version mismatch")
    if metadata["schema_sha256"] != CANONICAL_DECISION_JOURNAL_SCHEMA_SHA256:
        raise RunIntegrityError("canonical journal schema_sha256 mismatch")
    if metadata["compression"] != CANONICAL_DECISION_JOURNAL_COMPRESSION:
        raise RunIntegrityError("canonical journal must declare ZSTD compression")
    for key, expected in (
        ("run_id", stored.identity.run_id),
        ("scenario_id", stored.identity.scenario_id),
        ("method", stored.identity.method),
        ("seed", stored.identity.seed),
        ("run_completed", stored.episode_result.run_completed),
        ("metrics_complete", stored.episode_result.metrics_complete),
    ):
        if metadata[key] != expected:
            raise RunIntegrityError(f"canonical journal {key} differs from envelope")
    stage = metadata["stage"]
    if stage not in {"smoke", "tuning", "final"}:
        raise RunIntegrityError("canonical journal stage is invalid")
    for key in (
        "size_bytes",
        "row_count",
        "action_returned_count",
        "completed_step_count",
    ):
        value = metadata[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RunIntegrityError(f"canonical journal {key} must be non-negative")
    if not isinstance(metadata["simulation_entered"], bool):
        raise RunIntegrityError("canonical journal simulation_entered must be boolean")
    digest = metadata["sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise RunIntegrityError("canonical journal SHA-256 is malformed")
    stage_root = stored.path.resolve().parent.parent
    path = _safe_journal_path(stage_root, metadata["relative_path"])
    if path.parent != stage_root / _JOURNAL_DIRECTORY or path.name != f"{digest}.parquet":
        raise RunIntegrityError("canonical journal path is not content addressed")
    return path, stage


def _validate_rows(
    rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
) -> None:
    if len(rows) != metadata["row_count"]:
        raise RunIntegrityError("canonical journal row count mismatch")
    previous_time: float | None = None
    action_count = 0
    completed_count = 0
    action_prefix_open = True
    completed_prefix_open = True
    for index, row in enumerate(rows):
        if row.get("row_index") != index:
            raise RunIntegrityError("canonical journal row_index is not consecutive")
        time_s = _finite(row.get("time_s"), f"journal row {index} time_s")
        if time_s < 0.0 or (
            previous_time is not None and time_s <= previous_time
        ):
            raise RunIntegrityError("canonical journal endpoint times must increase")
        previous_time = time_s
        action_returned = row.get("action_returned")
        step_completed = row.get("step_completed")
        terminal = row.get("terminal_endpoint")
        if not all(isinstance(value, bool) for value in (action_returned, step_completed, terminal)):
            raise RunIntegrityError("canonical journal Boolean flags are malformed")
        if action_returned:
            if not action_prefix_open:
                raise RunIntegrityError("canonical journal actions are not a prefix")
            action_count += 1
            for key in ("u_sg_pu", "u_ibr_pu", "solve_time_s", "max_freq_slack_hz"):
                _finite(row.get(key), f"journal row {index} {key}")
            for key in ("controller_state", "solver_status", "solver_outcome"):
                if not isinstance(row.get(key), str) or not row[key]:
                    raise RunIntegrityError(f"journal row {index} {key} is malformed")
            record_json = row.get("controller_record_json")
            if record_json is not None:
                _record_json_value(record_json, f"journal row {index} controller_record_json")
        else:
            action_prefix_open = False
        if step_completed:
            if not completed_prefix_open or not action_returned or index + 1 >= len(rows):
                raise RunIntegrityError("canonical journal completed steps are malformed")
            completed_count += 1
        else:
            completed_prefix_open = False
        truth_available = row.get("truth_available")
        if not isinstance(truth_available, bool):
            raise RunIntegrityError("canonical journal truth_available is malformed")
        if truth_available:
            for key in (
                "omega_true_pu",
                "rocof_true_hz_per_s",
                "p_mech_true_pu",
                "p_ibr_true_pu",
                "load_disturbance_pu",
            ):
                _finite(row.get(key), f"journal row {index} {key}")
            if not isinstance(row.get("true_mode_eval_only"), str):
                raise RunIntegrityError("canonical journal truth mode is malformed")
        if terminal and (index != len(rows) - 1 or action_returned):
            raise RunIntegrityError("canonical journal terminal marker is malformed")
    if action_count != metadata["action_returned_count"]:
        raise RunIntegrityError("canonical journal action count mismatch")
    if completed_count != metadata["completed_step_count"]:
        raise RunIntegrityError("canonical journal completed-step count mismatch")
    if bool(rows) != metadata["simulation_entered"]:
        raise RunIntegrityError("canonical journal simulation_entered mismatch")
    if metadata["run_completed"]:
        if not rows or not rows[-1]["terminal_endpoint"]:
            raise RunIntegrityError("completed canonical run lacks terminal endpoint")
        if completed_count != len(rows) - 1 or action_count != completed_count:
            raise RunIntegrityError("completed canonical journal has incomplete actions")


def load_and_verify_canonical_decision_journal(
    stored_run: StoredRun,
) -> CanonicalDecisionJournal:
    """Authenticate and load the journal referenced by ``stored_run``."""

    if not isinstance(stored_run, StoredRun):
        raise TypeError("stored_run must be a StoredRun")
    raw = stored_run.run_payload.get(CANONICAL_DECISION_JOURNAL_PAYLOAD_KEY)
    if not isinstance(raw, Mapping):
        raise RunIntegrityError(
            f"stored run {stored_run.identity.run_id!r} lacks canonical decision journal"
        )
    metadata = strict_json_value(raw)
    if not isinstance(metadata, Mapping):
        raise RunIntegrityError("canonical journal metadata must be an object")
    path, stage = _validate_metadata(metadata, stored_run)
    if not path.is_file():
        raise RunIntegrityError(f"canonical journal file is missing: {path.name}")
    if path.stat().st_size != metadata["size_bytes"]:
        raise RunIntegrityError("canonical journal size differs from envelope")
    if sha256_file(path) != metadata["sha256"]:
        raise RunIntegrityError("canonical journal SHA-256 differs from envelope")
    try:
        parquet = pq.ParquetFile(path)
    except Exception as exc:
        raise RunIntegrityError(f"cannot open canonical journal Parquet: {exc}") from exc
    if parquet.metadata.num_rows != metadata["row_count"]:
        raise RunIntegrityError("canonical journal Parquet row count mismatch")
    arrow_schema = parquet.schema_arrow
    if not arrow_schema.remove_metadata().equals(_BASE_ARROW_SCHEMA):
        raise RunIntegrityError("canonical journal Arrow schema mismatch")
    if arrow_schema.metadata != _arrow_schema_metadata(
        stage=stage, identity=stored_run.identity
    ):
        raise RunIntegrityError("canonical journal Arrow identity metadata mismatch")
    compressions = {
        str(parquet.metadata.row_group(group).column(column).compression).upper()
        for group in range(parquet.metadata.num_row_groups)
        for column in range(parquet.metadata.row_group(group).num_columns)
    }
    if compressions and compressions != {"ZSTD"}:
        raise RunIntegrityError("canonical journal Parquet columns are not all ZSTD")
    try:
        table = parquet.read()
        rows = tuple(MappingProxyType(dict(row)) for row in table.to_pylist())
    except Exception as exc:
        raise RunIntegrityError(f"cannot read canonical journal records: {exc}") from exc
    _validate_rows(rows, metadata)
    return CanonicalDecisionJournal(
        identity=stored_run.identity,
        path=path,
        metadata=MappingProxyType(dict(metadata)),
        rows=rows,
    )


def _assert_close(actual: object, expected: object, name: str) -> float:
    actual_value = _finite(actual, f"actual {name}")
    expected_value = _finite(expected, f"journal {name}")
    difference = abs(actual_value - expected_value)
    if difference > _FLOAT_TOLERANCE:
        raise RunIntegrityError(
            f"canonical journal replay {name} mismatch: "
            f"actual={actual_value}, expected={expected_value}"
        )
    return difference


def _verify_measurement(
    measurement: Measurement, row: Mapping[str, Any], endpoint_index: int
) -> float:
    if not isinstance(measurement, Measurement):
        raise RunIntegrityError("simulator replay did not return Measurement")
    maximum = 0.0
    for attribute, column in (
        ("time_s", "time_s"),
        ("omega_pu", "omega_measurement_pu"),
        ("p_mech_pu", "p_mech_measurement_pu"),
        ("p_ibr_pu", "p_ibr_measurement_pu"),
        ("u_sg_prev_pu", "u_sg_prev_measurement_pu"),
        ("u_ibr_prev_pu", "u_ibr_prev_measurement_pu"),
    ):
        maximum = max(
            maximum,
            _assert_close(
                getattr(measurement, attribute),
                row[column],
                f"endpoint {endpoint_index} {column}",
            ),
        )
    return maximum


def _verify_truth_point(
    point: Mapping[str, Any], row: Mapping[str, Any], endpoint_index: int
) -> float:
    if not row["truth_available"]:
        return 0.0
    maximum = 0.0
    for key in (
        "time_s",
        "omega_true_pu",
        "rocof_true_hz_per_s",
        "p_mech_true_pu",
        "p_ibr_true_pu",
        "load_disturbance_pu",
    ):
        maximum = max(
            maximum,
            _assert_close(
                point.get(key), row[key], f"endpoint {endpoint_index} {key}"
            ),
        )
    if point.get("true_mode_eval_only") != row["true_mode_eval_only"]:
        raise RunIntegrityError(
            f"canonical journal replay endpoint {endpoint_index} truth mode mismatch"
        )
    return maximum


def _copy_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RunIntegrityError(f"{name} must be a mapping")
    return MappingProxyType(dict(value))


def _deduplicate_truth(
    points: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    result: list[Mapping[str, Any]] = []
    for point in points:
        current = _copy_mapping(point, "replayed truth point")
        time_s = _finite(current.get("time_s"), "replayed truth time_s")
        if result:
            previous_time = float(result[-1]["time_s"])
            if time_s < previous_time - _FLOAT_TOLERANCE:
                raise RunIntegrityError("replayed truth points are not ordered")
            # Preserve a strictly later point even when it lies within the
            # comparison tolerance.  Such pairs occur when floating-point
            # integration stops a few ulps before an exact right-continuous
            # event boundary.  Equal or microscopically regressed timestamps
            # are the only duplicate records.
            if time_s <= previous_time:
                previous = result[-1]
                if set(previous) != set(current):
                    raise RunIntegrityError("duplicate replay truth schemas differ")
                for key in previous:
                    left, right = previous[key], current[key]
                    if isinstance(left, (int, float)) and not isinstance(left, bool):
                        _assert_close(right, left, f"duplicate truth {key}")
                    elif left != right:
                        raise RunIntegrityError(
                            f"duplicate replay truth value {key!r} differs"
                        )
                continue
        result.append(current)
    return tuple(result)


def _mode_belief(record: Mapping[str, Any]) -> list[float] | None:
    if "mode_belief" in record:
        raw = record["mode_belief"]
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            return [float(value) for value in raw]
    indexed: list[tuple[int, float]] = []
    for key, value in record.items():
        if key.startswith("belief_") and key.removeprefix("belief_").isdigit():
            indexed.append((int(key.removeprefix("belief_")), float(value)))
    if not indexed:
        return None
    indexed.sort()
    return [value for _, value in indexed]


def _journal_control_trajectory(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    trajectory: list[Mapping[str, Any]] = []
    records: list[Mapping[str, Any]] = []
    previous_record: Mapping[str, Any] = MappingProxyType({})
    for row in rows:
        raw_record = row.get("controller_record_json")
        if raw_record is not None:
            record = _record_json_value(raw_record, "controller_record_json")
            records.append(record)
            previous_record = record
        else:
            record = previous_record
        terminal = bool(row["terminal_endpoint"])
        trajectory.append(
            MappingProxyType(
                {
                    "time_s": row["time_s"],
                    "omega_measurement_pu": row["omega_measurement_pu"],
                    "p_mech_measurement_pu": row["p_mech_measurement_pu"],
                    "p_ibr_true_pu": row["p_ibr_true_pu"],
                    "u_sg_pu": (
                        row["u_sg_prev_measurement_pu"]
                        if terminal
                        else row["u_sg_pu"]
                    ),
                    "u_ibr_pu": (
                        row["u_ibr_prev_measurement_pu"]
                        if terminal
                        else row["u_ibr_pu"]
                    ),
                    "controller_state": (
                        str(previous_record.get("controller_state", "UNSPECIFIED"))
                        if terminal
                        else row["controller_state"]
                    ),
                    "solver_status": "not_run" if terminal else row["solver_status"],
                    "solver_outcome": "not_run" if terminal else row["solver_outcome"],
                    "solve_time_s": 0.0 if terminal else row["solve_time_s"],
                    "max_freq_slack_hz": (
                        0.0 if terminal else row["max_freq_slack_hz"]
                    ),
                    "max_rocof_slack_hz_s": (
                        0.0 if terminal else row["max_rocof_slack_hz_s"]
                    ),
                    "max_power_slack_pu": (
                        0.0 if terminal else row["max_power_slack_pu"]
                    ),
                    "diagnostic_state": str(
                        previous_record.get("diagnostic_state", "UNSPECIFIED")
                        if terminal
                        else row["diagnostic_state"]
                    ),
                    "mode_belief": _mode_belief(record),
                    "map_mode": record.get("map_mode"),
                    "belief_entropy": record.get("belief_entropy"),
                    "ood_pvalue": record.get("ood_pvalue"),
                    "terminal_endpoint": terminal,
                }
            )
        )
    return tuple(trajectory), tuple(records)


def replay_simulator_from_canonical_journal(
    *,
    identity: RunIdentity,
    scenario: object,
    simulator: object,
    journal: CanonicalDecisionJournal,
) -> CanonicalJournalReplay:
    """Replay only completed canonical actions and audit every endpoint.

    The signature intentionally has no controller, optimizer, or solver
    argument.  A returned action whose canonical simulator step failed is kept
    in the journal for audit but is not re-applied, because its partial side
    effects cannot be reconstructed safely.
    """

    if not isinstance(identity, RunIdentity):
        raise TypeError("identity must be a RunIdentity")
    if not isinstance(journal, CanonicalDecisionJournal):
        raise TypeError("journal must be a CanonicalDecisionJournal")
    if journal.identity != identity:
        raise RunIntegrityError("journal identity differs from replay identity")
    rows = journal.rows
    if not rows:
        raise RunIntegrityError("canonical journal contains no simulator endpoint")
    initial = getattr(simulator, "reset")(identity.seed, scenario)
    max_measurement_difference = _verify_measurement(initial, rows[0], 0)
    max_truth_difference = 0.0
    measurements = [initial]
    actions: list[ControlAction] = []
    evaluations: list[Mapping[str, Any]] = []
    raw_truth: list[Mapping[str, Any]] = []
    intervals: list[Mapping[str, Any]] = []
    verified_truth_indices: set[int] = set()

    for index, row in enumerate(rows):
        if not row["step_completed"]:
            break
        action = ControlAction(
            u_sg_pu=float(row["u_sg_pu"]),
            u_ibr_pu=float(row["u_ibr_pu"]),
            controller_state=str(row["controller_state"]),
            solver_status=str(row["solver_status"]),
            solve_time_s=float(row["solve_time_s"]),
            max_freq_slack_hz=float(row["max_freq_slack_hz"]),
        )
        next_measurement, raw_evaluation = getattr(simulator, "step")(action)
        evaluation = _copy_mapping(raw_evaluation, "simulator replay evaluation")
        raw_points = evaluation.get("true_trace_points_eval_only", ())
        raw_intervals = evaluation.get("true_trace_intervals_eval_only", ())
        if not isinstance(raw_points, Sequence) or isinstance(
            raw_points, (str, bytes, bytearray)
        ) or not raw_points:
            raise RunIntegrityError("simulator replay lacks truth points")
        if not isinstance(raw_intervals, Sequence) or isinstance(
            raw_intervals, (str, bytes, bytearray)
        ):
            raise RunIntegrityError("simulator replay truth intervals are malformed")
        copied_points = tuple(
            _copy_mapping(point, "simulator replay truth point")
            for point in raw_points
        )
        max_truth_difference = max(
            max_truth_difference,
            _verify_truth_point(copied_points[0], rows[index], index),
            _verify_truth_point(copied_points[-1], rows[index + 1], index + 1),
        )
        verified_truth_indices.update((index, index + 1))
        max_measurement_difference = max(
            max_measurement_difference,
            _verify_measurement(next_measurement, rows[index + 1], index + 1),
        )
        actions.append(action)
        measurements.append(next_measurement)
        evaluations.append(evaluation)
        raw_truth.extend(copied_points)
        intervals.extend(
            _copy_mapping(interval, "simulator replay truth interval")
            for interval in raw_intervals
        )

    if journal.metadata["run_completed"]:
        if len(actions) != journal.metadata["completed_step_count"]:
            raise RunIntegrityError("completed canonical replay stopped early")
        if not bool(evaluations[-1].get("done")):
            raise RunIntegrityError("completed canonical replay lacks done=true")
    high_frequency_truth = _deduplicate_truth(raw_truth)
    control_trajectory, controller_records = _journal_control_trajectory(rows)
    audit = {
        "schema_version": "d5freq.canonical_journal_replay_audit.v1",
        "trace_source": "canonical_action_journal_forced_simulator_replay",
        "controller_or_solver_invoked": False,
        "journal_sha256": journal.metadata["sha256"],
        "journal_row_count": journal.metadata["row_count"],
        "measurement_endpoint_count_verified": len(measurements),
        "truth_endpoint_count_verified": len(verified_truth_indices),
        "completed_action_count_replayed": len(actions),
        "returned_but_uncompleted_action_count": (
            journal.metadata["action_returned_count"]
            - journal.metadata["completed_step_count"]
        ),
        "high_frequency_truth_point_count": len(high_frequency_truth),
        "truth_interval_count": len(intervals),
        "comparison_abs_tolerance": _FLOAT_TOLERANCE,
        "max_abs_measurement_difference": max_measurement_difference,
        "max_abs_truth_difference": max_truth_difference,
    }
    return CanonicalJournalReplay(
        identity=identity,
        measurements=tuple(measurements),
        actions=tuple(actions),
        control_trajectory=control_trajectory,
        high_frequency_truth=high_frequency_truth,
        truth_intervals=tuple(intervals),
        controller_records=controller_records,
        simulator_evaluations=tuple(evaluations),
        consistency_audit=MappingProxyType(audit),
    )


__all__ = [
    "CANONICAL_DECISION_JOURNAL_COMPRESSION",
    "CANONICAL_DECISION_JOURNAL_PAYLOAD_KEY",
    "CANONICAL_DECISION_JOURNAL_SCHEMA_SHA256",
    "CANONICAL_DECISION_JOURNAL_SCHEMA_VERSION",
    "CanonicalDecisionJournal",
    "CanonicalJournalReplay",
    "build_canonical_decision_rows",
    "load_and_verify_canonical_decision_journal",
    "make_canonical_decision_journal_writer",
    "replay_simulator_from_canonical_journal",
    "write_canonical_decision_journal",
]
