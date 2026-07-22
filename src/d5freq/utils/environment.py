"""Safe environment metadata export for reproducibility records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import sys
from typing import Any


DEFAULT_PACKAGE_NAMES: tuple[str, ...] = (
    "numpy",
    "scipy",
    "pandas",
    "pyarrow",
    "matplotlib",
    "scikit-learn",
    "PyYAML",
    "cvxpy",
    "pytest",
    "pytest-cov",
    "control",
    "typer",
    "jupyter",
    "Mosek",
    "gurobipy",
)

_SENSITIVE_KEY_FRAGMENTS: tuple[str, ...] = (
    "license",
    "secret",
    "token",
    "key",
    "password",
    "credential",
)
_REDACTED = "<redacted>"


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).casefold().replace("-", "_")
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _looks_like_secret(value: str) -> bool:
    normalized = value.strip().casefold()
    return (
        "-----begin private key-----" in normalized
        or "-----begin license" in normalized
        or normalized.startswith(("sk-", "ghp_", "glpat-", "xoxb-", "xoxp-"))
    )


def redact_sensitive(value: Any) -> Any:
    """Recursively copy metadata while redacting sensitive keys and token shapes."""

    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            rendered_key = str(key)
            redacted[rendered_key] = (
                _REDACTED if _is_sensitive_key(key) else redact_sensitive(item)
            )
        return redacted
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str) and _looks_like_secret(value):
        return _REDACTED
    return deepcopy(value)


def _package_versions(package_names: Sequence[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in sorted(set(package_names), key=str.casefold):
        try:
            versions[package_name] = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            versions[package_name] = "not_installed"
    return versions


def _physical_memory_bytes() -> int | None:
    try:
        import psutil  # type: ignore[import-not-found]

        return int(psutil.virtual_memory().total)
    except (ImportError, AttributeError, OSError):
        return None


def _solver_info() -> dict[str, Any]:
    result: dict[str, Any] = {
        "installed_cvxpy_solvers": [],
        "versions": _package_versions(("cvxpy", "Mosek", "gurobipy")),
        "interface_discovery_only": True,
    }
    try:
        import cvxpy as cp

        result["installed_cvxpy_solvers"] = sorted(cp.installed_solvers())
    except Exception as exc:  # Environment collection must remain best-effort.
        result["query_error_type"] = type(exc).__name__
    return result


def collect_environment_info(
    *,
    package_names: Sequence[str] = DEFAULT_PACKAGE_NAMES,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect an allowlisted, license-safe reproducibility snapshot.

    This function never exports the process environment, Conda prefix, license
    contents, license paths, API keys, or credentials. Solver discovery only asks
    CVXPY which solver interfaces are installed; it does not check out a
    commercial-solver entitlement.
    """

    memory_bytes = _physical_memory_bytes()
    system_info: dict[str, Any] = {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count_logical": os.cpu_count(),
    }
    if memory_bytes is not None:
        system_info["ram_bytes"] = memory_bytes

    info: dict[str, Any] = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "python": {
            "version": platform.python_version(),
            "version_info": list(sys.version_info[:3]),
            "implementation": platform.python_implementation(),
            "executable_name": Path(sys.executable).name,
        },
        "platform": system_info,
        "conda": {
            "active_environment": os.environ.get("CONDA_DEFAULT_ENV"),
        },
        "packages": _package_versions(package_names),
        "solvers": _solver_info(),
    }
    if extra is not None:
        info["extra"] = dict(extra)
    return redact_sensitive(info)


def write_environment_info(
    path: str | Path,
    info: Mapping[str, Any] | None = None,
    *,
    extra: Mapping[str, Any] | None = None,
) -> Path:
    """Write a sanitized environment snapshot as UTF-8 JSON."""

    if info is None:
        payload = collect_environment_info(extra=extra)
    else:
        payload = dict(info)
        if extra is not None:
            payload["extra"] = dict(extra)
        payload = redact_sensitive(payload)
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        handle.write("\n")
    return output_path


__all__ = [
    "DEFAULT_PACKAGE_NAMES",
    "collect_environment_info",
    "redact_sensitive",
    "write_environment_info",
]
