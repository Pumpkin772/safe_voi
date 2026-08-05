"""Post-run independent audit of the immutable C2 confirmatory evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.direction5_closure.run_c0_audit import (
    B_METHOD,
    METRICS,
    P_METHOD,
    bootstrap,
    failure_table,
    metric_pairs,
    paired_wide,
)
from scripts.direction5_closure.run_c2_confirmatory import (
    CONFIG,
    LOCK,
    MANIFEST_DIR,
    R5_LOCK,
    file_sha,
    tree_sha,
)


EVIDENCE = REPO / "research_outputs_closure/02_CONFIRMATORY"
RESULTS = REPO / "results_closure/C2"
OUT = REPO / "research_outputs_closure/02_CONFIRMATORY/AUDIT"


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def close(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= 1e-11 * max(1.0, abs(float(right)))


def independently_verify_lock() -> dict:
    lock = json.loads(LOCK.read_text("utf-8"))
    goal_candidates = (
        REPO / "research/direction5_closure_confirmation_and_manuscript/CODEX_GOAL.md",
        REPO / "research/DIRECTION5_CLOSURE_CONFIRMATION_AND_MANUSCRIPT_CODEX_PACKAGE/CODEX_GOAL.md",
    )
    goal = next((path for path in goal_candidates if path.is_file()), None)
    if goal is None:
        raise RuntimeError("locked closure Goal is missing")
    actual = {
        "method_source_sha256": tree_sha([
            REPO / "src/direction5freq",
            REPO / "scripts/direction5_final/run_r5_validation.py",
            R5_LOCK,
        ]),
        "execution_source_sha256": file_sha(
            REPO / "scripts/direction5_closure/run_c2_confirmatory.py"
        ),
        "statistics_source_sha256": file_sha(
            REPO / "src/direction5freq/evaluation/corrected_statistics.py"
        ),
        "protocol_sha256": file_sha(CONFIG),
        "r5_lock_sha256": file_sha(R5_LOCK),
        "manifest_sha256": file_sha(MANIFEST_DIR / "FINAL_MANIFEST.csv"),
        "goal_sha256": file_sha(goal),
    }
    mismatches = {
        key: {"locked": lock[key], "actual": value}
        for key, value in actual.items() if lock[key] != value
    }
    return {"passed": not mismatches, "goal_path": str(goal), "mismatches": mismatches}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lock_audit = independently_verify_lock()
    marker = json.loads((RESULTS / "FINAL_SEEDS_CONSUMED.json").read_text("utf-8"))
    summary = json.loads((RESULTS / "C2_SUMMARY.json").read_text("utf-8"))
    episodes = pd.read_parquet(EVIDENCE / "FINAL_EPISODES.parquet")
    cycles = pd.read_parquet(EVIDENCE / "FINAL_CYCLES.parquet")
    core = episodes[episodes.dataset_kind.isin(("plant_a_primary", "plant_b"))].copy()
    wide = paired_wide(core)
    failures = failure_table(wide)
    packaged_failures = pd.read_csv(EVIDENCE / "FINAL_PAIRED_FAILURES.csv")
    failure_match = failures.equals(packaged_failures)

    package_metrics = pd.read_csv(EVIDENCE / "FINAL_CORE_METRIC_GATES.csv")
    comparisons = []
    for metric_index, metric in enumerate(METRICS):
        pairs = metric_pairs(wide, metric, "both_success")
        means = pairs.groupby("design_cell")[["proposed_value", "baseline_value"]].mean().mean()
        p_mean = float(means.proposed_value)
        b_mean = float(means.baseline_value)
        difference = b_mean - p_mean
        relative = difference / max(abs(b_mean), 1e-12)
        interval = bootstrap(pairs, 3000, 20260805 + 100 * metric_index)
        expected = package_metrics[package_metrics.metric.eq(metric)].iloc[0]
        fields = {
            "scenario_balanced_proposed_mean": p_mean,
            "scenario_balanced_baseline_mean": b_mean,
            "paired_absolute_difference": difference,
            "aggregate_mean_relative_improvement": relative,
            "relative_improvement_lower": interval["relative_improvement_lower"],
        }
        for field, value in fields.items():
            comparisons.append({
                "metric": metric, "field": field, "recomputed": value,
                "stored": float(expected[field]), "within_tolerance": close(value, expected[field]),
            })
    comparison_frame = pd.DataFrame(comparisons)
    comparison_frame.to_csv(OUT / "CONFIRMATORY_STATISTIC_REPLICATION.csv", index=False)

    dcsv = cycles[(cycles.method.eq(P_METHOD)) & cycles.attempted_solver_calls.fillna(0).gt(0)]
    decisions = len(dcsv)
    raw_calls = int(dcsv.attempted_solver_calls.sum())
    restoration = int(dcsv.restoration_used.sum())
    fallback = int(dcsv.fallback_used.sum())
    primary = decisions - restoration - fallback
    denominator_ok = (
        primary + restoration + fallback == decisions
        and primary + 2 * restoration + 2 * fallback == raw_calls
    )
    final_seed_manifest = pd.read_csv(EVIDENCE / "PLANT_A_PRIMARY_MANIFEST.csv")
    seed_counts = final_seed_manifest.seed.value_counts()
    final_seed_coverage = set(seed_counts.index) == set(range(100, 160)) and seed_counts.eq(2).all()
    expected_rows = {
        "plant_a_primary": 240, "plant_a_supplemental": 120,
        "plant_b": 48, "normal": 42, "contract_violation": 6,
    }
    actual_rows = episodes.groupby("dataset_kind").size().to_dict()
    task_counts_ok = all(actual_rows.get(kind) == count for kind, count in expected_rows.items())
    summary_hash_ok = marker["summary_sha256"] == sha256(RESULTS / "C2_SUMMARY.json")
    result = {
        "schema": "direction5.closure.confirmatory_audit.v1",
        "lock_verified": lock_audit["passed"], "lock_audit": lock_audit,
        "marker_complete": marker["status"] == "COMPLETE",
        "summary_hash_verified": summary_hash_ok, "final_seed_coverage": bool(final_seed_coverage),
        "task_counts_verified": task_counts_ok, "episode_rows": len(episodes),
        "cycle_rows": len(cycles), "paired_failure_table_exact": failure_match,
        "statistic_fields": len(comparison_frame),
        "statistic_fields_matching": int(comparison_frame.within_tolerance.sum()),
        "optimization_decisions": decisions, "raw_solver_invocations": raw_calls,
        "restoration_calls": restoration, "fallback_calls": fallback,
        "solver_denominator_identities_hold": denominator_ok,
        "confirmatory_positive_gate": summary["confirmatory_positive_gate"],
        "joint_validation_confirmatory_positive": summary["joint_validation_confirmatory_positive"],
    }
    result["passed"] = bool(
        result["lock_verified"] and result["marker_complete"] and summary_hash_ok
        and final_seed_coverage and task_counts_ok and failure_match
        and comparison_frame.within_tolerance.all() and denominator_ok
    )
    (OUT / "CONFIRMATORY_AUDIT.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
