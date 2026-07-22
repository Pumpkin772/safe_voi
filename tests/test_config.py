from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from d5freq.utils.config import (
    ConfigError,
    config_sha256,
    deep_merge,
    load_config,
    load_yaml,
    resolve_path,
    save_yaml,
)


def test_deep_merge_is_recursive_and_does_not_mutate_inputs() -> None:
    base = {
        "grid": {"f0_hz": 50.0, "limits": {"frequency_hz": 0.5}},
        "seeds": [0, 1],
    }
    override = {
        "grid": {"limits": {"rocof_hz_per_s": 0.5}},
        "seeds": [2],
    }
    base_before = deepcopy(base)
    override_before = deepcopy(override)

    merged = deep_merge(base, override)

    assert merged == {
        "grid": {
            "f0_hz": 50.0,
            "limits": {"frequency_hz": 0.5, "rocof_hz_per_s": 0.5},
        },
        "seeds": [2],
    }
    assert base == base_before
    assert override == override_before


def test_load_config_merges_ordered_yaml_layers_and_overrides(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    overlay_path = tmp_path / "overlay.yaml"
    base_path.write_text(
        "grid:\n  f0_hz: 50.0\n  limits:\n    frequency_hz: 0.5\n",
        encoding="utf-8",
    )
    overlay_path.write_text(
        "grid:\n  limits:\n    rocof_hz_per_s: 0.4\n",
        encoding="utf-8",
    )

    config = load_config(
        base_path,
        overlay_path,
        overrides={"grid": {"f0_hz": 60.0}},
    )

    assert config["grid"] == {
        "f0_hz": 60.0,
        "limits": {"frequency_hz": 0.5, "rocof_hz_per_s": 0.4},
    }
    output_path = save_yaml(config, tmp_path / "resolved" / "config.yaml")
    assert output_path.is_absolute()
    assert load_yaml(output_path) == config
    assert config_sha256(load_yaml(output_path)) == config_sha256(config)


def test_paths_are_resolved_explicitly(tmp_path: Path) -> None:
    resolved = resolve_path("nested/config.yaml", base_dir=tmp_path)
    assert resolved == (tmp_path / "nested" / "config.yaml").resolve()
    assert resolved.is_absolute()
    with pytest.raises(FileNotFoundError):
        resolve_path("missing.yaml", base_dir=tmp_path, must_exist=True)


def test_load_yaml_rejects_non_mapping_root(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("- one\n- two\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Top-level YAML"):
        load_yaml(path)
