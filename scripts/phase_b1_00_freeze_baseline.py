"""Freeze and later verify the immutable Phase-A evidence used by Phase B1.

This utility only reads the legacy ``artifacts/``, ``results/`` and ``figures/``
trees.  Its sole output is the Phase-B1 manifest named on the command line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


EXPECTED_REVIEW_ZIP_SHA256 = (
    "2e1c3bfc380c57172a5d96663a6ab90cf95b79511f60cefce73ce4c38e2f04a9"
)
EXPECTED_FROZEN_COMMIT = "20f652f5f8b180a2518798d0ed85aa3f48212908"
EXPECTED_TAG = "phase-a-final-reviewed-v2"
EXPECTED_BRANCH = "phase-b1-bottleneck-audit"
REVIEW_ZIP = "D5_FROM_SCRATCH_SD_BMPC_REVIEW_PACKAGE.zip"
LEGACY_ROOTS = ("artifacts", "results", "figures")


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _scan_tree(repo: Path, root_name: str) -> dict[str, Any]:
    root = repo / root_name
    if not root.exists():
        return {
            "root": root_name,
            "present": False,
            "file_count": 0,
            "total_bytes": 0,
            "logical_sha256": hashlib.sha256(b"").hexdigest(),
            "files": [],
        }

    files: list[dict[str, Any]] = []
    logical_digest = hashlib.sha256()
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda p: p.as_posix()):
        relative = path.relative_to(repo).as_posix()
        size = path.stat().st_size
        file_hash = _sha256(path)
        logical_digest.update(f"{relative}\0{size}\0{file_hash}\n".encode("utf-8"))
        files.append({"path": relative, "size_bytes": size, "sha256": file_hash})
    return {
        "root": root_name,
        "present": True,
        "file_count": len(files),
        "total_bytes": sum(item["size_bytes"] for item in files),
        "logical_sha256": logical_digest.hexdigest(),
        "files": files,
    }


def _review_package_evidence(repo: Path) -> dict[str, Any]:
    path = repo / REVIEW_ZIP
    package_sha = _sha256(path)
    if package_sha != EXPECTED_REVIEW_ZIP_SHA256:
        raise RuntimeError(
            f"review ZIP SHA256 mismatch: expected {EXPECTED_REVIEW_ZIP_SHA256}, got {package_sha}"
        )
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        commit_name = next((name for name in names if name.endswith("git/commit.txt")), None)
        diff_name = next((name for name in names if name.endswith("git/diff.patch")), None)
        status_name = next((name for name in names if name.endswith("git/status.txt")), None)
        if not commit_name or not diff_name or not status_name:
            raise RuntimeError("review ZIP is missing git/commit.txt, git/diff.patch or git/status.txt")
        archived_commit = archive.read(commit_name).decode("utf-8").strip()
        diff_bytes = archive.read(diff_name)
        status_bytes = archive.read(status_name)
    if archived_commit != EXPECTED_FROZEN_COMMIT:
        raise RuntimeError(
            f"review ZIP commit mismatch: expected {EXPECTED_FROZEN_COMMIT}, got {archived_commit}"
        )
    return {
        "path": REVIEW_ZIP,
        "size_bytes": path.stat().st_size,
        "sha256": package_sha,
        "archived_frozen_commit": archived_commit,
        "archived_diff_sha256": hashlib.sha256(diff_bytes).hexdigest(),
        "archived_status_sha256": hashlib.sha256(status_bytes).hexdigest(),
    }


def _git_evidence(repo: Path) -> dict[str, Any]:
    baseline_commit = _git(repo, "rev-list", "-n", "1", EXPECTED_TAG)
    parent = _git(repo, "rev-parse", f"{baseline_commit}^")
    if parent != EXPECTED_FROZEN_COMMIT:
        raise RuntimeError(
            f"baseline parent mismatch: expected {EXPECTED_FROZEN_COMMIT}, got {parent}"
        )
    if _git(repo, "cat-file", "-t", EXPECTED_TAG) != "tag":
        raise RuntimeError(f"{EXPECTED_TAG} is not an annotated tag")
    branch_commit = _git(repo, "rev-parse", EXPECTED_BRANCH)
    merge_base = _git(repo, "merge-base", baseline_commit, branch_commit)
    if merge_base != baseline_commit:
        raise RuntimeError(f"{EXPECTED_BRANCH} does not descend from {EXPECTED_TAG}")
    return {
        "frozen_phase6_commit": EXPECTED_FROZEN_COMMIT,
        "phase_a_baseline_commit": baseline_commit,
        "phase_a_baseline_parent": parent,
        "annotated_tag": EXPECTED_TAG,
        "phase_b1_branch": EXPECTED_BRANCH,
        "phase_b1_branch_commit_at_capture": branch_commit,
    }


def _test_evidence(repo: Path) -> dict[str, Any]:
    text_path = repo / "logs_phase_b1" / "pytest_baseline.txt"
    xml_path = repo / "logs_phase_b1" / "pytest_baseline.xml"
    root = ElementTree.parse(xml_path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        raise RuntimeError("cannot parse baseline pytest XML")
    result = {
        "tests": int(suite.attrib.get("tests", "0")),
        "failures": int(suite.attrib.get("failures", "0")),
        "errors": int(suite.attrib.get("errors", "0")),
        "skipped": int(suite.attrib.get("skipped", "0")),
        "time_seconds": float(suite.attrib.get("time", "nan")),
    }
    if result["tests"] != 609 or any(result[key] for key in ("failures", "errors", "skipped")):
        raise RuntimeError(f"unexpected baseline test result: {result}")
    result["files"] = [
        {
            "path": path.relative_to(repo).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in (text_path, xml_path)
    ]
    return result


def build_manifest(repo: Path) -> dict[str, Any]:
    trees = [_scan_tree(repo, name) for name in LEGACY_ROOTS]
    return {
        "schema_version": "phase-b1-baseline-manifest-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "immutability_contract": {
            "legacy_roots": list(LEGACY_ROOTS),
            "rule": "read-only throughout Phase B1; all new evidence uses *_phase_b1 roots",
        },
        "review_package": _review_package_evidence(repo),
        "git": _git_evidence(repo),
        "baseline_tests": _test_evidence(repo),
        "legacy_trees": trees,
        "legacy_totals": {
            "file_count": sum(tree["file_count"] for tree in trees),
            "total_bytes": sum(tree["total_bytes"] for tree in trees),
        },
    }


def verify_manifest(repo: Path, expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        current_package = _review_package_evidence(repo)
        current_git = _git_evidence(repo)
        current_tests = _test_evidence(repo)
    except Exception as exc:  # keep verification output actionable
        return [str(exc)]
    for section_name, current in (
        ("review_package", current_package),
        ("git", current_git),
        ("baseline_tests", current_tests),
    ):
        reference = expected[section_name]
        for key, value in reference.items():
            if key in {"phase_b1_branch_commit_at_capture", "time_seconds"}:
                continue
            if current.get(key) != value:
                errors.append(f"{section_name}.{key}: expected {value!r}, got {current.get(key)!r}")

    expected_trees = {tree["root"]: tree for tree in expected["legacy_trees"]}
    for root_name in LEGACY_ROOTS:
        current = _scan_tree(repo, root_name)
        reference = expected_trees[root_name]
        for key in ("present", "file_count", "total_bytes", "logical_sha256", "files"):
            if current[key] != reference[key]:
                errors.append(f"legacy tree {root_name!r} changed ({key})")
                break
    return errors


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts_phase_b1/baseline_manifest.json"),
    )
    parser.add_argument("--verify", action="store_true", help="verify an existing manifest")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo = args.repo.resolve()
    output = args.output if args.output.is_absolute() else repo / args.output
    if args.verify:
        with output.open("r", encoding="utf-8") as handle:
            expected = json.load(handle)
        errors = verify_manifest(repo, expected)
        if errors:
            print("BASELINE VERIFICATION FAILED", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        print("BASELINE VERIFICATION PASSED")
        return 0

    manifest = build_manifest(repo)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    totals = manifest["legacy_totals"]
    print(
        f"Wrote {output}: {totals['file_count']} files, "
        f"{totals['total_bytes']} bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
