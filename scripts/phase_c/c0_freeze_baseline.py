"""Freeze and inventory the Phase B2 baseline without modifying its evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any
import zipfile

from d5freq.utils.environment import collect_environment_info, write_environment_info


REPO = Path(__file__).resolve().parents[2]
LAUNCH_ROOT = REPO / "research" / "phase_c_full_rebuild_and_method_completion"
B2_ZIP = REPO / "D5_PHASE_B2_SCIENTIFIC_HARDENING_REVIEW_PACKAGE.zip"
B2_SHA256 = "5280a39e97a99f0bd831d0d5d2f72c7faae6b04b45e5e8fcf5b644325c9b1ebe"
B2_COMMIT = "5953ffcf71a641581364e0684b982852def4421c"
B2_TAG = "direction5-phase-b2-reviewed-invalidated"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPO,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def verify_launch_package() -> list[dict[str, Any]]:
    index = json.loads((LAUNCH_ROOT / "PACKAGE_INDEX.json").read_text(encoding="utf-8"))
    for row in index:
        path = LAUNCH_ROOT / row["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != row["size_bytes"] or sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"launch-package integrity failure: {row['path']}")
    return index


def source_inventory(destination: Path) -> int:
    excluded_parts = {".git", "__pycache__", ".pytest_cache", ".pytest_tmp"}
    rows: list[tuple[str, int, str]] = []
    for path in sorted(REPO.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or any(part in excluded_parts for part in path.parts):
            continue
        if path.suffix.lower() in {".pyc", ".pyo", ".lic"}:
            continue
        rows.append((path.relative_to(REPO).as_posix(), path.stat().st_size, sha256_file(path)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("path", "size_bytes", "sha256"))
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    if sha256_file(B2_ZIP) != B2_SHA256:
        raise RuntimeError("frozen Phase B2 ZIP SHA256 mismatch")
    with zipfile.ZipFile(B2_ZIP) as archive:
        corrupt = archive.testzip()
        if corrupt is not None:
            raise RuntimeError(f"frozen Phase B2 ZIP CRC failure at {corrupt}")
        b2_member_count = len(archive.namelist())
    launch_index = verify_launch_package()
    tag_target = git("rev-parse", f"{B2_TAG}^{{}}")
    if tag_target != B2_COMMIT:
        raise RuntimeError(f"{B2_TAG} does not point to the frozen B2 commit")

    artifact_root = REPO / "artifacts_phase_c" / "baseline"
    log_root = REPO / "logs_phase_c" / "C0"
    inventory_count = source_inventory(artifact_root / "source_inventory.csv")
    environment = collect_environment_info(
        package_names=(
            "numpy", "scipy", "pandas", "pyarrow", "matplotlib", "scikit-learn",
            "PyYAML", "cvxpy", "casadi", "control", "pytest", "pytest-cov",
            "Mosek", "gurobipy", "andes",
        ),
        extra={
            "phase": "C0",
            "b2_conclusion_withdrawn": True,
            "license_paths_or_values_exported": False,
            "processor": platform.processor(),
            "python_prefix_exported": False,
        },
    )
    write_environment_info(artifact_root / "environment.json", environment)
    payload = {
        "schema_version": "d5freq.phase_c.c0_baseline.v1",
        "phase_b2": {
            "commit": B2_COMMIT,
            "tag": B2_TAG,
            "zip_sha256": B2_SHA256,
            "zip_size_bytes": B2_ZIP.stat().st_size,
            "zip_member_count": b2_member_count,
            "zip_crc_verified": True,
            "scientific_decision_withdrawn": "PROBLEM_NOT_MATERIAL",
            "evidence_retention": "read_only",
        },
        "phase_c": {
            "branch": git("branch", "--show-current"),
            "launch_package_entries_verified": len(launch_index),
            "launch_package_mismatches": 0,
            "source_inventory_file_count": inventory_count,
            "source_baseline_complete": True,
        },
    }
    write_json(artifact_root / "baseline_freeze.json", payload)
    write_json(log_root / "baseline_verification.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
