"""Verify every payload file in an extracted Direction5 Phase-I package."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "16_GIT_MANIFEST/MANIFEST.csv"
EXCLUDED = {
    "16_GIT_MANIFEST/MANIFEST.csv",
    "16_GIT_MANIFEST/MANIFEST.json",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if not MANIFEST.is_file():
        raise SystemExit(f"manifest missing: {MANIFEST}")
    with MANIFEST.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = {row["path"] for row in rows}
    actual = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file() and path.relative_to(ROOT).as_posix() not in EXCLUDED
    }
    if expected != actual:
        raise SystemExit(
            f"manifest path mismatch missing={sorted(expected - actual)} "
            f"extra={sorted(actual - expected)}"
        )
    for row in rows:
        path = ROOT / row["path"]
        if path.stat().st_size != int(row["bytes"]):
            raise SystemExit(f"size mismatch: {row['path']}")
        if sha256(path) != row["sha256"]:
            raise SystemExit(f"sha256 mismatch: {row['path']}")
    print(f"DIRECTION5_PHASE_I_MANIFEST_OK files={len(rows)}")


if __name__ == "__main__":
    main()
