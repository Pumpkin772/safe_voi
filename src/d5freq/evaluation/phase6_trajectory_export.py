"""Deterministic selection, replay, and export of final Phase-6 trajectories.

The final experiment store intentionally retains scalar episode results rather
than every high-rate trace.  This module selects a small, preregistered audit
subset from the immutable final CSVs, reruns exactly those frozen FINAL specs,
checks deterministic scientific fields against the canonical rows, and emits
only ZSTD Parquet evidence plus authenticated manifests for Phase 7.

Simulator truth remains evaluator-owned.  Normal controllers receive only the
usual ``Measurement`` API; B4 alone uses the existing Oracle evaluation bridge.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Literal

import numpy as np
import pandas as pd

from d5freq.evaluation.experiment_store import (
    PerRunExperimentStore,
    RunIdentity,
    StoredRun,
    strict_json_value,
)
from d5freq.evaluation.results_schema import (
    EPISODE_RESULT_COLUMNS,
    EpisodeResult,
)
from d5freq.utils.hashing import sha256_file, sha256_json


SELECTED_TRAJECTORY_MANIFEST_SCHEMA_VERSION = (
    "d5freq.selected_trajectory_manifest.v1"
)
TRAJECTORY_EXPORT_AUDIT_SCHEMA_VERSION = "d5freq.trajectory-export-audit.v1"
KNOWN_REPRESENTATIVE_SCENARIO = "S2_sluggish_switch_060"
OOD_REPRESENTATIVE_SCENARIO = "S7_ood_asymmetric_limit"
KNOWN_REPRESENTATIVE_METHODS: tuple[str, ...] = (
    "B0",
    "B1",
    "B2",
    "B3",
    "B4",
    "P",
)
OOD_REPRESENTATIVE_METHODS: tuple[str, ...] = ("B1", "B3", "P", "no-OOD")
REQUIRED_TRACE_FILES: tuple[str, ...] = (
    "control_trajectory",
    "high_frequency_truth",
    "truth_intervals",
    "controller_records",
)
NONDETERMINISTIC_EPISODE_FIELDS: frozenset[str] = frozenset(
    {
        "solve_time_mean_s",
        "solve_time_p95_s",
        "solve_time_max_s",
        "wall_time_s",
        # Oracle regret is attached only after the cross-method Phase-6
        # analysis, not by a standalone episode replay.
        "oracle_regret",
    }
)
DEFAULT_FLOAT_ABSOLUTE_TOLERANCE = 1e-9
DEFAULT_FLOAT_RELATIVE_TOLERANCE = 1e-9
CANONICAL_JOURNAL_TRACE_SOURCE = (
    "canonical_action_journal_forced_simulator_replay"
)

SelectionRole = Literal[
    "representative_known", "representative_ood", "worst_failure"
]


class TrajectoryExportError(RuntimeError):
    """Raised when selected-run evidence cannot be published honestly."""


@dataclass(frozen=True, slots=True)
class SelectedRun:
    run_id: str
    scenario_id: str
    method: str
    seed: int
    selection_role: SelectionRole
    selection_rank: int
    selection_basis: str

    @property
    def identity(self) -> RunIdentity:
        return RunIdentity(
            run_id=self.run_id,
            scenario_id=self.scenario_id,
            method=self.method,
            seed=self.seed,
        )


@dataclass(frozen=True, slots=True)
class CanonicalRunEvidence:
    stored_run: StoredRun
    metrics: Mapping[str, Any]
    ledger: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ReplayCapture:
    stored_run: StoredRun
    episode_result: EpisodeResult
    control_trajectory: tuple[Mapping[str, Any], ...]
    high_frequency_truth: tuple[Mapping[str, Any], ...]
    truth_intervals: tuple[Mapping[str, Any], ...]
    controller_records: tuple[Mapping[str, Any], ...]
    trace_source: str = "dependency_injected_replay_provider"
    trace_source_audit: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TrajectoryExportResult:
    representative_manifest: Path
    worst_manifest: Path
    representative_count: int
    worst_count: int


ReplayProvider = Callable[[SelectedRun, Path], ReplayCapture]
CanonicalProvider = Callable[[SelectedRun], CanonicalRunEvidence]


def _required_columns(frame: pd.DataFrame, names: Sequence[str], label: str) -> None:
    missing = [name for name in names if name not in frame.columns]
    if missing:
        raise TrajectoryExportError(f"{label} lacks columns: {missing}")


def _strict_bool(value: object, name: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise TrajectoryExportError(f"{name} must be boolean")


def _finite_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    return normalized if math.isfinite(normalized) else None


def _median_anchor_seed(frame: pd.DataFrame, scenario_id: str) -> tuple[int, float]:
    candidates = frame.loc[
        (frame["scenario_id"] == scenario_id) & (frame["method"] == "P"),
        ["run_id", "seed", "freq_iae"],
    ].copy()
    candidates["freq_iae_numeric"] = pd.to_numeric(
        candidates["freq_iae"], errors="coerce"
    )
    candidates = candidates.loc[
        np.isfinite(candidates["freq_iae_numeric"].to_numpy(dtype=float))
    ]
    if candidates.empty:
        raise TrajectoryExportError(
            f"no finite P freq_iae rows for representative scenario {scenario_id}"
        )
    median = float(np.median(candidates["freq_iae_numeric"].to_numpy(dtype=float)))
    candidates["distance"] = np.abs(candidates["freq_iae_numeric"] - median)
    candidates = candidates.sort_values(
        ["distance", "seed", "run_id"], kind="mergesort"
    )
    return int(candidates.iloc[0]["seed"]), median


def _row_for_identity(
    frame: pd.DataFrame, *, scenario_id: str, method: str, seed: int
) -> Mapping[str, Any]:
    rows = frame.loc[
        (frame["scenario_id"] == scenario_id)
        & (frame["method"] == method)
        & (pd.to_numeric(frame["seed"], errors="coerce") == seed)
    ]
    if len(rows) != 1:
        raise TrajectoryExportError(
            "selected identity must have exactly one canonical row: "
            f"scenario={scenario_id}, method={method}, seed={seed}; found={len(rows)}"
        )
    return rows.iloc[0].to_dict()


def select_representative_runs(frame: pd.DataFrame) -> tuple[SelectedRun, ...]:
    """Select the two frozen median-P seeds and their required comparisons."""

    _required_columns(
        frame,
        ("run_id", "scenario_id", "method", "seed", "freq_iae"),
        "per_episode_metrics",
    )
    groups = (
        (
            KNOWN_REPRESENTATIVE_SCENARIO,
            KNOWN_REPRESENTATIVE_METHODS,
            "representative_known",
        ),
        (
            OOD_REPRESENTATIVE_SCENARIO,
            OOD_REPRESENTATIVE_METHODS,
            "representative_ood",
        ),
    )
    selected: list[SelectedRun] = []
    rank = 1
    for scenario_id, methods, role in groups:
        seed, median = _median_anchor_seed(frame, scenario_id)
        anchor = _row_for_identity(
            frame, scenario_id=scenario_id, method="P", seed=seed
        )
        anchor_value = float(anchor["freq_iae"])
        basis = (
            f"P seed minimizing |freq_iae - scenario P median|; "
            f"median={median:.17g}, selected_P_freq_iae={anchor_value:.17g}, "
            "ties resolved by seed then run_id; comparison methods reuse that seed"
        )
        for method in methods:
            row = _row_for_identity(
                frame, scenario_id=scenario_id, method=method, seed=seed
            )
            selected.append(
                SelectedRun(
                    run_id=str(row["run_id"]),
                    scenario_id=scenario_id,
                    method=method,
                    seed=seed,
                    selection_role=role,  # type: ignore[arg-type]
                    selection_rank=rank,
                    selection_basis=basis,
                )
            )
            rank += 1
    return tuple(selected)


def select_worst_runs(
    frame: pd.DataFrame, *, maximum_count: int = 3
) -> tuple[SelectedRun, ...]:
    """Rank retained failures first, without treating missing metrics as zero.

    ``worst_failure_cases`` must not silently prefer a scientifically successful
    large excursion over a failed episode.  Failure status is therefore the
    primary key; physical severity only orders rows within the same status.
    When the final matrix contains no failure, the returned rows are explicitly
    described as worst observed non-failure cases in ``selection_basis``.
    """

    if isinstance(maximum_count, bool) or not isinstance(maximum_count, int):
        raise TypeError("maximum_count must be an integer")
    if maximum_count <= 0:
        raise ValueError("maximum_count must be positive")
    _required_columns(
        frame,
        (
            "run_id",
            "scenario_id",
            "method",
            "seed",
            "run_completed",
            "metrics_complete",
            "scientific_success",
            "failure_type",
            "catastrophic_failure",
            "max_abs_freq_hz",
            "freq_iae",
        ),
        "per_episode_metrics",
    )
    ranked = frame.copy()
    ranked["_run_incomplete"] = [
        int(not _strict_bool(value, "run_completed"))
        for value in ranked["run_completed"].tolist()
    ]
    ranked["_metrics_incomplete"] = [
        int(not _strict_bool(value, "metrics_complete"))
        for value in ranked["metrics_complete"].tolist()
    ]
    ranked["_scientific_failure"] = [
        int(not _strict_bool(value, "scientific_success"))
        for value in ranked["scientific_success"].tolist()
    ]
    ranked["_declared_failure"] = [
        int(value is not None and not pd.isna(value) and bool(str(value).strip()))
        for value in ranked["failure_type"].tolist()
    ]
    ranked["_catastrophic"] = [
        int(_strict_bool(value, "catastrophic_failure"))
        for value in ranked["catastrophic_failure"].tolist()
    ]
    ranked["_is_failure"] = (
        ranked[
            [
                "_run_incomplete",
                "_metrics_incomplete",
                "_scientific_failure",
                "_declared_failure",
                "_catastrophic",
            ]
        ]
        .max(axis=1)
        .astype(int)
    )
    ranked["_max_abs_freq"] = pd.to_numeric(
        ranked["max_abs_freq_hz"], errors="coerce"
    )
    ranked["_freq_iae"] = pd.to_numeric(ranked["freq_iae"], errors="coerce")
    ranked["_max_missing"] = ranked["_max_abs_freq"].isna().astype(int)
    ranked["_iae_missing"] = ranked["_freq_iae"].isna().astype(int)
    ranked = ranked.sort_values(
        [
            "_is_failure",
            "_catastrophic",
            "_run_incomplete",
            "_metrics_incomplete",
            "_scientific_failure",
            "_max_missing",
            "_max_abs_freq",
            "_iae_missing",
            "_freq_iae",
            "scenario_id",
            "method",
            "seed",
            "run_id",
        ],
        ascending=[
            False,
            False,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            True,
            True,
            True,
            True,
        ],
        kind="mergesort",
    )
    selected: list[SelectedRun] = []
    for rank, (_, row) in enumerate(ranked.head(maximum_count).iterrows(), start=1):
        max_freq = _finite_or_none(row["max_abs_freq_hz"])
        iae = _finite_or_none(row["freq_iae"])
        selected.append(
            SelectedRun(
                run_id=str(row["run_id"]),
                scenario_id=str(row["scenario_id"]),
                method=str(row["method"]),
                seed=int(row["seed"]),
                selection_role="worst_failure",
                selection_rank=rank,
                selection_basis=(
                    "stable descending rank: retained failure status, "
                    "catastrophic_failure, incomplete run/metrics, scientific "
                    "failure, observed max_abs_freq_hz, observed freq_iae; missing "
                    "continuous metrics sort after observed values within the same "
                    "failure class; "
                    f"selected values is_failure={bool(row['_is_failure'])}, "
                    f"catastrophic={bool(row['_catastrophic'])}, "
                    f"failure_type={_none_if_missing(row['failure_type'])!r}, "
                    f"max_abs_freq_hz={max_freq}, freq_iae={iae}"
                ),
            )
        )
    return tuple(selected)


def _none_if_missing(value: object) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, np.generic):
        value = value.item()
    return value


def episode_result_mapping(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact canonical EpisodeResult field set in schema order."""

    missing = [name for name in EPISODE_RESULT_COLUMNS if name not in row]
    if missing:
        raise TrajectoryExportError(
            f"canonical metrics row lacks EpisodeResult fields: {missing}"
        )
    payload = {
        name: _none_if_missing(row[name]) for name in EPISODE_RESULT_COLUMNS
    }
    # Reconstruction proves types/derived success flags are still valid after
    # the CSV round trip, and gives canonical primitive values.
    result = EpisodeResult(**payload)
    return result.to_json_dict()


def episode_result_sha256(row: Mapping[str, Any]) -> str:
    return sha256_json(episode_result_mapping(row))


def compare_episode_results(
    canonical: Mapping[str, Any],
    replay: Mapping[str, Any],
    *,
    absolute_tolerance: float = DEFAULT_FLOAT_ABSOLUTE_TOLERANCE,
    relative_tolerance: float = DEFAULT_FLOAT_RELATIVE_TOLERANCE,
) -> dict[str, Any]:
    """Compare every scientific field and explicitly list timing exclusions."""

    if absolute_tolerance < 0.0 or relative_tolerance < 0.0:
        raise ValueError("comparison tolerances must be non-negative")
    left = episode_result_mapping(canonical)
    right = episode_result_mapping(replay)
    compared: list[str] = []
    mismatches: list[dict[str, Any]] = []
    for field in EPISODE_RESULT_COLUMNS:
        if field in NONDETERMINISTIC_EPISODE_FIELDS:
            continue
        compared.append(field)
        first = left[field]
        second = right[field]
        if isinstance(first, float) and isinstance(second, float):
            equal = math.isclose(
                first,
                second,
                rel_tol=relative_tolerance,
                abs_tol=absolute_tolerance,
            )
        else:
            equal = first == second
        if not equal:
            mismatches.append(
                {"field": field, "canonical": first, "replay": second}
            )
    return {
        "status": "verified" if not mismatches else "mismatch",
        "compared_fields": compared,
        "excluded_nondeterministic_fields": sorted(
            NONDETERMINISTIC_EPISODE_FIELDS
        ),
        "tolerances": {
            "float_absolute": absolute_tolerance,
            "float_relative": relative_tolerance,
        },
        "mismatches": mismatches,
    }


def _normalized_cell(value: Any) -> Any:
    converted = strict_json_value(value)
    if converted is None or isinstance(converted, (str, bool, int, float)):
        return converted
    return json.dumps(
        converted,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def records_frame(records: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Normalize nested values to stable compact JSON before Parquet export."""

    if not records:
        return pd.DataFrame({"record_index": pd.Series(dtype="int64")})
    key_order = sorted({key for row in records for key in row})
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(records):
        if not isinstance(raw, Mapping) or not all(
            isinstance(key, str) for key in raw
        ):
            raise TrajectoryExportError("trace records must be string-keyed objects")
        normalized = {"record_index": index}
        normalized.update(
            {key: _normalized_cell(raw.get(key)) for key in key_order}
        )
        rows.append(normalized)
    return pd.DataFrame.from_records(
        rows, columns=("record_index", *key_order)
    )


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        strict_json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".j_", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_zstd_parquet(path: Path, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = records_frame(records)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".p_", suffix=".tmp", dir=str(path.parent)
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(
            temporary,
            index=False,
            engine="pyarrow",
            compression="zstd",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "relative_path": path.name,
        "sha256": sha256_file(path),
        "row_count": len(frame),
        "compression": "zstd",
    }


def _records_with_selection_identity(
    records: Sequence[Mapping[str, Any]], selection: SelectedRun
) -> tuple[Mapping[str, Any], ...]:
    """Attach evaluator-owned identity to exported evidence tables.

    These fields are added only after the episode has completed.  They are not
    visible to any controller and let downstream figures consume the strict
    trajectory manifest instead of guessing identity from directory order.
    """

    identity = {
        "run_id": selection.run_id,
        "scenario_id": selection.scenario_id,
        "method": selection.method,
        "seed": selection.seed,
        "selection_role": selection.selection_role,
    }
    enriched: list[Mapping[str, Any]] = []
    for ordinal, raw in enumerate(records):
        if not isinstance(raw, Mapping):
            raise TrajectoryExportError(
                f"trace record {ordinal} is not a mapping for {selection.run_id}"
            )
        row = dict(raw)
        for key, value in identity.items():
            if key in row and _none_if_missing(row[key]) != value:
                raise TrajectoryExportError(
                    f"trace record {ordinal} has conflicting {key!r} identity"
                )
            row[key] = value
        enriched.append(row)
    return tuple(enriched)


def _safe_entry_directory(selection: SelectedRun) -> str:
    digest = sha256_json(
        {
            "run_id": selection.run_id,
            "role": selection.selection_role,
            "rank": selection.selection_rank,
        }
    )[:16]
    return f"entry_{selection.selection_rank:03d}_{digest}"


def _copy_replay_envelope(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _canonical_result_records(
    *, results_dir: Path, manifest_root: Path
) -> dict[str, dict[str, Any]]:
    names = {
        "metrics": "per_episode_metrics.csv",
        "ledger": "experiment_ledger.csv",
        "protocol_lock": "protocol_lock.json",
    }
    return {
        key: {
            "relative_path": Path(
                os.path.relpath(results_dir / filename, manifest_root)
            ).as_posix(),
            "sha256": sha256_file(results_dir / filename),
        }
        for key, filename in names.items()
    }


def _entry_payload(
    *,
    selection: SelectedRun,
    canonical: CanonicalRunEvidence,
    replay: ReplayCapture,
    entry_root: Path,
) -> dict[str, Any]:
    ledger_envelope = str(canonical.ledger.get("per_run_envelope_sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", ledger_envelope):
        raise TrajectoryExportError(
            f"ledger envelope digest is malformed for {selection.run_id}"
        )
    if ledger_envelope != canonical.stored_run.sha256:
        raise TrajectoryExportError(
            f"canonical_envelope_sha256 disagrees with ledger for {selection.run_id}"
        )
    canonical_store_consistency = compare_episode_results(
        canonical.metrics,
        canonical.stored_run.episode_result.to_json_dict(),
    )
    if canonical_store_consistency["mismatches"]:
        raise TrajectoryExportError(
            "canonical final CSV differs from its authenticated per-run episode "
            f"result for {selection.run_id}: "
            f"{canonical_store_consistency['mismatches']}"
        )
    consistency = compare_episode_results(
        canonical.metrics,
        replay.episode_result.to_json_dict(),
    )
    if consistency["mismatches"]:
        raise TrajectoryExportError(
            f"selected replay differs from canonical scientific fields for "
            f"{selection.run_id}: {consistency['mismatches']}"
        )
    if not isinstance(replay.trace_source, str) or not replay.trace_source.strip():
        raise TrajectoryExportError("ReplayCapture.trace_source must be non-empty")
    source_audit = strict_json_value(replay.trace_source_audit)
    if not isinstance(source_audit, Mapping):
        raise TrajectoryExportError("ReplayCapture.trace_source_audit must be an object")
    if replay.trace_source == CANONICAL_JOURNAL_TRACE_SOURCE:
        required_audits = {
            "canonical_journal",
            "endpoint_consistency_audit",
            "scientific_recomputation_audit",
        }
        if set(source_audit) != required_audits:
            raise TrajectoryExportError(
                "canonical journal ReplayCapture lacks its complete source audit"
            )
        replay_payload = replay.stored_run.run_payload
        if replay_payload.get("trace_source") != replay.trace_source or any(
            replay_payload.get(name) != source_audit[name]
            for name in required_audits
        ):
            raise TrajectoryExportError(
                "canonical journal ReplayCapture source audit differs from its envelope"
            )
        endpoint = source_audit["endpoint_consistency_audit"]
        scientific = source_audit["scientific_recomputation_audit"]
        journal = source_audit["canonical_journal"]
        if not all(
            isinstance(value, Mapping)
            for value in (endpoint, scientific, journal)
        ):
            raise TrajectoryExportError(
                "canonical journal ReplayCapture audit sections must be objects"
            )
        if endpoint.get("controller_or_solver_invoked") is not False:
            raise TrajectoryExportError(
                "canonical journal replay reports controller/solver invocation"
            )
        if endpoint.get("trace_source") != replay.trace_source:
            raise TrajectoryExportError("canonical journal endpoint trace_source mismatch")
        if scientific.get("status") != "verified" or scientific.get("mismatches"):
            raise TrajectoryExportError(
                "canonical journal scientific recomputation was not verified"
            )
    entry_root.mkdir(parents=True, exist_ok=False)
    replay_envelope = entry_root / "replay_envelope.json"
    _copy_replay_envelope(replay.stored_run.path, replay_envelope)
    if replay.stored_run.sha256 != json.loads(
        replay_envelope.read_text(encoding="utf-8")
    ).get("sha256"):
        raise TrajectoryExportError("copied replay envelope internal digest mismatch")

    high_frequency_records = replay.high_frequency_truth
    interval_records = replay.truth_intervals
    truth_source = replay.trace_source
    if not bool(canonical.stored_run.episode_result.run_completed):
        canonical_truth = canonical.stored_run.run_payload.get(
            "truth_trace_points_eval_only"
        )
        canonical_intervals = canonical.stored_run.run_payload.get(
            "truth_trace_intervals_eval_only"
        )
        if not isinstance(canonical_truth, Sequence) or isinstance(
            canonical_truth, (str, bytes, bytearray)
        ):
            raise TrajectoryExportError(
                "canonical incomplete failure lacks its required saved truth prefix"
            )
        if not isinstance(canonical_intervals, Sequence) or isinstance(
            canonical_intervals, (str, bytes, bytearray)
        ):
            raise TrajectoryExportError(
                "canonical incomplete failure lacks its required interval prefix"
            )
        high_frequency_records = tuple(dict(row) for row in canonical_truth)
        interval_records = tuple(dict(row) for row in canonical_intervals)
        truth_source = "canonical_incomplete_failure_prefix"

    trace_records = {
        "control_trajectory": _records_with_selection_identity(
            replay.control_trajectory, selection
        ),
        "high_frequency_truth": _records_with_selection_identity(
            high_frequency_records, selection
        ),
        "truth_intervals": _records_with_selection_identity(
            interval_records, selection
        ),
        "controller_records": _records_with_selection_identity(
            replay.controller_records, selection
        ),
    }
    files: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_TRACE_FILES:
        file_record = _write_zstd_parquet(
            entry_root / f"{name}.parquet", trace_records[name]
        )
        file_record["relative_path"] = (
            Path(entry_root.name) / str(file_record["relative_path"])
        ).as_posix()
        file_record["source"] = (
            truth_source
            if name in {"high_frequency_truth", "truth_intervals"}
            else replay.trace_source
        )
        files[name] = file_record

    canonical_metrics = episode_result_mapping(canonical.metrics)
    canonical_episode_result = canonical.stored_run.episode_result.to_json_dict()
    replay_metrics = replay.episode_result.to_json_dict()
    return {
        "run_id": selection.run_id,
        "scenario_id": selection.scenario_id,
        "method": selection.method,
        "seed": selection.seed,
        "selection_role": selection.selection_role,
        "selection_rank": selection.selection_rank,
        "selection_basis": selection.selection_basis,
        "canonical_envelope_sha256": ledger_envelope,
        "canonical_episode_result_sha256": sha256_json(
            canonical_episode_result
        ),
        "canonical_episode_result": canonical_episode_result,
        "canonical_metrics": canonical_metrics,
        "canonical_store_consistency": canonical_store_consistency,
        "replay_envelope_relative_path": (
            Path(entry_root.name) / replay_envelope.name
        ).as_posix(),
        "replay_envelope_sha256": replay.stored_run.sha256,
        "replay_envelope_file_sha256": sha256_file(replay_envelope),
        "replay_episode_result_sha256": sha256_json(replay_metrics),
        "replay_consistency": consistency,
        "trace_source": replay.trace_source,
        "canonical_journal": source_audit.get("canonical_journal"),
        "endpoint_consistency_audit": source_audit.get(
            "endpoint_consistency_audit"
        ),
        "scientific_recomputation_audit": source_audit.get(
            "scientific_recomputation_audit"
        ),
        "canonical_incomplete_failure_truth_source": truth_source,
        "files": files,
    }


def _manifest_payload(
    *,
    manifest_root: Path,
    results_dir: Path,
    role: str,
    entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SELECTED_TRAJECTORY_MANIFEST_SCHEMA_VERSION,
        "hash_algorithm": "sha256",
        "episode_result_hash_serialization": (
            "d5freq.utils.hashing.canonical_json_bytes over the ordered "
            "EpisodeResult field mapping"
        ),
        "episode_result_hash_fields": list(EPISODE_RESULT_COLUMNS),
        "selection_policy": {
            "role": role,
            "representative_known": {
                "scenario_id": KNOWN_REPRESENTATIVE_SCENARIO,
                "anchor_method": "P",
                "metric": "freq_iae",
                "seed_rule": "minimum absolute distance to P median; seed/run_id tie-break",
                "comparison_methods": list(KNOWN_REPRESENTATIVE_METHODS),
            },
            "representative_ood": {
                "scenario_id": OOD_REPRESENTATIVE_SCENARIO,
                "anchor_method": "P",
                "metric": "freq_iae",
                "seed_rule": "minimum absolute distance to P median; seed/run_id tie-break",
                "comparison_methods": list(OOD_REPRESENTATIVE_METHODS),
            },
            "worst": {
                "maximum_count": 3,
                "rank": "catastrophic first, then descending observed max_abs_freq_hz and freq_iae, stable identity tie-break",
            },
        },
        "canonical_results": _canonical_result_records(
            results_dir=results_dir, manifest_root=manifest_root
        ),
        "entries": list(entries),
    }


def build_selected_outputs(
    *,
    results_dir: Path,
    metrics_frame: pd.DataFrame,
    ledger_frame: pd.DataFrame,
    representative: Sequence[SelectedRun],
    worst: Sequence[SelectedRun],
    canonical_provider: CanonicalProvider,
    replay_provider: ReplayProvider,
    staging_root: Path,
) -> tuple[Path, Path]:
    """Build both manifests below an unpublished staging root.

    This dependency-injected core is used by tests; production callers must
    perform the complete final-matrix/protocol-lock validation first.
    """

    results_dir = Path(results_dir).resolve()
    staging_root = Path(staging_root).resolve()
    if staging_root.exists():
        if any(staging_root.iterdir()):
            raise TrajectoryExportError("staging_root must be new or empty")
    else:
        staging_root.mkdir(parents=True)
    metrics_by_run = {str(row["run_id"]): row for row in metrics_frame.to_dict("records")}
    ledger_by_run = {str(row["run_id"]): row for row in ledger_frame.to_dict("records")}
    if set(metrics_by_run) != set(ledger_by_run):
        raise TrajectoryExportError("canonical metrics and ledger run_id sets differ")
    if not representative or not worst:
        raise TrajectoryExportError(
            "representative and worst selections must both be non-empty"
        )
    for name, group_rows in (
        ("representative", representative),
        ("worst", worst),
    ):
        run_ids = [row.run_id for row in group_rows]
        ranks = [row.selection_rank for row in group_rows]
        if len(set(run_ids)) != len(run_ids):
            raise TrajectoryExportError(f"{name} selection contains duplicate run_id")
        if len(set(ranks)) != len(ranks) or sorted(ranks) != list(
            range(1, len(ranks) + 1)
        ):
            raise TrajectoryExportError(
                f"{name} selection ranks must be unique contiguous integers from one"
            )

    replay_cache: dict[str, ReplayCapture] = {}
    canonical_cache: dict[str, CanonicalRunEvidence] = {}
    roots = {
        "representative": staging_root / "representative_trajectories",
        "worst": staging_root / "worst_failure_cases",
    }
    selections = {
        "representative": tuple(representative),
        "worst": tuple(worst),
    }
    manifests: dict[str, Path] = {}
    replay_work = staging_root / ".replay_work"
    replay_work.mkdir()
    final_manifest_roots = {
        "representative": results_dir / "representative_trajectories",
        "worst": results_dir / "worst_failure_cases",
    }
    for group in ("representative", "worst"):
        manifest_root = roots[group]
        manifest_root.mkdir()
        entry_payloads: list[Mapping[str, Any]] = []
        for selection in selections[group]:
            if selection.run_id not in metrics_by_run:
                raise TrajectoryExportError(
                    f"selected run absent from canonical CSVs: {selection.run_id}"
                )
            canonical = canonical_cache.get(selection.run_id)
            if canonical is None:
                canonical = canonical_provider(selection)
                canonical_cache[selection.run_id] = canonical
            replay = replay_cache.get(selection.run_id)
            if replay is None:
                replay_digest = sha256_json({"run_id": selection.run_id})[:16]
                replay = replay_provider(selection, replay_work / f"r_{replay_digest}")
                replay_cache[selection.run_id] = replay
            # Mappings may differ only in pandas scalar types; compare their
            # canonical EpisodeResult projections instead.
            if episode_result_mapping(canonical.metrics) != episode_result_mapping(
                metrics_by_run[selection.run_id]
            ):
                raise TrajectoryExportError("canonical provider metrics differ from CSV")
            if str(canonical.ledger.get("per_run_envelope_sha256", "")) != str(
                ledger_by_run[selection.run_id].get("per_run_envelope_sha256", "")
            ):
                raise TrajectoryExportError("canonical provider ledger differs from CSV")
            entry_payloads.append(
                _entry_payload(
                    selection=selection,
                    canonical=canonical,
                    replay=replay,
                    entry_root=manifest_root / _safe_entry_directory(selection),
                )
            )
        manifest = manifest_root / "trajectory_manifest.json"
        _atomic_write_json(
            manifest,
            _manifest_payload(
                manifest_root=final_manifest_roots[group],
                results_dir=results_dir,
                role=group,
                entries=entry_payloads,
            ),
        )
        manifests[group] = manifest
    shutil.rmtree(replay_work)
    return manifests["representative"], manifests["worst"]


def _load_protocol_lock(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrajectoryExportError(f"cannot read final protocol lock: {path}") from exc
    if not isinstance(payload, Mapping):
        raise TrajectoryExportError("final protocol lock must be an object")
    material = payload.get("material")
    if not isinstance(material, Mapping):
        raise TrajectoryExportError("final protocol lock lacks material")
    from d5freq.evaluation.phase6_experiments import protocol_material_sha256

    if payload.get("protocol_material_sha256") != protocol_material_sha256(material):
        raise TrajectoryExportError("final protocol-lock material hash mismatch")
    return payload


def _journal_returned_actions(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[object, ...]:
    """Rebuild every canonical returned action without applying it."""

    from d5freq.interfaces import ControlAction

    actions: list[ControlAction] = []
    for row in rows:
        if not bool(row.get("action_returned")):
            continue
        actions.append(
            ControlAction(
                u_sg_pu=float(row["u_sg_pu"]),
                u_ibr_pu=float(row["u_ibr_pu"]),
                controller_state=str(row["controller_state"]),
                solver_status=str(row["solver_status"]),
                solve_time_s=float(row["solve_time_s"]),
                max_freq_slack_hz=float(row["max_freq_slack_hz"]),
            )
        )
    return tuple(actions)


def build_canonical_journal_replay_capture(
    *,
    canonical_stored_run: StoredRun,
    scenario: object,
    simulator: object,
    metric_config: object,
    work_root: Path,
    evaluators: Sequence[Callable[[Any], Any]] = (),
    responsibility_event_time_s: float | None = None,
) -> ReplayCapture:
    """Build authenticated traces and metrics without a controller or solver.

    The simulator receives only the canonical actions recorded during the
    original episode.  A returned action whose canonical simulator step did
    not complete is reconstructed for prefix-metric parity but is never
    applied to the simulator.  Every applied endpoint is verified by the
    journal module before scientific metrics are recomputed.
    """

    from types import MappingProxyType

    from d5freq.evaluation.closed_loop_metrics import (
        ClosedLoopMetricConfig,
        ClosedLoopMetrics,
        HighFrequencyTruthTrace,
        compute_closed_loop_metrics,
    )
    from d5freq.evaluation.closed_loop_runner import (
        EpisodeEvaluationData,
        EvaluationContribution,
        _build_control_trace,
        _merge_contribution,
        settling_reference_time,
    )
    from d5freq.evaluation.phase6_canonical_journal import (
        load_and_verify_canonical_decision_journal,
        replay_simulator_from_canonical_journal,
    )

    if not isinstance(canonical_stored_run, StoredRun):
        raise TypeError("canonical_stored_run must be a StoredRun")
    if not isinstance(metric_config, ClosedLoopMetricConfig):
        raise TypeError("metric_config must be a ClosedLoopMetricConfig")
    journal = load_and_verify_canonical_decision_journal(canonical_stored_run)
    forced = replay_simulator_from_canonical_journal(
        identity=canonical_stored_run.identity,
        scenario=scenario,
        simulator=simulator,
        journal=journal,
    )
    run_completed = bool(journal.metadata["run_completed"])
    truth_points = tuple(forced.high_frequency_truth)
    high_frequency_truth = (
        None
        if len(truth_points) < 2
        else HighFrequencyTruthTrace.from_points(truth_points)
    )
    returned_actions = _journal_returned_actions(journal.rows)
    control_trace, metric_control_trajectory = _build_control_trace(
        forced.measurements,
        returned_actions,
        forced.controller_records,
        truth_points,
        responsibility_event_time_s=responsibility_event_time_s,
    )
    base_metrics: ClosedLoopMetrics | None = None
    if high_frequency_truth is not None and control_trace is not None:
        base_metrics = compute_closed_loop_metrics(
            high_frequency_truth,
            control_trace,
            metric_config,
            run_completed=run_completed,
            settling_reference_time_s=settling_reference_time(scenario),
        )
    canonical_result = canonical_stored_run.episode_result
    if canonical_result.metrics_complete and base_metrics is None:
        raise TrajectoryExportError(
            "canonical complete metrics cannot be recomputed from the journal"
        )
    data = EpisodeEvaluationData(
        identity=canonical_stored_run.identity,
        scenario=scenario,
        run_completed=run_completed,
        measurements=forced.measurements,
        actions=returned_actions,  # type: ignore[arg-type]
        simulator_evaluations=forced.simulator_evaluations,
        truth_points_eval_only=truth_points,
        truth_intervals_eval_only=forced.truth_intervals,
        controller_records=forced.controller_records,
        high_frequency_truth=high_frequency_truth,
        control_trace=control_trace,
        control_trajectory=metric_control_trajectory,
        base_metrics=base_metrics,
        failure_stage=canonical_result.failure_stage,
        failure_type=canonical_result.failure_type,
        failure_message=canonical_result.failure_message,
    )
    evaluator_metrics: dict[str, Any] = {}
    for evaluator in evaluators:
        contribution = evaluator(data)
        if not isinstance(contribution, EvaluationContribution):
            raise TrajectoryExportError(
                "canonical replay evaluator did not return EvaluationContribution"
            )
        _merge_contribution(evaluator_metrics, contribution)

    if base_metrics is None:
        replay_result = EpisodeResult(
            run_id=canonical_result.run_id,
            scenario_id=canonical_result.scenario_id,
            method=canonical_result.method,
            seed=canonical_result.seed,
            run_completed=run_completed,
            metrics_complete=False,
            failure_stage=canonical_result.failure_stage,
            failure_type=canonical_result.failure_type,
            failure_message=canonical_result.failure_message,
            catastrophic_safety_boundary=(
                canonical_result.catastrophic_safety_boundary
            ),
            catastrophic_solver_without_fallback=(
                canonical_result.catastrophic_solver_without_fallback
            ),
            catastrophic_nan_detected=canonical_result.catastrophic_nan_detected,
            catastrophic_persistent_command_violation=(
                canonical_result.catastrophic_persistent_command_violation
            ),
            catastrophic_not_recovered=canonical_result.catastrophic_not_recovered,
            wall_time_s=0.0,
        )
    else:
        metric_payload = base_metrics.to_dict()
        metric_payload.update(evaluator_metrics)
        if canonical_result.failure_type is not None:
            metric_payload["metrics_complete"] = False
        replay_result = EpisodeResult.from_metrics(
            run_id=canonical_result.run_id,
            scenario_id=canonical_result.scenario_id,
            method=canonical_result.method,
            seed=canonical_result.seed,
            metrics=metric_payload,
            run_completed=run_completed,
            failure_stage=canonical_result.failure_stage,
            failure_type=canonical_result.failure_type,
            failure_message=canonical_result.failure_message,
            wall_time_s=0.0,
        )

    scientific = compare_episode_results(
        canonical_result.to_json_dict(), replay_result.to_json_dict()
    )
    if scientific["mismatches"]:
        raise TrajectoryExportError(
            "canonical journal scientific recomputation differs from its "
            f"authenticated EpisodeResult: {scientific['mismatches']}"
        )
    journal_binding = {
        key: journal.metadata[key]
        for key in (
            "schema_version",
            "schema_sha256",
            "relative_path",
            "sha256",
            "size_bytes",
            "row_count",
            "compression",
            "stage",
            "run_completed",
            "metrics_complete",
            "simulation_entered",
            "action_returned_count",
            "completed_step_count",
        )
    }
    source_audit = {
        "canonical_journal": journal_binding,
        "endpoint_consistency_audit": dict(forced.consistency_audit),
        "scientific_recomputation_audit": scientific,
    }
    normalized_audit = strict_json_value(source_audit)
    assert isinstance(normalized_audit, Mapping)
    replay_payload = {
        "trace_source": CANONICAL_JOURNAL_TRACE_SOURCE,
        **dict(normalized_audit),
    }
    replay_store = PerRunExperimentStore(Path(work_root) / "store")
    replay_stored = replay_store.save(
        canonical_stored_run.identity,
        replay_result,
        replay_payload,
    )
    return ReplayCapture(
        stored_run=replay_stored,
        episode_result=replay_result,
        control_trajectory=forced.control_trajectory,
        high_frequency_truth=forced.high_frequency_truth,
        truth_intervals=forced.truth_intervals,
        controller_records=forced.controller_records,
        trace_source=CANONICAL_JOURNAL_TRACE_SOURCE,
        trace_source_audit=MappingProxyType(dict(normalized_audit)),
    )


def _grid_model_for_forced_replay(base_config_path: Path) -> object:
    """Construct only the public grid model; no controller factory is loaded."""

    from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
    from d5freq.utils.config import load_yaml

    base = load_yaml(base_config_path)
    values = base.get("grid")
    if base.get("schema_version") != 1 or not isinstance(values, Mapping):
        raise TrajectoryExportError("base config lacks the frozen grid section")
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


def _production_replay_provider(
    spec_by_run: Mapping[str, object],
    canonical_by_run: Mapping[str, CanonicalRunEvidence],
) -> ReplayProvider:
    def replay(selection: SelectedRun, work_root: Path) -> ReplayCapture:
        from d5freq.evaluation.phase6_experiments import (
            _diagnostic_evaluator,
            build_metric_config,
            load_frozen_phase6_protocol,
            load_simulator_private_modes_eval_only,
            responsibility_event_time_eval_only,
        )
        from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator

        spec = spec_by_run[selection.run_id]
        paths = getattr(spec, "paths")
        identity = getattr(spec, "identity")
        protocol = load_frozen_phase6_protocol(paths.experiments_config)
        scenario = protocol.build_scenario(identity.scenario_id)
        simulator = HiddenModeFrequencySimulator(
            _grid_model_for_forced_replay(paths.base_config),
            load_simulator_private_modes_eval_only(paths),
        )
        canonical = canonical_by_run.get(selection.run_id)
        if canonical is None:
            raise TrajectoryExportError(
                "production replay was requested before canonical evidence "
                f"was authenticated: {selection.run_id}"
            )
        return build_canonical_journal_replay_capture(
            canonical_stored_run=canonical.stored_run,
            scenario=scenario,
            simulator=simulator,
            metric_config=build_metric_config(paths.base_config),
            work_root=work_root,
            evaluators=(_diagnostic_evaluator(spec),),
            responsibility_event_time_s=responsibility_event_time_eval_only(
                scenario
            ),
        )

    return replay


def _verify_ledger_journal_binding(
    ledger_row: Mapping[str, Any], journal_metadata: Mapping[str, Any]
) -> None:
    bindings = {
        "canonical_decision_journal_schema_version": "schema_version",
        "canonical_decision_journal_schema_sha256": "schema_sha256",
        "canonical_decision_journal_relative_path": "relative_path",
        "canonical_decision_journal_sha256": "sha256",
        "canonical_decision_journal_row_count": "row_count",
        "canonical_decision_journal_compression": "compression",
    }
    for ledger_name, metadata_name in bindings.items():
        if ledger_name not in ledger_row:
            raise TrajectoryExportError(
                f"final ledger lacks canonical journal binding {ledger_name}"
            )
        observed = _none_if_missing(ledger_row[ledger_name])
        expected = journal_metadata[metadata_name]
        if metadata_name == "row_count":
            try:
                observed = int(observed)
            except (TypeError, ValueError) as exc:
                raise TrajectoryExportError(
                    "final ledger canonical journal row_count is malformed"
                ) from exc
        if observed != expected:
            raise TrajectoryExportError(
                f"final ledger {ledger_name} differs from authenticated journal"
            )


def _publish_two_directories(
    *,
    representative_staged: Path,
    worst_staged: Path,
    results_dir: Path,
    replace: bool,
) -> tuple[Path, Path]:
    targets = (
        (representative_staged, results_dir / "representative_trajectories"),
        (worst_staged, results_dir / "worst_failure_cases"),
    )
    if not replace and any(target.exists() for _, target in targets):
        raise TrajectoryExportError(
            "selected trajectory output already exists; pass replace=True for audited replacement"
        )
    backups: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for ordinal, (staged, target) in enumerate(targets):
            if target.exists():
                backup = results_dir / f".d5bak_{os.getpid()}_{ordinal}"
                if backup.exists():
                    raise TrajectoryExportError(f"stale trajectory-export backup: {backup}")
                os.replace(target, backup)
                backups.append((backup, target))
            os.replace(staged, target)
            published.append(target)
    except Exception:
        for target in reversed(published):
            if target.exists():
                shutil.rmtree(target)
        for backup, target in reversed(backups):
            if backup.exists():
                os.replace(backup, target)
        raise
    for backup, _ in backups:
        shutil.rmtree(backup)
    return targets[0][1] / "trajectory_manifest.json", targets[1][1] / "trajectory_manifest.json"


def _production_staging_root(final_results: Path) -> Path:
    """Create a short, same-filesystem staging root for atomic publication.

    Windows paths in the supplied workspace are already long, and temporary
    Parquet/run-store suffixes can otherwise cross the legacy path limit.  A
    system temporary directory is safe for publication only when it is on the
    same filesystem/volume as ``final_results``; otherwise the shortest safe
    fallback is a sibling of the canonical result directory.
    """

    system_temporary = Path(tempfile.gettempdir()).resolve()
    try:
        same_filesystem = (
            os.stat(system_temporary).st_dev == os.stat(final_results).st_dev
        )
    except OSError:
        same_filesystem = False
    base = system_temporary if same_filesystem else final_results.parent
    staging = Path(tempfile.mkdtemp(prefix="d5x_", dir=base)).resolve()
    try:
        if os.stat(staging).st_dev != os.stat(final_results).st_dev:
            raise TrajectoryExportError(
                "trajectory staging and final results are on different filesystems"
            )
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return staging


def export_final_selected_trajectories(
    *,
    repo_root: str | Path,
    results_dir: str | Path | None = None,
    replace: bool = False,
) -> TrajectoryExportResult:
    """Validate the complete locked final test, replay selections, and publish."""

    from d5freq.evaluation.phase6_analysis import validate_phase6_inputs
    from d5freq.evaluation.phase6_experiments import (
        Phase6Paths,
        _stored_provenance,
        build_protocol_material,
        build_run_plan,
        protocol_material_sha256,
    )

    root = Path(repo_root).resolve()
    final_results = (
        root / "results" / "final"
        if results_dir is None
        else Path(results_dir).resolve()
    )
    metrics_path = final_results / "per_episode_metrics.csv"
    ledger_path = final_results / "experiment_ledger.csv"
    lock_path = final_results / "protocol_lock.json"
    for path in (metrics_path, ledger_path, lock_path):
        if not path.is_file():
            raise TrajectoryExportError(f"required canonical final file is missing: {path.name}")
    metrics = pd.read_csv(metrics_path)
    ledger = pd.read_csv(ledger_path)
    validate_phase6_inputs(metrics, ledger, require_complete_final=True)
    if "final_protocol_lock_file_sha256" not in ledger.columns:
        raise TrajectoryExportError(
            "final ledger lacks final_protocol_lock_file_sha256 provenance"
        )
    lock_hashes = {
        str(value)
        for value in ledger["final_protocol_lock_file_sha256"].dropna().tolist()
    }
    if lock_hashes != {sha256_file(lock_path)}:
        raise TrajectoryExportError(
            "canonical protocol lock file hash differs from final ledger provenance"
        )
    lock = _load_protocol_lock(lock_path)
    material = lock["material"]
    assert isinstance(material, Mapping)
    paths = Phase6Paths.from_repo(root)
    current = build_protocol_material(paths, include_tuning_selection=True)
    if dict(strict_json_value(current)) != dict(strict_json_value(material)):
        raise TrajectoryExportError(
            "current FINAL configs/code/artifacts differ from canonical protocol lock"
        )
    material_sha = protocol_material_sha256(material)
    specs = build_run_plan(
        paths,
        stage="final",
        solver_tier="FINAL",
        artifact_state_sha256=material_sha,
        protocol_material=material,
    )
    spec_by_run = {spec.identity.run_id: spec for spec in specs}
    representative = select_representative_runs(metrics)
    worst = select_worst_runs(metrics, maximum_count=3)
    selected_by_run = {
        selection.run_id: selection
        for selection in (*representative, *worst)
    }
    if any(run_id not in spec_by_run for run_id in selected_by_run):
        raise TrajectoryExportError("selected run is absent from the locked final run plan")
    metrics_by_run = {
        str(row["run_id"]): row for row in metrics.to_dict("records")
    }
    ledger_by_run = {
        str(row["run_id"]): row for row in ledger.to_dict("records")
    }
    canonical_store = PerRunExperimentStore(paths.run_store_root("final"))
    canonical_for_replay: dict[str, CanonicalRunEvidence] = {}

    def canonical_provider(selection: SelectedRun) -> CanonicalRunEvidence:
        from d5freq.evaluation.phase6_canonical_journal import (
            load_and_verify_canonical_decision_journal,
        )

        spec = spec_by_run[selection.run_id]
        stored = canonical_store.load(spec.identity)
        if stored is None:
            raise TrajectoryExportError(
                f"selected canonical run envelope is missing: {selection.run_id}"
            )
        _stored_provenance(stored, spec)
        ledger_row = ledger_by_run[selection.run_id]
        if str(ledger_row.get("per_run_envelope_sha256", "")) != stored.sha256:
            raise TrajectoryExportError(
                "canonical envelope digest differs from final experiment ledger"
            )
        journal = load_and_verify_canonical_decision_journal(stored)
        _verify_ledger_journal_binding(ledger_row, journal.metadata)
        evidence = CanonicalRunEvidence(
            stored_run=stored,
            metrics=metrics_by_run[selection.run_id],
            ledger=ledger_row,
        )
        canonical_for_replay[selection.run_id] = evidence
        return evidence

    audit_base = {
        "schema_version": TRAJECTORY_EXPORT_AUDIT_SCHEMA_VERSION,
        "canonical_files": {
            "per_episode_metrics.csv": sha256_file(metrics_path),
            "experiment_ledger.csv": sha256_file(ledger_path),
            "protocol_lock.json": sha256_file(lock_path),
        },
        "selected_run_ids": sorted(selected_by_run),
    }
    staging = _production_staging_root(final_results)
    try:
        representative_manifest, worst_manifest = build_selected_outputs(
            results_dir=final_results,
            metrics_frame=metrics,
            ledger_frame=ledger,
            representative=representative,
            worst=worst,
            canonical_provider=canonical_provider,
            replay_provider=_production_replay_provider(
                spec_by_run, canonical_for_replay
            ),
            staging_root=staging / "bundle",
        )
        published_representative, published_worst = _publish_two_directories(
            representative_staged=representative_manifest.parent,
            worst_staged=worst_manifest.parent,
            results_dir=final_results,
            replace=replace,
        )
        _atomic_write_json(
            final_results / "trajectory_export_audit.json",
            {
                **audit_base,
                "status": "success",
                "representative_manifest_sha256": sha256_file(
                    published_representative
                ),
                "worst_manifest_sha256": sha256_file(published_worst),
            },
        )
        return TrajectoryExportResult(
            representative_manifest=published_representative,
            worst_manifest=published_worst,
            representative_count=len(representative),
            worst_count=len(worst),
        )
    except Exception as exc:
        _atomic_write_json(
            final_results / "trajectory_export_failure_audit.json",
            {
                **audit_base,
                "status": "failed_not_published",
                "failure_type": type(exc).__name__,
                "failure_message": str(exc),
            },
        )
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


__all__ = [
    "CANONICAL_JOURNAL_TRACE_SOURCE",
    "CanonicalRunEvidence",
    "DEFAULT_FLOAT_ABSOLUTE_TOLERANCE",
    "DEFAULT_FLOAT_RELATIVE_TOLERANCE",
    "NONDETERMINISTIC_EPISODE_FIELDS",
    "ReplayCapture",
    "SELECTED_TRAJECTORY_MANIFEST_SCHEMA_VERSION",
    "SelectedRun",
    "TrajectoryExportError",
    "TrajectoryExportResult",
    "build_selected_outputs",
    "build_canonical_journal_replay_capture",
    "compare_episode_results",
    "episode_result_mapping",
    "episode_result_sha256",
    "export_final_selected_trajectories",
    "records_frame",
    "select_representative_runs",
    "select_worst_runs",
]
