"""Repository-level independence and information-boundary checks."""

from __future__ import annotations

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCANNED_ROOTS = (ROOT / "src", ROOT / "scripts", ROOT / "configs")


def _text_files() -> list[Path]:
    suffixes = {".py", ".yaml", ".yml", ".toml"}
    return [
        path
        for directory in SCANNED_ROOTS
        if directory.exists()
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
    ]


def test_production_files_have_no_local_absolute_paths() -> None:
    windows_absolute = re.compile(r"(?i)(?:^|[\"'])(?:[a-z]:[\\/])")
    posix_absolute = re.compile(r"(?:^|[\"'])(?:/home/|/users/)", re.IGNORECASE)
    violations: list[str] = []
    for path in _text_files():
        text = path.read_text(encoding="utf-8")
        if windows_absolute.search(text) or posix_absolute.search(text):
            violations.append(str(path.relative_to(ROOT)))
    assert not violations, f"local absolute paths found in: {violations}"


def test_source_does_not_reference_unrelated_reproduction_package() -> None:
    # Keep the forbidden name split so this audit test does not flag itself if
    # tests are included in a future scan.
    forbidden = ("tg" + "sfr", "方向" + "3实现")
    violations: list[str] = []
    for path in _text_files():
        text = path.read_text(encoding="utf-8").lower()
        if any(token.lower() in text for token in forbidden):
            violations.append(str(path.relative_to(ROOT)))
    assert not violations, f"unrelated repository reference found in: {violations}"


def test_truth_configs_are_marked_simulator_and_evaluation_only() -> None:
    for name in ("modes_known.yaml", "modes_ood.yaml", "experiments.yaml"):
        with (ROOT / "configs" / name).open(encoding="utf-8") as stream:
            config = yaml.safe_load(stream)
        assert config["truth_access"] == "simulator_and_evaluation_only"


def test_controller_source_does_not_import_truth_config_names() -> None:
    controller_dir = ROOT / "src" / "d5freq" / "controllers"
    if not controller_dir.exists():
        return
    violations: list[str] = []
    for path in controller_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "modes_known" in text or "modes_ood" in text:
            violations.append(str(path.relative_to(ROOT)))
    assert not violations, f"controller imports simulator truth config: {violations}"


def test_production_source_uses_no_numpy_global_random_draws() -> None:
    forbidden_global_rng = re.compile(
        r"\bnp\.random\.(?!(?:Generator|PCG64|SeedSequence|default_rng)\b)"
    )
    violations: list[str] = []
    source_root = ROOT / "src"
    for path in source_root.rglob("*.py"):
        if forbidden_global_rng.search(path.read_text(encoding="utf-8")):
            violations.append(str(path.relative_to(ROOT)))
    assert not violations, f"NumPy global RNG use found in: {violations}"
