from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "research_outputs_closure/02_CONFIRMATORY"


def test_confirmatory_execution_is_complete_and_negative() -> None:
    summary = json.loads((REPO / "results_closure/C2/C2_SUMMARY.json").read_text("utf-8"))
    assert summary["execution_complete"] is True
    assert summary["final_seeds_consumed"] is True
    assert summary["post_result_tuning_permitted"] is False
    assert summary["core_metrics_passing"] == 0
    assert summary["confirmatory_positive_gate"] is False
    assert summary["validation_positive_gate"] is False
    assert summary["joint_validation_confirmatory_positive"] is False


def test_confirmatory_scale_and_raw_cycles_are_complete() -> None:
    episodes = pd.read_parquet(EVIDENCE / "FINAL_EPISODES.parquet")
    cycles = pd.read_parquet(EVIDENCE / "FINAL_CYCLES.parquet")
    assert episodes.groupby("dataset_kind").size().to_dict() == {
        "contract_violation": 6,
        "normal": 42,
        "plant_a_primary": 240,
        "plant_a_supplemental": 120,
        "plant_b": 48,
    }
    assert len(cycles) > 0
    assert cycles.applied_action_available.all()


def test_confirmatory_solver_denominator_and_audit() -> None:
    denominator = pd.read_csv(EVIDENCE / "FINAL_SOLVER_DENOMINATOR.csv")
    counts = dict(zip(denominator.quantity, denominator["count"]))
    assert counts["attempted_optimization_decisions"] == 20227
    assert counts["raw_solver_invocations"] == 21400
    assert denominator.decision_identity_holds.all()
    assert denominator.raw_invocation_identity_holds.all()
    audit = json.loads((EVIDENCE / "AUDIT/CONFIRMATORY_AUDIT.json").read_text("utf-8"))
    assert audit["passed"] is True
