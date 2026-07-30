"""Verify a package manifest from the extracted review-package root."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    root = Path.cwd()
    manifest = root / "15_GIT_AND_MANIFEST" / "FILE_MANIFEST.csv"
    failures = []
    with manifest.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            path = root / row["path"]
            if not path.is_file() or path.stat().st_size != int(row["bytes"]) or sha256(path) != row["sha256"]:
                failures.append(row["path"])
    if failures:
        raise SystemExit(f"manifest failures: {failures}")
    print("manifest PASS")


if __name__ == "__main__":
    main()
