"""Verify every byte in a freshly extracted Direction5 review package."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "16_GIT_MANIFEST/MANIFEST_SHA256.csv"
MANIFEST_FILES = {
    "16_GIT_MANIFEST/MANIFEST_SHA256.csv",
    "16_GIT_MANIFEST/MANIFEST_SHA256.json",
}


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> None:
    if not MANIFEST.is_file():
        raise SystemExit(f"missing manifest: {MANIFEST}")
    with MANIFEST.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = {row["path"] for row in rows}
    actual = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
    } - MANIFEST_FILES
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    mismatches: list[dict[str, object]] = []
    for row in rows:
        path = ROOT / row["path"]
        if not path.is_file():
            continue
        size = path.stat().st_size
        checksum = digest(path)
        if size != int(row["bytes"]) or checksum != row["sha256"]:
            mismatches.append({
                "path": row["path"],
                "expected_bytes": int(row["bytes"]),
                "actual_bytes": size,
                "expected_sha256": row["sha256"],
                "actual_sha256": checksum,
            })
    result = {
        "schema": "direction5.final_repair.manifest_verification.v1",
        "package_root": str(ROOT),
        "manifest_files": len(rows),
        "missing": missing,
        "unexpected": unexpected,
        "mismatches": mismatches,
        "passed": not missing and not unexpected and not mismatches,
    }
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
