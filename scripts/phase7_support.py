"""Shared, dependency-light helpers for the Phase-7 audit deliverables.

This module deliberately lives under :mod:`scripts`: changing packaging and
plotting code after the Phase-6 final-test lock must not change the locked
controller/source hash.  It contains no controller or simulator imports.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable, Iterator, Mapping, Sequence


PACKAGE_ROOT_NAME = "D5_FROM_SCRATCH_SD_BMPC_REVIEW_PACKAGE"
ZIP_NAME = f"{PACKAGE_ROOT_NAME}.zip"
MAX_ZIP_BYTES = 512 * 1024 * 1024

RESULT_CSV_NAMES: tuple[str, ...] = (
    "per_episode_metrics.csv",
    "summary_metrics.csv",
    "statistical_tests.csv",
    "diagnostic_metrics.csv",
    "solver_metrics.csv",
    "experiment_ledger.csv",
)

FROZEN_REPRESENTATIVE_SELECTION: Mapping[str, tuple[str, ...]] = {
    "S2_sluggish_switch_060": ("B0", "B1", "B2", "B3", "B4", "P"),
    "S7_ood_asymmetric_limit": ("B1", "B3", "P", "no-OOD"),
}
FROZEN_REPLAY_TIMING_EXCLUSIONS: frozenset[str] = frozenset(
    {
        "solve_time_mean_s",
        "solve_time_p95_s",
        "solve_time_max_s",
        "wall_time_s",
        "oracle_regret",
    }
)

FIGURE_SPECS: tuple[tuple[str, str], ...] = (
    ("01_system_diagnostic_control_overview.png", "System, diagnosis, and control overview"),
    ("02_hidden_mode_truth_response.png", "Hidden-mode truth response comparison"),
    ("03_gmm_bic_and_clusters.png", "GMM BIC and mode clustering"),
    ("04_known_switch_truth_and_belief.png", "Known-mode switch truth and belief"),
    ("05_controller_frequency_comparison.png", "Controller frequency comparison"),
    ("06_commands_and_ibr_output.png", "SG/IBR commands and actual IBR output"),
    ("07_detection_delay_vs_iae.png", "Detection delay versus frequency IAE"),
    ("08_ood_fallback_frequency.png", "OOD p-value, fallback state, and frequency"),
    ("09_method_performance_distribution.png", "Method performance distribution"),
    ("10_ablation_results.png", "SD-BMPC ablation results"),
    ("11_solver_time_distribution.png", "Solver-time distribution"),
    ("12_worst_failure_case.png", "Worst retained failure case"),
)

REQUIRED_PACKAGE_DIRECTORIES: tuple[str, ...] = (
    "source",
    "research_docs",
    "configs",
    "tests",
    "environment",
    "artifacts/mode_discovery",
    "artifacts/ood_calibration",
    "artifacts/model_library",
    "results",
    "figures",
    "representative_trajectories",
    "worst_failure_cases",
    "logs",
    "git",
)

REQUIRED_TOP_LEVEL_DOCUMENTS: tuple[str, ...] = (
    "00_EXECUTIVE_SUMMARY.md",
    "01_RESEARCH_CLAIMS_AND_STATUS.md",
    "02_MATH_IMPLEMENTATION_MAP.md",
    "03_REPRODUCIBILITY_COMMANDS.md",
    "04_LIMITATIONS_AND_FAILURES.md",
    "05_FILE_INDEX.csv",
    "06_SHA256SUMS.txt",
)

_CACHE_DIR_NAMES = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".ipynb_checkpoints",
        ".venv",
        "venv",
        "env",
        "conda-meta",
        "site-packages",
        "node_modules",
        "build",
        "dist",
    }
)
_FORBIDDEN_SUFFIXES = frozenset(
    {".pyc", ".pyo", ".lic", ".pem", ".key", ".p12", ".pfx"}
)
_FORBIDDEN_EXACT_NAMES = frozenset(
    {
        ".coverage",
        "mosek.lic",
        "gurobi.lic",
        "credentials.json",
        "secrets.json",
    }
)
_SECRET_FILENAME = re.compile(
    r"(?:^|[_\-.])(credential|secret|api[_-]?key|private[_-]?key|access[_-]?token)(?:[_\-.]|$)",
    re.IGNORECASE,
)
_PRIVATE_KEY_MARKERS: tuple[bytes, ...] = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
)


class Phase7AuditError(RuntimeError):
    """Raised when a strict review-package or figure audit cannot proceed."""


def resolved(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
    )


def atomic_write_csv(
    path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(fieldnames), lineterminator="\n"
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") for name in fieldnames})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def require_file(path: Path, description: str | None = None) -> Path:
    if not path.is_file():
        label = description or str(path)
        raise Phase7AuditError(f"required file is missing: {label} ({path})")
    if path.is_symlink():
        raise Phase7AuditError(f"symbolic links are not accepted: {path}")
    return path


def require_nonempty_directory(path: Path, description: str | None = None) -> Path:
    if not path.is_dir():
        label = description or str(path)
        raise Phase7AuditError(f"required directory is missing: {label} ({path})")
    if path.is_symlink():
        raise Phase7AuditError(f"symbolic links are not accepted: {path}")
    if not any(item.is_file() for item in path.rglob("*")):
        label = description or str(path)
        raise Phase7AuditError(f"required directory has no files: {label} ({path})")
    return path


def forbidden_reason(relative: Path) -> str | None:
    parts = tuple(part.lower() for part in relative.parts)
    if any(part in _CACHE_DIR_NAMES or part.startswith(".pytest_tmp") for part in parts[:-1]):
        return "repository metadata, environment, build output, or cache directory"
    name = relative.name.lower()
    if name in _FORBIDDEN_EXACT_NAMES or name.startswith(".env"):
        return "credential, solver-license, or local state filename"
    if relative.suffix.lower() in _FORBIDDEN_SUFFIXES:
        return "compiled, credential, or solver-license suffix"
    if _SECRET_FILENAME.search(name):
        return "credential-like filename"
    return None


def iter_safe_files(source: Path) -> Iterator[tuple[Path, Path]]:
    """Yield ``(source_file, relative_path)`` in deterministic order.

    Excluded cache/environment/license/key paths are silently omitted because
    callers intentionally copy broader source/test trees.  Symlinks are a hard
    failure: silently following one could escape the repository.
    """

    source = resolved(source)
    if not source.is_dir():
        raise Phase7AuditError(f"copy source is not a directory: {source}")
    for candidate in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
        relative = candidate.relative_to(source)
        if candidate.is_symlink():
            raise Phase7AuditError(f"symbolic links are not accepted: {candidate}")
        if forbidden_reason(relative) is not None:
            continue
        if not candidate.is_file():
            continue
        prefix_reason = None
        for index in range(1, len(relative.parts)):
            prefix_reason = forbidden_reason(Path(*relative.parts[: index + 1]))
            if prefix_reason is not None:
                break
        if prefix_reason is not None:
            continue
        yield candidate, relative


def _scan_private_key_markers(path: Path) -> None:
    # Avoid loading large binary artifacts.  Keys are small text files; the
    # marker scan still catches a misleadingly named text key.
    if path.stat().st_size > 2 * 1024 * 1024:
        return
    content = path.read_bytes()
    if any(marker in content for marker in _PRIVATE_KEY_MARKERS):
        raise Phase7AuditError(f"private-key material detected in candidate file: {path}")


def copy_file_strict(source: Path, destination: Path) -> None:
    require_file(source)
    reason = forbidden_reason(Path(source.name))
    if reason is not None:
        raise Phase7AuditError(f"refusing forbidden file {source}: {reason}")
    _scan_private_key_markers(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    # Normalize permissions so source-machine ACL/mode differences do not
    # affect the archive metadata.
    try:
        destination.chmod(0o644)
    except OSError:
        pass


def copy_tree_strict(source: Path, destination: Path) -> int:
    copied = 0
    for item, relative in iter_safe_files(source):
        _scan_private_key_markers(item)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item, target)
        try:
            target.chmod(0o644)
        except OSError:
            pass
        copied += 1
    if copied == 0:
        raise Phase7AuditError(f"copy source contains no eligible files: {source}")
    return copied


def find_first_file(candidates: Iterable[Path], description: str) -> Path:
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    rendered = ", ".join(str(candidate) for candidate in candidates)
    raise Phase7AuditError(f"required {description} not found; checked: {rendered}")


def relative_posix(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    require_file(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def parse_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def parse_float(value: object) -> float | None:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def validate_result_identity(results_dir: Path) -> dict[str, int]:
    """Ensure the canonical result and ledger CSVs retain the same runs."""

    result_rows = read_csv_rows(results_dir / "per_episode_metrics.csv")
    ledger_rows = read_csv_rows(results_dir / "experiment_ledger.csv")
    if not result_rows:
        raise Phase7AuditError("per_episode_metrics.csv contains no episode rows")
    if not ledger_rows:
        raise Phase7AuditError("experiment_ledger.csv contains no episode rows")
    for label, rows in (("metrics", result_rows), ("ledger", ledger_rows)):
        if "run_id" not in rows[0]:
            raise Phase7AuditError(f"{label} CSV has no run_id column")
        identifiers = [row.get("run_id", "") for row in rows]
        if any(not identifier for identifier in identifiers):
            raise Phase7AuditError(f"{label} CSV contains a blank run_id")
        if len(set(identifiers)) != len(identifiers):
            raise Phase7AuditError(f"{label} CSV contains duplicate run_id values")
    metric_ids = {row["run_id"] for row in result_rows}
    ledger_ids = {row["run_id"] for row in ledger_rows}
    if metric_ids != ledger_ids:
        missing_metrics = sorted(ledger_ids - metric_ids)[:10]
        missing_ledger = sorted(metric_ids - ledger_ids)[:10]
        raise Phase7AuditError(
            "episode result/ledger run_id sets differ; failure rows may have been "
            f"dropped (missing_metrics={missing_metrics}, missing_ledger={missing_ledger})"
        )
    incomplete = sum(
        parse_bool(row.get("run_completed")) is False for row in result_rows
    )
    metric_incomplete = sum(
        parse_bool(row.get("metrics_complete")) is False for row in result_rows
    )
    scientific_failures = sum(
        parse_bool(row.get("scientific_success")) is False for row in result_rows
    )
    return {
        "episode_count": len(result_rows),
        "incomplete_episode_count": incomplete,
        "metrics_incomplete_count": metric_incomplete,
        "scientific_failure_count": scientific_failures,
    }


def _strict_relative_path(
    *,
    base: Path,
    relative_value: object,
    containment_root: Path,
    description: str,
) -> Path:
    if not isinstance(relative_value, str) or not relative_value.strip():
        raise Phase7AuditError(f"{description} must contain a non-empty relative_path")
    relative = Path(relative_value)
    if relative.is_absolute():
        raise Phase7AuditError(f"{description} path must be relative: {relative_value!r}")
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(containment_root.resolve())
    except ValueError as exc:
        raise Phase7AuditError(
            f"{description} path escapes its permitted root: {relative_value!r}"
        ) from exc
    return candidate


def _require_sha256(value: object, description: str) -> str:
    normalized = str(value)
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise Phase7AuditError(f"{description} must be a lowercase SHA256 hex digest")
    return normalized


def _sha256_canonical_json(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _parquet_audit(path: Path, expected_rows: object, description: str) -> None:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - project dependency gate
        raise Phase7AuditError("pyarrow is required to audit selected Parquet traces") from exc
    if path.suffix.lower() != ".parquet":
        raise Phase7AuditError(f"{description} must be a Parquet file: {path}")
    try:
        row_count = int(expected_rows)
    except (TypeError, ValueError) as exc:
        raise Phase7AuditError(f"{description} row_count must be an integer") from exc
    if row_count < 0:
        raise Phase7AuditError(f"{description} row_count must be non-negative")
    parquet = pq.ParquetFile(path)
    observed = int(parquet.metadata.num_rows)
    if observed != row_count:
        raise Phase7AuditError(
            f"{description} row_count mismatch: manifest={row_count}, parquet={observed}"
        )
    codecs = {
        str(parquet.metadata.row_group(group).column(column).compression).upper()
        for group in range(parquet.metadata.num_row_groups)
        for column in range(parquet.metadata.row_group(group).num_columns)
    }
    if codecs and codecs != {"ZSTD"}:
        raise Phase7AuditError(
            f"{description} must use ZSTD for every Parquet column chunk; observed={sorted(codecs)}"
        )


def _equivalent_csv_value(csv_value: object, manifest_value: object) -> bool:
    csv_missing = csv_value is None or str(csv_value).strip() == ""
    manifest_missing = manifest_value is None or (
        isinstance(manifest_value, str) and manifest_value.strip() == ""
    )
    if csv_missing or manifest_missing:
        return csv_missing and manifest_missing
    csv_bool = parse_bool(csv_value)
    manifest_bool = parse_bool(manifest_value)
    if csv_bool is not None and manifest_bool is not None:
        return csv_bool == manifest_bool
    csv_number = parse_float(csv_value)
    manifest_number = parse_float(manifest_value)
    if csv_number is not None and manifest_number is not None:
        return math.isclose(csv_number, manifest_number, rel_tol=0.0, abs_tol=1e-12)
    return str(csv_value) == str(manifest_value)


def _equivalent_manifest_value(
    first: object,
    second: object,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> bool:
    if first is None or second is None:
        return first is None and second is None
    if isinstance(first, bool) or isinstance(second, bool):
        return isinstance(first, bool) and isinstance(second, bool) and first == second
    if isinstance(first, (int, float)) and isinstance(second, (int, float)):
        return math.isclose(
            float(first),
            float(second),
            rel_tol=relative_tolerance,
            abs_tol=absolute_tolerance,
        )
    return first == second


def validate_selected_trajectory_manifest(
    directory: Path,
    *,
    results_dir: Path,
    expected_role: str,
    enforce_frozen_selection: bool = False,
) -> dict[str, Any]:
    """Authenticate deterministic selected-run replay exports.

    The four retained tables for every entry must be ZSTD Parquet, and their
    path, SHA256, and row count are checked.  Canonical metrics/ledger/protocol
    bindings and replay-consistency evidence are also mandatory.  No replay is
    performed here; this is an independent consumer-side audit.
    """

    directory = resolved(directory)
    results_dir = resolved(results_dir)
    require_nonempty_directory(directory, f"selected {expected_role} trajectories")
    manifest_path = require_file(
        directory / "trajectory_manifest.json",
        f"selected {expected_role} trajectory manifest",
    )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Phase7AuditError(f"invalid selected trajectory manifest: {manifest_path}") from exc
    if not isinstance(payload, dict):
        raise Phase7AuditError("selected trajectory manifest root must be an object")
    if payload.get("schema_version") != "d5freq.selected_trajectory_manifest.v1":
        raise Phase7AuditError("selected trajectory manifest schema_version mismatch")
    if payload.get("hash_algorithm") != "sha256":
        raise Phase7AuditError("selected trajectory manifest hash_algorithm must be sha256")
    result_hash_fields = payload.get("episode_result_hash_fields")
    if (
        not isinstance(result_hash_fields, list)
        or not result_hash_fields
        or not all(isinstance(field, str) and field for field in result_hash_fields)
        or len(set(result_hash_fields)) != len(result_hash_fields)
    ):
        raise Phase7AuditError(
            "selected trajectory manifest episode_result_hash_fields is malformed"
        )
    if enforce_frozen_selection:
        from d5freq.evaluation.results_schema import EPISODE_RESULT_COLUMNS

        if result_hash_fields != list(EPISODE_RESULT_COLUMNS):
            raise Phase7AuditError(
                "selected trajectory manifest must declare the exact ordered "
                "EpisodeResult field set"
            )
    if not isinstance(payload.get("episode_result_hash_serialization"), str):
        raise Phase7AuditError(
            "selected trajectory manifest lacks episode_result_hash_serialization"
        )
    if not payload.get("selection_policy"):
        raise Phase7AuditError("selected trajectory manifest lacks selection_policy")

    canonical = payload.get("canonical_results")
    if not isinstance(canonical, Mapping):
        raise Phase7AuditError("selected trajectory manifest lacks canonical_results")
    canonical_keys = {
        "metrics": "per_episode_metrics.csv",
        "ledger": "experiment_ledger.csv",
        "protocol_lock": "protocol_lock.json",
    }
    for key, expected_name in canonical_keys.items():
        record = canonical.get(key)
        if not isinstance(record, Mapping):
            raise Phase7AuditError(f"canonical_results.{key} must be an object")
        candidate = _strict_relative_path(
            base=directory,
            relative_value=record.get("relative_path", record.get("path")),
            containment_root=results_dir,
            description=f"canonical_results.{key}",
        )
        require_file(candidate, f"canonical selected-replay input {key}")
        expected_candidate = (results_dir / expected_name).resolve()
        if candidate != expected_candidate:
            raise Phase7AuditError(
                f"canonical_results.{key} must bind the exact canonical file "
                f"{expected_candidate}, found {candidate}"
            )
        recorded_sha = _require_sha256(
            record.get("sha256"), f"canonical_results.{key}.sha256"
        )
        if sha256_file(candidate) != recorded_sha:
            raise Phase7AuditError(f"canonical selected-replay hash mismatch: {key}")

    metric_rows = {row["run_id"]: row for row in read_csv_rows(results_dir / "per_episode_metrics.csv")}
    ledger_rows = {row["run_id"]: row for row in read_csv_rows(results_dir / "experiment_ledger.csv")}
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise Phase7AuditError("selected trajectory manifest entries must be non-empty")
    seen: set[str] = set()
    required_files = {
        "control_trajectory",
        "high_frequency_truth",
        "truth_intervals",
        "controller_records",
    }
    acceptable_status = {"pass", "passed", "match", "matched", "consistent", "verified"}
    selection_rows: list[tuple[str, str, int, str]] = []
    for index, entry in enumerate(entries):
        label = f"entries[{index}]"
        if not isinstance(entry, Mapping):
            raise Phase7AuditError(f"{label} must be an object")
        for field in (
            "run_id",
            "scenario_id",
            "method",
            "seed",
            "selection_role",
            "selection_rank",
            "selection_basis",
        ):
            if entry.get(field) in (None, ""):
                raise Phase7AuditError(f"{label} lacks {field}")
        run_id = str(entry["run_id"])
        if run_id in seen:
            raise Phase7AuditError(f"duplicate selected run_id: {run_id}")
        seen.add(run_id)
        role = str(entry["selection_role"]).lower().replace("-", "_")
        normalized_expected = expected_role.lower().replace("-", "_")
        if normalized_expected not in role:
            raise Phase7AuditError(
                f"{label} selection_role={entry['selection_role']!r} does not match {expected_role!r} directory"
            )
        try:
            selection_rank = int(entry["selection_rank"])
        except (TypeError, ValueError) as exc:
            raise Phase7AuditError(f"{label}.selection_rank must be an integer") from exc
        selection_rows.append(
            (
                str(entry["scenario_id"]),
                str(entry["method"]),
                selection_rank,
                role,
            )
        )
        if run_id not in metric_rows or run_id not in ledger_rows:
            raise Phase7AuditError(f"selected run_id is absent from canonical results: {run_id}")
        for source_name, source_row in (
            ("metrics", metric_rows[run_id]),
            ("ledger", ledger_rows[run_id]),
        ):
            for field in ("scenario_id", "method", "seed"):
                if not _equivalent_csv_value(source_row.get(field), entry.get(field)):
                    raise Phase7AuditError(
                        f"{label} {field} disagrees with canonical {source_name} row"
                    )
        _require_sha256(
            entry.get("canonical_envelope_sha256"),
            f"{label}.canonical_envelope_sha256",
        )
        canonical_envelope_sha = str(entry["canonical_envelope_sha256"])
        ledger_envelope_sha = str(
            ledger_rows[run_id].get("per_run_envelope_sha256", "")
        )
        if canonical_envelope_sha != ledger_envelope_sha:
            raise Phase7AuditError(
                f"{label}.canonical_envelope_sha256 differs from final ledger"
            )
        canonical_result_sha = _require_sha256(
            entry.get("canonical_episode_result_sha256"),
            f"{label}.canonical_episode_result_sha256",
        )
        replay_envelope_sha = _require_sha256(
            entry.get("replay_envelope_sha256"), f"{label}.replay_envelope_sha256"
        )
        replay_result_sha = _require_sha256(
            entry.get("replay_episode_result_sha256"),
            f"{label}.replay_episode_result_sha256",
        )
        canonical_metrics = entry.get("canonical_metrics")
        if not isinstance(canonical_metrics, Mapping) or not canonical_metrics:
            raise Phase7AuditError(f"{label}.canonical_metrics must be non-empty")
        if set(canonical_metrics) != set(result_hash_fields):
            raise Phase7AuditError(
                f"{label}.canonical_metrics fields differ from declared episode_result_hash_fields"
            )
        canonical_episode_result = entry.get("canonical_episode_result")
        if not isinstance(canonical_episode_result, Mapping):
            raise Phase7AuditError(f"{label}.canonical_episode_result must be an object")
        if set(canonical_episode_result) != set(result_hash_fields):
            raise Phase7AuditError(
                f"{label}.canonical_episode_result fields differ from declaration"
            )
        if _sha256_canonical_json(dict(canonical_episode_result)) != canonical_result_sha:
            raise Phase7AuditError(
                f"{label}.canonical_episode_result_sha256 does not bind canonical_episode_result"
            )
        for field, value in canonical_metrics.items():
            if field not in metric_rows[run_id]:
                raise Phase7AuditError(f"{label}.canonical_metrics has unknown field {field!r}")
            if not _equivalent_csv_value(metric_rows[run_id].get(field), value):
                raise Phase7AuditError(
                    f"{label}.canonical_metrics.{field} disagrees with canonical CSV"
                )
        replay_envelope_path = _strict_relative_path(
            base=directory,
            relative_value=entry.get("replay_envelope_relative_path"),
            containment_root=directory,
            description=f"{label}.replay_envelope_relative_path",
        )
        require_file(replay_envelope_path, "selected replay envelope")
        if "replay_envelope_file_sha256" in entry:
            replay_file_sha = _require_sha256(
                entry.get("replay_envelope_file_sha256"),
                f"{label}.replay_envelope_file_sha256",
            )
            if sha256_file(replay_envelope_path) != replay_file_sha:
                raise Phase7AuditError(f"{label} replay envelope file SHA256 mismatch")
        try:
            replay_payload = json.loads(replay_envelope_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise Phase7AuditError(f"{label} replay envelope is invalid JSON") from exc
        if not isinstance(replay_payload, Mapping):
            raise Phase7AuditError(f"{label} replay envelope root must be an object")
        replay_body = replay_payload.get("body")
        replay_schema = replay_payload.get("schema_version")
        if not isinstance(replay_body, Mapping) or not isinstance(replay_schema, str):
            raise Phase7AuditError(f"{label} replay envelope lacks schema/body")
        computed_envelope_sha = _sha256_canonical_json(
            {"schema_version": replay_schema, "body": dict(replay_body)}
        )
        if replay_payload.get("sha256") != replay_envelope_sha or computed_envelope_sha != replay_envelope_sha:
            raise Phase7AuditError(f"{label} replay_envelope_sha256 does not bind its JSON body")
        replay_identity = replay_body.get("identity")
        if not isinstance(replay_identity, Mapping) or any(
            not _equivalent_csv_value(replay_identity.get(field), entry.get(field))
            for field in ("run_id", "scenario_id", "method", "seed")
        ):
            raise Phase7AuditError(f"{label} replay envelope identity mismatch")
        replay_metrics = replay_body.get("episode_result")
        if not isinstance(replay_metrics, Mapping):
            raise Phase7AuditError(f"{label} replay envelope lacks episode_result")
        if set(replay_metrics) != set(result_hash_fields):
            raise Phase7AuditError(
                f"{label} replay episode_result fields differ from declaration"
            )
        if _sha256_canonical_json(dict(replay_metrics)) != replay_result_sha:
            raise Phase7AuditError(
                f"{label}.replay_episode_result_sha256 does not bind replay envelope result"
            )
        trace_source = entry.get("trace_source")
        if trace_source == "canonical_action_journal_forced_simulator_replay":
            journal_audit = entry.get("canonical_journal")
            endpoint_audit = entry.get("endpoint_consistency_audit")
            scientific_audit = entry.get("scientific_recomputation_audit")
            if not all(
                isinstance(value, Mapping)
                for value in (journal_audit, endpoint_audit, scientific_audit)
            ):
                raise Phase7AuditError(
                    f"{label} canonical journal replay lacks source audits"
                )
            assert isinstance(journal_audit, Mapping)
            assert isinstance(endpoint_audit, Mapping)
            assert isinstance(scientific_audit, Mapping)
            _require_sha256(
                journal_audit.get("schema_sha256"),
                f"{label}.canonical_journal.schema_sha256",
            )
            journal_sha = _require_sha256(
                journal_audit.get("sha256"),
                f"{label}.canonical_journal.sha256",
            )
            if (
                not isinstance(journal_audit.get("schema_version"), str)
                or not journal_audit.get("schema_version")
                or str(journal_audit.get("compression", "")).lower() != "zstd"
            ):
                raise Phase7AuditError(
                    f"{label} canonical journal schema/compression audit is malformed"
                )
            try:
                journal_rows = int(journal_audit.get("row_count"))
            except (TypeError, ValueError) as exc:
                raise Phase7AuditError(
                    f"{label} canonical journal row_count is malformed"
                ) from exc
            if journal_rows <= 0:
                raise Phase7AuditError(
                    f"{label} canonical journal row_count must be positive"
                )
            if (
                endpoint_audit.get("trace_source") != trace_source
                or endpoint_audit.get("controller_or_solver_invoked") is not False
                or endpoint_audit.get("journal_sha256") != journal_sha
                or endpoint_audit.get("journal_row_count") != journal_rows
            ):
                raise Phase7AuditError(
                    f"{label} canonical journal endpoint audit is inconsistent"
                )
            try:
                endpoint_tolerance = float(
                    endpoint_audit.get("comparison_abs_tolerance")
                )
                measurement_difference = float(
                    endpoint_audit.get("max_abs_measurement_difference")
                )
                truth_difference = float(
                    endpoint_audit.get("max_abs_truth_difference")
                )
            except (TypeError, ValueError) as exc:
                raise Phase7AuditError(
                    f"{label} canonical journal endpoint differences are malformed"
                ) from exc
            if (
                endpoint_tolerance < 0.0
                or measurement_difference > endpoint_tolerance
                or truth_difference > endpoint_tolerance
            ):
                raise Phase7AuditError(
                    f"{label} canonical journal endpoint audit exceeds tolerance"
                )
            if (
                scientific_audit.get("status") != "verified"
                or scientific_audit.get("mismatches") != []
            ):
                raise Phase7AuditError(
                    f"{label} canonical journal scientific recomputation failed"
                )
            replay_run_payload = replay_body.get("run_payload")
            if not isinstance(replay_run_payload, Mapping) or (
                replay_run_payload.get("trace_source") != trace_source
                or replay_run_payload.get("canonical_journal") != journal_audit
                or replay_run_payload.get("endpoint_consistency_audit")
                != endpoint_audit
                or replay_run_payload.get("scientific_recomputation_audit")
                != scientific_audit
            ):
                raise Phase7AuditError(
                    f"{label} manifest replay audit differs from its envelope"
                )
        for consistency_name in (
            "canonical_store_consistency",
            "replay_consistency",
        ):
            consistency = entry.get(consistency_name)
            if not isinstance(consistency, Mapping):
                raise Phase7AuditError(f"{label}.{consistency_name} must be an object")
            status = str(consistency.get("status", "")).lower()
            if status not in acceptable_status:
                raise Phase7AuditError(
                    f"{label} {consistency_name} did not pass: {status!r}"
                )
            compared = consistency.get("compared_fields")
            tolerances = consistency.get("tolerances")
            mismatches = consistency.get("mismatches")
            if not isinstance(compared, list) or not compared:
                raise Phase7AuditError(
                    f"{label} {consistency_name} lacks compared_fields"
                )
            if not isinstance(tolerances, Mapping):
                raise Phase7AuditError(
                    f"{label} {consistency_name} lacks tolerances"
                )
            if not isinstance(mismatches, list) or mismatches:
                raise Phase7AuditError(
                    f"{label} {consistency_name} contains mismatches"
                )
            if enforce_frozen_selection:
                excluded = consistency.get("excluded_nondeterministic_fields")
                if not isinstance(excluded, list) or set(excluded) != set(
                    FROZEN_REPLAY_TIMING_EXCLUSIONS
                ):
                    raise Phase7AuditError(
                        f"{label} {consistency_name} has an incorrect replay "
                        "exclusion set"
                    )
                expected_compared = set(result_hash_fields) - set(
                    FROZEN_REPLAY_TIMING_EXCLUSIONS
                )
                if len(compared) != len(set(compared)) or set(compared) != expected_compared:
                    raise Phase7AuditError(
                        f"{label} {consistency_name} does not compare every "
                        "non-timing EpisodeResult field exactly once"
                    )
            try:
                absolute_tolerance = float(tolerances.get("float_absolute", tolerances.get("absolute", 0.0)))
                relative_tolerance = float(tolerances.get("float_relative", tolerances.get("relative", 0.0)))
            except (TypeError, ValueError) as exc:
                raise Phase7AuditError(
                    f"{label} {consistency_name} has invalid tolerances"
                ) from exc
            comparison_target = (
                canonical_episode_result
                if consistency_name == "canonical_store_consistency"
                else replay_metrics
            )
            for field in compared:
                if field not in canonical_metrics or field not in comparison_target:
                    raise Phase7AuditError(
                        f"{label} {consistency_name} compares unknown field {field!r}"
                    )
                if not _equivalent_manifest_value(
                    canonical_metrics[field],
                    comparison_target[field],
                    absolute_tolerance=absolute_tolerance,
                    relative_tolerance=relative_tolerance,
                ):
                    raise Phase7AuditError(
                        f"{label} {consistency_name} falsely declares field {field!r} consistent"
                    )
        files = entry.get("files")
        if not isinstance(files, Mapping) or set(files) != required_files:
            raise Phase7AuditError(
                f"{label}.files must contain exactly {sorted(required_files)}"
            )
        for file_kind in sorted(required_files):
            record = files[file_kind]
            if not isinstance(record, Mapping):
                raise Phase7AuditError(f"{label}.files.{file_kind} must be an object")
            candidate = _strict_relative_path(
                base=directory,
                relative_value=record.get("relative_path", record.get("path")),
                containment_root=directory,
                description=f"{label}.files.{file_kind}",
            )
            require_file(candidate, f"selected replay {file_kind}")
            recorded_sha = _require_sha256(
                record.get("sha256"), f"{label}.files.{file_kind}.sha256"
            )
            if sha256_file(candidate) != recorded_sha:
                raise Phase7AuditError(
                    f"selected replay file hash mismatch: {label}.files.{file_kind}"
                )
            if str(record.get("compression", "")).lower() != "zstd":
                raise Phase7AuditError(
                    f"{label}.files.{file_kind} must declare compression=zstd"
                )
            _parquet_audit(
                candidate,
                record.get("row_count"),
                f"{label}.files.{file_kind}",
            )
    ranks = sorted(rank for _, _, rank, _ in selection_rows)
    if ranks != list(range(1, len(selection_rows) + 1)):
        raise Phase7AuditError(
            "selected trajectory ranks must be unique contiguous integers from one"
        )
    if enforce_frozen_selection:
        normalized_expected = expected_role.lower().replace("-", "_")
        if normalized_expected == "representative":
            expected_pairs = {
                (scenario, method)
                for scenario, methods in FROZEN_REPRESENTATIVE_SELECTION.items()
                for method in methods
            }
            observed_pairs = {
                (scenario, method) for scenario, method, _, _ in selection_rows
            }
            if len(selection_rows) != 10 or observed_pairs != expected_pairs:
                raise Phase7AuditError(
                    "representative trajectory selection differs from the frozen "
                    "two-scenario, ten-method comparison set"
                )
            for scenario, methods in FROZEN_REPRESENTATIVE_SELECTION.items():
                selected_seeds = {
                    int(entry["seed"])
                    for entry in entries
                    if str(entry["scenario_id"]) == scenario
                    and str(entry["method"]) in methods
                }
                if len(selected_seeds) != 1:
                    raise Phase7AuditError(
                        f"representative comparisons for {scenario} must share one seed"
                    )
        elif normalized_expected == "worst":
            if len(selection_rows) != 3 or any(
                role != "worst_failure" for _, _, _, role in selection_rows
            ):
                raise Phase7AuditError(
                    "worst_failure_cases must contain exactly three ranked entries"
                )
        else:
            raise Phase7AuditError(f"unknown frozen selection role {expected_role!r}")
    return payload


def relocate_selected_trajectory_manifest(
    directory: Path,
    *,
    results_dir: Path,
    expected_role: str,
    enforce_frozen_selection: bool = True,
) -> Path:
    """Rebase canonical-result links after copying a trajectory bundle.

    The replay evidence files and their hashes are byte-for-byte copies.  Only
    the three relative links to canonical result files change when the bundle
    moves from ``results/final/<role>`` to the review package's top level.
    The rewritten manifest is immediately consumed by the independent strict
    validator so a broken package-relative path cannot be published.
    """

    directory = resolved(directory)
    results_dir = resolved(results_dir)
    manifest = require_file(directory / "trajectory_manifest.json")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Phase7AuditError(f"invalid selected trajectory manifest: {manifest}") from exc
    if not isinstance(payload, dict) or not isinstance(
        payload.get("canonical_results"), dict
    ):
        raise Phase7AuditError("selected trajectory manifest lacks canonical_results")
    names = {
        "metrics": "per_episode_metrics.csv",
        "ledger": "experiment_ledger.csv",
        "protocol_lock": "protocol_lock.json",
    }
    canonical = payload["canonical_results"]
    for key, name in names.items():
        record = canonical.get(key)
        if not isinstance(record, dict):
            raise Phase7AuditError(f"canonical_results.{key} must be an object")
        target = require_file(results_dir / name, f"packaged canonical {name}")
        record["relative_path"] = Path(
            os.path.relpath(target, directory)
        ).as_posix()
        record.pop("path", None)
    atomic_write_json(manifest, payload)
    validate_selected_trajectory_manifest(
        directory,
        results_dir=results_dir,
        expected_role=expected_role,
        enforce_frozen_selection=enforce_frozen_selection,
    )
    return manifest


def collect_regular_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for item in root.rglob("*"):
        if item.is_symlink():
            raise Phase7AuditError(f"symbolic link found in staged package: {item}")
        if item.is_file():
            files.append(item)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def verify_no_forbidden_packaged_paths(root: Path) -> None:
    for path in collect_regular_files(root):
        relative = path.relative_to(root)
        reason = forbidden_reason(relative)
        if reason is not None:
            raise Phase7AuditError(
                f"forbidden path entered staged review package: {relative.as_posix()} ({reason})"
            )
        _scan_private_key_markers(path)


__all__ = [
    "FIGURE_SPECS",
    "MAX_ZIP_BYTES",
    "PACKAGE_ROOT_NAME",
    "Phase7AuditError",
    "REQUIRED_PACKAGE_DIRECTORIES",
    "REQUIRED_TOP_LEVEL_DOCUMENTS",
    "RESULT_CSV_NAMES",
    "ZIP_NAME",
    "atomic_write_csv",
    "atomic_write_json",
    "atomic_write_text",
    "collect_regular_files",
    "copy_file_strict",
    "copy_tree_strict",
    "find_first_file",
    "forbidden_reason",
    "parse_bool",
    "parse_float",
    "read_csv_rows",
    "relocate_selected_trajectory_manifest",
    "relative_posix",
    "require_file",
    "require_nonempty_directory",
    "resolved",
    "sha256_file",
    "validate_result_identity",
    "validate_selected_trajectory_manifest",
    "verify_no_forbidden_packaged_paths",
]
