"""Standard-library integrity verification for the extracted closure package."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "17_GIT_MANIFEST"
EXPECTED_DIRS = {f"{i:02d}_{name}" for i, name in enumerate((
    "README", "AUDIT", "SCIENCE", "LITERATURE", "MODEL_METHOD", "VALIDATION",
    "CONFIRMATORY", "MECHANISM_ANALYSIS", "THEORY", "SOURCE_ENV", "TESTS",
    "RAW_RESULTS", "SUMMARY_TABLES", "FIGURES", "FAILURES", "PAPER_DRAFT",
    "REPRODUCIBILITY", "GIT_MANIFEST", "FINAL_STATUS",
))}
EXCLUDED = {
    "17_GIT_MANIFEST/MANIFEST_SHA256.csv",
    "17_GIT_MANIFEST/MANIFEST_SHA256.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    actual_dirs = {path.name for path in ROOT.iterdir() if path.is_dir()}
    directory_match = actual_dirs == EXPECTED_DIRS
    with (MANIFEST_DIR / "MANIFEST_SHA256.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected_paths = {row["path"] for row in rows}
    actual_paths = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file() and path.relative_to(ROOT).as_posix() not in EXCLUDED
    }
    differences = []
    for row in rows:
        path = ROOT / row["path"]
        exists = path.is_file()
        size_ok = exists and path.stat().st_size == int(row["bytes"])
        hash_ok = size_ok and sha256(path) == row["sha256"]
        if not hash_ok:
            differences.append({"path": row["path"], "exists": exists, "size_ok": size_ok, "hash_ok": hash_ok})
    final = json.loads((ROOT / "18_FINAL_STATUS/FINAL_STATUS.json").read_text(encoding="utf-8"))
    result = {
        "schema": "direction5.closure.package_manifest_verification.v1",
        "package_root": ROOT.name,
        "directory_match": directory_match,
        "manifest_files": len(rows),
        "missing_from_manifest": sorted(actual_paths - expected_paths),
        "missing_from_package": sorted(expected_paths - actual_paths),
        "differences": differences,
        "final_status": final["final_status"],
    }
    result["passed"] = bool(
        directory_match
        and not result["missing_from_manifest"]
        and not result["missing_from_package"]
        and not differences
        and final["final_status"] in {
            "DIRECTION5_NEGATIVE_RESULT_CONFIRMED_AND_ARCHIVED",
            "DIRECTION5_BOUNDED_POSITIVE_RESULT_CONFIRMED",
        }
    )
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
