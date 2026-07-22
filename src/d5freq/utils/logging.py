"""Small JSON Lines logging helpers with no process-global configuration."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
import json
from pathlib import Path
import traceback
from types import MappingProxyType
from typing import Any


def utc_now_iso() -> str:
    """Return an RFC 3339 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=repr)
    tolist_method = getattr(value, "tolist", None)
    if callable(tolist_method):
        return tolist_method()
    item_method = getattr(value, "item", None)
    if callable(item_method):
        scalar = item_method()
        if scalar is not value:
            return scalar
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _encode_record(record: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(record),
        default=_json_default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def append_jsonl(path: str | Path, record: Mapping[str, Any]) -> Path:
    """Append one complete UTF-8 JSON object to a JSONL file."""

    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _encode_record(record)
    with output_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
        handle.write("\n")
    return output_path


def write_jsonl(
    path: str | Path,
    records: Iterable[Mapping[str, Any]],
    *,
    append: bool = False,
) -> Path:
    """Write an iterable of mappings to JSONL, optionally appending."""

    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with output_path.open(mode, encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(_encode_record(record))
            handle.write("\n")
    return output_path


def iter_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield decoded JSON objects from a JSONL file."""

    input_path = Path(path).expanduser().resolve()
    with input_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSONL object at {input_path}:{line_number}"
                ) from exc
            if not isinstance(value, dict):
                raise ValueError(
                    f"JSONL record must be an object at {input_path}:{line_number}"
                )
            yield value


@dataclass(frozen=True, slots=True)
class JsonlLogger:
    """File-backed structured logger with immutable per-run context."""

    path: str | Path
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path).expanduser().resolve())
        object.__setattr__(
            self,
            "context",
            MappingProxyType(deepcopy(dict(self.context))),
        )

    def log(self, level: str, event: str, **fields: Any) -> dict[str, Any]:
        """Append and return one structured log record."""

        if not event.strip():
            raise ValueError("event must not be empty")
        record = dict(self.context)
        record.update(fields)
        record.update(
            {
                "timestamp_utc": utc_now_iso(),
                "level": level.upper(),
                "event": event,
            }
        )
        append_jsonl(self.path, record)
        return record

    def info(self, event: str, **fields: Any) -> dict[str, Any]:
        return self.log("INFO", event, **fields)

    def warning(self, event: str, **fields: Any) -> dict[str, Any]:
        return self.log("WARNING", event, **fields)

    def error(self, event: str, **fields: Any) -> dict[str, Any]:
        return self.log("ERROR", event, **fields)

    def exception(
        self, event: str, error: BaseException, **fields: Any
    ) -> dict[str, Any]:
        """Log an exception type, message, and traceback."""

        exception_fields = dict(fields)
        exception_fields.update(
            {
                "exception_type": type(error).__name__,
                "exception_message": str(error),
                "traceback": "".join(
                    traceback.format_exception(type(error), error, error.__traceback__)
                ),
            }
        )
        return self.log("ERROR", event, **exception_fields)


__all__ = [
    "JsonlLogger",
    "append_jsonl",
    "iter_jsonl",
    "utc_now_iso",
    "write_jsonl",
]
