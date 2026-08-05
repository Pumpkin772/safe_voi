"""Standard-library scientific replay for the Direction5 closure package."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NEGATIVE = "DIRECTION5_NEGATIVE_RESULT_CONFIRMED_AND_ARCHIVED"


def read_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def read_csv(path: str) -> list[dict[str, str]]:
    with (ROOT / path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def as_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def main() -> None:
    final = read_json("18_FINAL_STATUS/FINAL_STATUS.json")
    c0 = read_json("18_FINAL_STATUS/progress_closure/C0.json")
    c1 = read_json("18_FINAL_STATUS/progress_closure/C1.json")
    c2 = read_json("18_FINAL_STATUS/progress_closure/C2.json")
    c6 = read_json("18_FINAL_STATUS/progress_closure/C6.json")
    validation = read_json("05_VALIDATION/R5_SUMMARY.json")
    confirm = read_json("06_CONFIRMATORY/C2_SUMMARY.json")
    seed_marker = read_json("06_CONFIRMATORY/FINAL_SEEDS_CONSUMED.json")
    vmetrics = [row for row in read_csv("05_VALIDATION/CORE_METRIC_GATES.csv") if row["analysis"] == "both_success"]
    cmetrics = [row for row in read_csv("06_CONFIRMATORY/FINAL_CORE_METRIC_GATES.csv") if row["analysis"] == "both_success"]
    denom = {row["quantity"]: int(row["count"]) for row in read_csv("06_CONFIRMATORY/FINAL_SOLVER_DENOMINATOR.csv")}
    decision_identity = (
        denom["primary_accepted_actions"]
        + denom["restoration_accepted_actions"]
        + denom["backup_actions"]
        + denom["unhandled_actions"]
        == denom["attempted_optimization_decisions"]
    )
    invocation_identity = (
        denom["attempted_optimization_decisions"]
        + denom["restoration_accepted_actions"]
        + denom["backup_actions"]
        == denom["raw_solver_invocations"]
    )
    stage_gates = {row["stage"]: row["status"] for row in read_csv("18_FINAL_STATUS/ALL_STAGE_GATES.csv")}
    facts = {
        "final_status": final["final_status"],
        "c0_manifest_verified": c0["manifest_verified"],
        "c0_statistics_exact": [c0["statistics_within_tolerance"], c0["statistics_comparisons"]],
        "c1_explained_fraction": [c1["fallback_explained_fraction"], c1["performance_rows_explained_fraction"]],
        "validation_core_metrics_passing": validation["core_metrics_passing"],
        "confirmatory_core_metrics_passing": confirm["core_metrics_passing"],
        "validation_positive": final["validation_positive_gate"],
        "confirmatory_positive": final["confirmatory_positive_gate"],
        "joint_positive": final["joint_validation_confirmatory_positive"],
        "validation_primary_passes": sum(as_bool(row["passes"]) for row in vmetrics),
        "confirmatory_primary_passes": sum(as_bool(row["passes"]) for row in cmetrics),
        "final_seeds_consumed": seed_marker["final_seeds_consumed"],
        "single_execution": seed_marker["single_execution"],
        "post_result_tuning_permitted": confirm["post_result_tuning_permitted"],
        "attempted_optimization_decisions": denom["attempted_optimization_decisions"],
        "raw_solver_invocations": denom["raw_solver_invocations"],
        "decision_identity": decision_identity,
        "raw_invocation_identity": invocation_identity,
        "c0_to_c5_stage_pass": all(stage_gates.get(f"C{i}") == "PASS" for i in range(6)),
        "c6_status": c6["status"],
    }
    expected = {
        "final_status": NEGATIVE,
        "c0_manifest_verified": True,
        "c0_statistics_exact": [262, 262],
        "c1_explained_fraction": [1.0, 1.0],
        "validation_core_metrics_passing": 0,
        "confirmatory_core_metrics_passing": 0,
        "validation_positive": False,
        "confirmatory_positive": False,
        "joint_positive": False,
        "validation_primary_passes": 0,
        "confirmatory_primary_passes": 0,
        "final_seeds_consumed": True,
        "single_execution": True,
        "post_result_tuning_permitted": False,
        "attempted_optimization_decisions": 20227,
        "raw_solver_invocations": 21400,
        "decision_identity": True,
        "raw_invocation_identity": True,
        "c0_to_c5_stage_pass": True,
    }
    passed = all(facts[key] == value for key, value in expected.items()) and facts["c6_status"] in {"PENDING_PACKAGE_VERIFICATION", "PASS"}
    print(json.dumps({"schema": "direction5.closure.minimal_replay.v1", "facts": facts, "expected": expected, "passed": passed}, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
