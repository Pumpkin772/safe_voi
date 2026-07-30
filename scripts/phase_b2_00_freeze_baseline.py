"""Freeze or verify the immutable Phase-B1 baseline consumed by Phase B2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from d5freq.evaluation.phase_b2_baseline import (
    verify_phase_b1_baseline_manifest,
    write_phase_b1_baseline_manifest,
)
from d5freq.evaluation.phase_b2_protocol import PhaseB2Paths
from d5freq.utils.hashing import sha256_file


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", type=Path, default=Path("."))
    result.add_argument("--verify", action="store_true")
    return result


def main() -> int:
    arguments = parser().parse_args()
    paths = PhaseB2Paths.from_repo(arguments.repo_root)
    if arguments.verify:
        payload = verify_phase_b1_baseline_manifest(paths)
        status = "verified"
    else:
        destination = write_phase_b1_baseline_manifest(paths)
        payload = json.loads(destination.read_text(encoding="utf-8"))
        status = "created"
    print(
        json.dumps(
            {
                "status": status,
                "path": str(paths.baseline_manifest),
                "sha256": sha256_file(paths.baseline_manifest),
                "phase_b1_commit": payload["phase_b1_commit"],
                "file_count": payload["file_count"],
                "total_size_bytes": payload["total_size_bytes"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
