"""Deterministic SHA-256 helpers for configs, artifacts, and manifests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from typing import Any


_DEFAULT_CHUNK_SIZE = 1024 * 1024


def _jsonable(value: Any) -> Any:
    """Convert common scientific-Python values to canonical JSON values."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite floats cannot be hashed canonically")
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Canonical JSON mappings require string keys")
            converted[key] = _jsonable(item)
        return converted
    if isinstance(value, (set, frozenset)):
        converted_items = [_jsonable(item) for item in value]
        return sorted(
            converted_items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return [_jsonable(item) for item in value]

    # NumPy scalars and arrays are supported without making NumPy a dependency
    # of this small module.
    tolist_method = getattr(value, "tolist", None)
    if callable(tolist_method):
        return _jsonable(tolist_method())
    item_method = getattr(value, "item", None)
    if callable(item_method):
        scalar = item_method()
        if scalar is not value:
            return _jsonable(scalar)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize *value* to stable UTF-8 JSON bytes."""

    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes | bytearray | memoryview) -> str:
    """Return the lowercase SHA-256 hex digest of a byte buffer."""

    return hashlib.sha256(bytes(data)).hexdigest()


def sha256_text(text: str) -> str:
    """Return the SHA-256 digest of UTF-8 encoded text."""

    return sha256_bytes(text.encode("utf-8"))


def sha256_json(value: Any) -> str:
    """Hash a value after deterministic JSON conversion."""

    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: str | Path, *, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> str:
    """Stream a file and return its SHA-256 digest."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    file_path = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_sha256_manifest(root: str | Path) -> tuple[dict[str, Any], ...]:
    """Return a deterministic manifest for every regular file below *root*."""

    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)
    files = sorted(
        (path for path in root_path.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root_path).as_posix(),
    )
    return tuple(
        {
            "path": path.relative_to(root_path).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in files
    )


def sha256_directory(root: str | Path) -> str:
    """Hash a directory from its sorted relative paths, sizes, and file hashes."""

    return sha256_json(file_sha256_manifest(root))


__all__ = [
    "canonical_json_bytes",
    "file_sha256_manifest",
    "sha256_bytes",
    "sha256_directory",
    "sha256_file",
    "sha256_json",
    "sha256_text",
]
