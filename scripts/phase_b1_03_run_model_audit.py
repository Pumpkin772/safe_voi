"""Aggregate exact-vs-ARX and nonlinear constraint-activation evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from d5freq.evaluation.phase_b1_analysis import collect_final_evidence
from d5freq.evaluation.phase_b1_experiments import build_final_core_plan
from d5freq.evaluation.phase_b1_protocol import PhaseB1Paths


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", type=Path, default=Path.cwd())
    return result


def main() -> int:
    arguments = parser().parse_args()
    paths = PhaseB1Paths.from_repo(arguments.repo_root)
    _, audits, _, failures = collect_final_evidence(paths, (build_final_core_plan(paths),))
    destination = paths.results_root / "tables"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("closed_loop_prediction_error", "constraint_activation"):
        audits[name].to_csv(destination / f"{name}.csv", index=False, lineterminator="\n")
    failures.to_csv(destination / "compact_audit_failures.csv", index=False, lineterminator="\n")
    print(
        f"model audit rows: prediction={len(audits['closed_loop_prediction_error'])} "
        f"constraints={len(audits['constraint_activation'])} failures={len(failures)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
