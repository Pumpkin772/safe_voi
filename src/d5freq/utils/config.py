"""Explicit, side-effect-free YAML configuration loading."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .hashing import sha256_json


class ConfigError(ValueError):
    """Raised when a configuration file is malformed or ambiguous."""


def resolve_path(
    path: str | Path,
    *,
    base_dir: str | Path | None = None,
    must_exist: bool = False,
) -> Path:
    """Resolve an explicit path, optionally relative to an explicit base directory."""

    if str(path).strip() == "":
        raise ValueError("path must not be empty")
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        anchor = Path.cwd() if base_dir is None else Path(base_dir).expanduser()
        candidate = anchor / candidate
    resolved = candidate.resolve()
    if must_exist and not resolved.exists():
        raise FileNotFoundError(resolved)
    return resolved


def deep_merge(
    base: Mapping[str, Any], override: Mapping[str, Any]
) -> dict[str, Any]:
    """Recursively merge two mappings without mutating either input.

    Mapping values are merged recursively. Lists and scalar values in ``override``
    replace their counterparts in ``base`` in full.
    """

    merged = deepcopy(dict(base))
    for key, override_value in override.items():
        if not isinstance(key, str):
            raise ConfigError("Configuration keys must be strings")
        base_value = merged.get(key)
        if isinstance(base_value, Mapping) and isinstance(override_value, Mapping):
            merged[key] = deep_merge(base_value, override_value)
        else:
            merged[key] = deepcopy(override_value)
    return merged


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load one explicitly named YAML file as a top-level mapping."""

    config_path = resolve_path(path, must_exist=True)
    if not config_path.is_file():
        raise ConfigError(f"Configuration path is not a file: {config_path}")
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ConfigError(
            f"Top-level YAML value must be a mapping: {config_path}"
        )
    return deep_merge({}, loaded)


def load_config(
    path: str | Path,
    *overlay_paths: str | Path,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load and recursively merge a base YAML file and ordered overlays."""

    config = load_yaml(path)
    for overlay_path in overlay_paths:
        config = deep_merge(config, load_yaml(overlay_path))
    if overrides is not None:
        config = deep_merge(config, overrides)
    return config


def _yaml_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {str(key): _yaml_safe(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_yaml_safe(item) for item in value]
    if isinstance(value, list):
        return [_yaml_safe(item) for item in value]
    return deepcopy(value)


def save_yaml(config: Mapping[str, Any], path: str | Path) -> Path:
    """Write a fully materialized configuration to an explicit path."""

    output_path = resolve_path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(
            _yaml_safe(config),
            handle,
            allow_unicode=True,
            sort_keys=False,
        )
    return output_path


def config_sha256(config: Mapping[str, Any]) -> str:
    """Return the canonical SHA-256 digest of an expanded configuration."""

    return sha256_json(config)


__all__ = [
    "ConfigError",
    "config_sha256",
    "deep_merge",
    "load_config",
    "load_yaml",
    "resolve_path",
    "save_yaml",
]
