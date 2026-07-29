"""Run the locked passive closed-loop P_old identifiability matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from d5freq.evaluation.phase_b1_analysis import collect_final_evidence
from d5freq.evaluation.phase_b1_execution import execute_final_plan
from d5freq.evaluation.phase_b1_experiments import build_final_control_plan
from d5freq.evaluation.phase_b1_protocol import PhaseB1Paths


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", type=Path, default=Path.cwd())
    result.add_argument("--max-workers", type=int, default=4)
    return result


def main() -> int:
    arguments = parser().parse_args()
    paths = PhaseB1Paths.from_repo(arguments.repo_root)
    plan = tuple(
        spec for spec in build_final_control_plan(paths) if spec.method_id == "P_old"
    )
    summary = execute_final_plan(
        paths,
        matrix_id="passive_identifiability",
        plan=plan,
        max_workers=arguments.max_workers,
    )
    _, audits, _, failures = collect_final_evidence(paths, (plan,))
    destination = paths.results_root / "tables"
    destination.mkdir(parents=True, exist_ok=True)
    for name in (
        "information_gramian",
        "pairwise_separation",
        "identifiability_delay",
        "source_confusion",
    ):
        audits[name].to_csv(destination / f"{name}.csv", index=False, lineterminator="\n")
    failures.to_csv(
        destination / "identifiability_audit_failures.csv",
        index=False,
        lineterminator="\n",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
