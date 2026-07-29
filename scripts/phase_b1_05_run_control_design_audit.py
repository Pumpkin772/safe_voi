"""Run the locked P_old/C0--C5 control-design decomposition matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from d5freq.evaluation.phase_b1_analysis import (
    build_control_decomposition_table,
    collect_final_evidence,
)
from d5freq.evaluation.phase_b1_execution import execute_final_plan
from d5freq.evaluation.phase_b1_experiments import (
    build_final_control_plan,
    build_final_core_plan,
)
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
        matrix_id="control_design_decomposition",
        plan=build_final_control_plan(paths),
        max_workers=arguments.max_workers,
    )
    episodes, _, _, _ = collect_final_evidence(
        paths, (build_final_core_plan(paths), build_final_control_plan(paths))
    )
    destination = paths.results_root / "tables"
    destination.mkdir(parents=True, exist_ok=True)
    build_control_decomposition_table(episodes).to_csv(
        destination / "control_design_decomposition.csv",
        index=False,
        lineterminator="\n",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
