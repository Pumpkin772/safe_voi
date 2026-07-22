"""Atomic, content-addressed storage for independent episode results.

Each run owns one file whose name is derived only from ``run_id``.  There is
no shared ledger to update during parallel execution, so different runs never
contend on a common mutable file.  Every envelope contains a SHA-256 over its
canonical strict-JSON body.  Resume validates both that digest and the full
run identity before returning a stored result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
import hashlib
import hmac
import json
import math
from numbers import Integral, Real
import os
from pathlib import Path
import tempfile
from typing import Any

import numpy as np

from d5freq.evaluation.results_schema import EpisodeResult


STORE_SCHEMA_VERSION = "d5freq.per-run-envelope.v1"
_ENVELOPE_KEYS = frozenset({"schema_version", "sha256", "body"})
_BODY_KEYS = frozenset({"identity", "episode_result", "run_payload"})
_IDENTITY_KEYS = frozenset({"run_id", "scenario_id", "method", "seed"})


class RunStoreError(RuntimeError):
    """Base class for run-store integrity and conflict failures."""


class RunIntegrityError(RunStoreError):
    """A stored envelope is malformed or its SHA-256 does not match."""


class RunIdentityMismatchError(RunStoreError):
    """The run-id file exists but belongs to another experiment identity."""


class RunConflictError(RunStoreError):
    """A valid run file exists with different content."""


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Complete identity required to accept a per-run resume artifact."""

    run_id: str
    scenario_id: str
    method: str
    seed: int

    def __post_init__(self) -> None:
        for name in ("run_id", "scenario_id", "method"):
            object.__setattr__(self, name, _nonempty(getattr(self, name), name))
        if isinstance(self.seed, (bool, np.bool_)) or not isinstance(self.seed, Integral):
            raise TypeError("seed must be an integer")
        object.__setattr__(self, "seed", int(self.seed))

    def to_dict(self) -> dict[str, str | int]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "method": self.method,
            "seed": self.seed,
        }


@dataclass(frozen=True, slots=True)
class StoredRun:
    identity: RunIdentity
    episode_result: EpisodeResult
    run_payload: Mapping[str, Any]
    sha256: str
    path: Path


def _strict_json_value(value: Any) -> Any:
    """Convert common scientific objects to strict JSON, mapping NaN/inf to null."""

    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Enum):
        return _strict_json_value(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return [_strict_json_value(item) for item in value.tolist()]
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("strict JSON mappings must use string keys")
            converted[key] = _strict_json_value(item)
        return converted
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_strict_json_value(item) for item in value]
    if hasattr(value, "to_dict"):
        return _strict_json_value(value.to_dict())
    if hasattr(value, "as_mapping"):
        return _strict_json_value(value.as_mapping())
    if is_dataclass(value):
        return _strict_json_value(asdict(value))
    if isinstance(value, Real):
        normalized = float(value)
        return normalized if math.isfinite(normalized) else None
    raise TypeError(f"value of type {type(value).__name__} is not strict-JSON serializable")


def strict_json_value(value: Any) -> Any:
    """Public validation/conversion helper used before atomic publication."""

    return _strict_json_value(value)


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(schema_version: str, body: Mapping[str, Any]) -> str:
    material = {"schema_version": schema_version, "body": body}
    return hashlib.sha256(_canonical_bytes(material)).hexdigest()


def _reject_constant(token: str) -> None:
    raise ValueError(f"non-standard JSON constant {token!r} is forbidden")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _read_strict_json(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(
            raw,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise RunIntegrityError(f"cannot read strict run envelope {path.name!r}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise RunIntegrityError("run envelope must be a JSON object")
    return value


class PerRunExperimentStore:
    """One atomic JSON file per run, safe for parallel runs and strict resume."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise ValueError("run store root must be a directory")

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, identity: RunIdentity) -> Path:
        if not isinstance(identity, RunIdentity):
            raise TypeError("identity must be a RunIdentity")
        filename = hashlib.sha256(identity.run_id.encode("utf-8")).hexdigest() + ".json"
        return self._root / filename

    def load(self, identity: RunIdentity) -> StoredRun | None:
        """Return a verified run or ``None``; never accept identity by filename alone."""

        path = self.path_for(identity)
        if not path.exists():
            return None
        envelope = _read_strict_json(path)
        if frozenset(envelope) != _ENVELOPE_KEYS:
            raise RunIntegrityError("run envelope keys do not match the store schema")
        if envelope["schema_version"] != STORE_SCHEMA_VERSION:
            raise RunIntegrityError("unsupported run envelope schema version")
        digest = envelope["sha256"]
        if not isinstance(digest, str) or len(digest) != 64:
            raise RunIntegrityError("run envelope SHA-256 is malformed")
        body = envelope["body"]
        if not isinstance(body, Mapping) or frozenset(body) != _BODY_KEYS:
            raise RunIntegrityError("run envelope body keys do not match the store schema")
        expected_digest = _digest(STORE_SCHEMA_VERSION, body)
        if not hmac.compare_digest(digest, expected_digest):
            raise RunIntegrityError("run envelope SHA-256 mismatch")

        raw_identity = body["identity"]
        if not isinstance(raw_identity, Mapping) or frozenset(raw_identity) != _IDENTITY_KEYS:
            raise RunIntegrityError("stored run identity is malformed")
        try:
            stored_identity = RunIdentity(**dict(raw_identity))
        except (TypeError, ValueError) as exc:
            raise RunIntegrityError(f"stored run identity is invalid: {exc}") from exc
        if stored_identity != identity:
            raise RunIdentityMismatchError(
                f"run_id {identity.run_id!r} belongs to a different stored identity"
            )

        raw_result = body["episode_result"]
        if not isinstance(raw_result, Mapping):
            raise RunIntegrityError("stored episode_result must be an object")
        try:
            result = EpisodeResult(**dict(raw_result))
        except (TypeError, ValueError) as exc:
            raise RunIntegrityError(f"stored episode_result is invalid: {exc}") from exc
        if (
            result.run_id,
            result.scenario_id,
            result.method,
            result.seed,
        ) != (
            identity.run_id,
            identity.scenario_id,
            identity.method,
            identity.seed,
        ):
            raise RunIdentityMismatchError("episode_result identity disagrees with envelope identity")
        payload = body["run_payload"]
        if not isinstance(payload, Mapping):
            raise RunIntegrityError("stored run_payload must be an object")
        return StoredRun(
            identity=stored_identity,
            episode_result=result,
            run_payload=dict(payload),
            sha256=digest,
            path=path,
        )

    def save(
        self,
        identity: RunIdentity,
        episode_result: EpisodeResult,
        run_payload: Mapping[str, Any],
        *,
        replace_existing: bool = False,
    ) -> StoredRun:
        """Atomically publish a complete envelope in the target directory."""

        if not isinstance(episode_result, EpisodeResult):
            raise TypeError("episode_result must be an EpisodeResult")
        if not isinstance(run_payload, Mapping):
            raise TypeError("run_payload must be a mapping")
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
            raise RunIdentityMismatchError("episode_result does not match save identity")

        body = {
            "identity": identity.to_dict(),
            "episode_result": episode_result.to_json_dict(),
            "run_payload": _strict_json_value(run_payload),
        }
        digest = _digest(STORE_SCHEMA_VERSION, body)
        envelope = {
            "schema_version": STORE_SCHEMA_VERSION,
            "sha256": digest,
            "body": body,
        }
        serialized = json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"
        path = self.path_for(identity)
        existing = self.load(identity)
        if existing is not None and not replace_existing:
            if existing.sha256 == digest:
                return existing
            raise RunConflictError(
                f"run {identity.run_id!r} already has different verified content"
            )

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{path.stem}.",
                suffix=".tmp",
                dir=self._root,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
        stored = self.load(identity)
        if stored is None or stored.sha256 != digest:
            raise RunIntegrityError("atomic run publication could not be verified")
        return stored


__all__ = [
    "PerRunExperimentStore",
    "RunConflictError",
    "RunIdentity",
    "RunIdentityMismatchError",
    "RunIntegrityError",
    "RunStoreError",
    "STORE_SCHEMA_VERSION",
    "StoredRun",
    "strict_json_value",
]
