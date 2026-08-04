"""Replay the decisive Direction5 final-repair facts using packaged evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def load_csv(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    final = load_json("17_FINAL_STATUS/FINAL_STATUS.json")
    r5 = load_json("10_RAW_RESULTS/progress_final/R5.json")
    r6 = load_json("10_RAW_RESULTS/progress_final/R6.json")
    r7 = load_json("10_RAW_RESULTS/progress_final/R7.json")
    metrics = load_csv("11_SUMMARY_TABLES/R5/CORE_METRIC_GATES.csv")
    solver = load_csv("11_SUMMARY_TABLES/R5/SOLVER_DENOMINATOR.csv")
    hypotheses = load_csv("17_FINAL_STATUS/HYPOTHESES_H1_H6.csv")

    counts = {row["quantity"]: int(row["count"]) for row in solver}
    decision_identity = (
        counts["attempted_optimization_decisions"]
        == counts["primary_accepted_actions"]
        + counts["restoration_accepted_actions"]
        + counts["backup_actions"]
        + counts["unhandled_actions"]
    )
    invocation_identity = (
        counts["raw_solver_invocations"]
        == counts["attempted_optimization_decisions"]
        + counts["restoration_accepted_actions"]
        + counts["backup_actions"]
    )
    facts = {
        "final_status": final["final_status"],
        "r5": r5["status"],
        "r6": r6["status"],
        "r7": r7["status"],
        "final_seeds_consumed": r5["final_seeds_consumed"],
        "core_metrics_passing": sum(row["passes"].lower() == "true" for row in metrics),
        "attempted_optimization_decisions": counts["attempted_optimization_decisions"],
        "raw_solver_invocations": counts["raw_solver_invocations"],
        "decision_identity": decision_identity,
        "raw_invocation_identity": invocation_identity,
        "h5": next(row["status"] for row in hypotheses if row["hypothesis"] == "H5"),
        "r8": final["R0_R8"]["R8"],
    }
    expected = {
        "final_status": "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE",
        "r5": "FAIL",
        "r6": "NOT_EVALUATED",
        "r7": "NOT_EVALUATED",
        "final_seeds_consumed": False,
        "core_metrics_passing": 0,
        "attempted_optimization_decisions": 20271,
        "raw_solver_invocations": 21293,
        "decision_identity": True,
        "raw_invocation_identity": True,
        "h5": "NOT_SUPPORTED",
        "r8": "PASS",
    }
    result = {
        "schema": "direction5.final_repair.minimal_replay.v1",
        "facts": facts,
        "expected": expected,
        "passed": facts == expected,
    }
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
