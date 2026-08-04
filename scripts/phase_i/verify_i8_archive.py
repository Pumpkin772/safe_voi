"""Verify a Phase-I archive in a genuinely fresh temporary extraction."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


REPO = Path(__file__).resolve().parents[2]
EXPECTED_ROOT = "DIRECTION5_PHASE_I_FINAL_CONVERGENCE_SINGLE_REVIEW_PACKAGE"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    with tempfile.TemporaryDirectory(prefix="direction5_i8_fresh_") as temporary:
        extraction = Path(temporary)
        with zipfile.ZipFile(archive) as handle:
            bad = handle.testzip()
            if bad:
                raise RuntimeError(f"ZIP CRC failed: {bad}")
            handle.extractall(extraction)
        root = extraction / EXPECTED_ROOT
        if not root.is_dir():
            raise RuntimeError(f"expected single package root missing: {root}")
        manifest = subprocess.run(
            [sys.executable, "15_REPRODUCIBILITY/verify_manifest.py"], cwd=root,
            text=True, capture_output=True, check=False,
        )
        minimal = subprocess.run(
            [sys.executable, "15_REPRODUCIBILITY/reproduce_minimal.py"], cwd=root,
            text=True, capture_output=True, check=False,
        )
        result = {
            "schema": "direction5.phase_i.fresh_extract_verification.v1",
            "archive": str(archive), "bytes": archive.stat().st_size, "sha256": sha256(archive),
            "fresh_extract": True, "crc_ok": True,
            "manifest_ok": manifest.returncode == 0 and "DIRECTION5_PHASE_I_MANIFEST_OK" in manifest.stdout,
            "minimal_replay_ok": minimal.returncode == 0 and "DIRECTION5_PHASE_I_MINIMAL_REPLAY_OK" in minimal.stdout,
            "manifest_stdout": manifest.stdout, "manifest_stderr": manifest.stderr,
            "minimal_stdout": minimal.stdout, "minimal_stderr": minimal.stderr,
        }
    args.record.parent.mkdir(parents=True, exist_ok=True)
    args.record.write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    print(json.dumps(result, indent=2))
    if not all((result["crc_ok"], result["manifest_ok"], result["minimal_replay_ok"])):
        raise SystemExit("fresh-extract verification failed")


if __name__ == "__main__":
    main()
