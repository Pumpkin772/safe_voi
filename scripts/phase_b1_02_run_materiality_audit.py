"""Run the locked Phase-B1 B0/B2/B4/B5 final matrix exactly once."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from d5freq.evaluation.phase_b1_execution import execute_final_plan
from d5freq.evaluation.phase_b1_experiments import build_final_core_plan
from d5freq.evaluation.phase_b1_protocol import PhaseB1Paths


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", type=Path, default=Path.cwd())
    result.add_argument("--max-workers", type=int, default=4)
    return result


def main() -> int:
    arguments = parser().parse_args()
    paths = PhaseB1Paths.from_repo(arguments.repo_root)
    summary = execute_final_plan(
        paths,
        matrix_id="materiality_and_model",
        plan=build_final_core_plan(paths),
        max_workers=arguments.max_workers,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
