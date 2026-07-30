"""Freeze and verify every Phase-B1 input consumed by Phase B2."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from d5freq.evaluation.phase_b2_protocol import PhaseB2Paths
from d5freq.utils.hashing import sha256_file, sha256_json


PHASE_B1_ROOTS = (
    "artifacts_phase_b1",
    "results_phase_b1",
    "figures_phase_b1",
    "logs_phase_b1",
    "progress_phase_b1",
)


def _git(paths: PhaseB2Paths, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=paths.repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _included_files(paths: PhaseB2Paths) -> list[Path]:
    files: set[Path] = set()
    for relative in PHASE_B1_ROOTS:
        root = paths.repo_root / relative
        if not root.is_dir():
            raise FileNotFoundError(root)
        files.update(path for path in root.rglob("*") if path.is_file())
    patterns = (
        "configs/phase_b1*.yaml",
        "scripts/phase_b1*.py",
        "src/d5freq/evaluation/phase_b1*.py",
        "tests_phase_b1/*.py",
    )
    for pattern in patterns:
        files.update(path for path in paths.repo_root.glob(pattern) if path.is_file())
    files.add(paths.phase_b1_review_zip)
    return sorted(files, key=lambda path: path.relative_to(paths.repo_root).as_posix())


def build_phase_b1_baseline_manifest(paths: PhaseB2Paths) -> dict[str, Any]:
    config = paths.load_config()["phase_b1_baseline"]
    assert isinstance(config, dict)
    expected_commit = str(config["commit"])
    branch_commit = _git(paths, "rev-parse", "phase-b1-bottleneck-audit")
    if branch_commit != expected_commit:
        raise RuntimeError("Phase-B1 branch no longer points at the frozen commit")
    expected_zip_sha = str(config["review_zip_sha256"])
    actual_zip_sha = sha256_file(paths.phase_b1_review_zip)
    if actual_zip_sha != expected_zip_sha:
        raise RuntimeError("Phase-B1 review ZIP hash mismatch")
    records = []
    for path in _included_files(paths):
        relative = path.relative_to(paths.repo_root).as_posix()
        records.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    decision_path = paths.phase_b1_tables / "bottleneck_decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    return {
        "schema_version": "d5freq.phase_b2.phase_b1_baseline_manifest.v1",
        "phase_b1_commit": expected_commit,
        "phase_b1_branch_commit": branch_commit,
        "phase_b1_review_zip_sha256": actual_zip_sha,
        "phase_b1_original_decision": decision,
        "file_count": len(records),
        "total_size_bytes": sum(record["size_bytes"] for record in records),
        "files_sha256": sha256_json(records),
        "files": records,
    }


def write_phase_b1_baseline_manifest(paths: PhaseB2Paths) -> Path:
    payload = build_phase_b1_baseline_manifest(paths)
    paths.baseline_manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.baseline_manifest.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return paths.baseline_manifest


def verify_phase_b1_baseline_manifest(paths: PhaseB2Paths) -> dict[str, Any]:
    if not paths.baseline_manifest.is_file():
        raise FileNotFoundError(paths.baseline_manifest)
    recorded = json.loads(paths.baseline_manifest.read_text(encoding="utf-8"))
    current = build_phase_b1_baseline_manifest(paths)
    if recorded != current:
        raise RuntimeError("Phase-B1 baseline changed after Phase-B2 freeze")
    return current


__all__ = [
    "PHASE_B1_ROOTS",
    "build_phase_b1_baseline_manifest",
    "verify_phase_b1_baseline_manifest",
    "write_phase_b1_baseline_manifest",
]
