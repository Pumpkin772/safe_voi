"""Build and verify the final Phase-B1 bottleneck-audit review ZIP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from d5freq.evaluation.phase_b1_package import build_review_package
from d5freq.evaluation.phase_b1_protocol import PhaseB1Paths
from d5freq.utils.hashing import sha256_file


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", type=Path, default=Path.cwd())
    return result


def main() -> int:
    arguments = parser().parse_args()
    destination = build_review_package(PhaseB1Paths.from_repo(arguments.repo_root))
    print(
        json.dumps(
            {
                "path": str(destination),
                "size_bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
