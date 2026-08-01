"""Verify a Phase-F review package from its extracted root."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    manifest = ROOT / "16_GIT_MANIFEST" / "MANIFEST.sha256.csv"
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    with manifest.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        path = ROOT / row["path"]
        assert path.is_file(), row["path"]
        assert path.stat().st_size == int(row["bytes"]), row["path"]
        assert sha256(path) == row["sha256"], row["path"]
    print(f"verified {len(rows)} package files")


if __name__ == "__main__":
    main()
