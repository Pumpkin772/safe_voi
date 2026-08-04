"""Audit the locked I6 decision without weakening a failed method Gate."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
I6 = REPO / "results_phase_i/I6"


def test_i6_has_registered_scale_pairing_and_full_rolling_episodes() -> None:
    plant_a = pd.read_csv(I6 / "PLANT_A_VALIDATION_MANIFEST.csv")
    plant_b = pd.read_csv(I6 / "PLANT_B_VALIDATION_MANIFEST.csv")
    episodes = pd.read_parquet(I6 / "VALIDATION_EPISODES.parquet")
    assert len(plant_a) == 120
    assert plant_a.groupby(["mechanism", "sg_tension", "period_s"]).size().min() >= 10
    assert len(plant_b) == 24
    assert plant_b.groupby("mechanism").size().min() >= 8
    assert len(episodes) == 288
    assert set(episodes.method) == {"dcsv_mpc", "fixed_allocation_pi"}
    assert episodes.groupby(["scenario_id", "method"]).size().eq(1).all()
    assert episodes.full_rolling.all()
    assert episodes.nominal_warmup_s.eq(60.0).all()
    assert episodes.capability_change_time_s.notna().all()
    assert not episodes.seed.between(100, 159).any()


def test_native_plant_b_is_not_a_reduced_surrogate() -> None:
    episodes = pd.read_parquet(I6 / "VALIDATION_EPISODES.parquet")
    native = episodes[episodes.plant.eq("B_native_ANDES_Kundur")]
    assert len(native) == 48
    assert native.native_network.all()
    assert native.native_converged.all()
    assert native.algebraic_power_balance_p99_pu.max() < 1e-6
    assert native.controller_calls.gt(0).all()


def test_normal1h_is_real_full_duration_and_not_held_tail() -> None:
    normal = pd.read_parquet(I6 / "NORMAL1H_EPISODES.parquet")
    assert len(normal) == 12
    assert normal.groupby("method").size().eq(6).all()
    assert normal.duration_s.eq(3600.0).all()
    assert normal.controller_calls.gt(800).all()
    assert normal.real_normal1h_provenance.eq("3600s_full_nonlinear_180000_physical_steps").all()
    assert normal.full_rolling.all()
    assert not normal.hard_violation.any()


def test_i6_failure_and_not_evaluated_semantics_are_preserved() -> None:
    summary = json.loads((I6 / "I6_SUMMARY.json").read_text("utf-8"))
    assert summary["status"] == "FAIL"
    assert not summary["method_gate_passed"]
    assert summary["decisive_status"] == "DIRECTION5_METHOD_NOT_SUPPORTED_AFTER_CORRECTED_FULL_VALIDATION"
    assert summary["validation_repair_rounds_used"] == 1
    assert not summary["final_seeds_consumed"]
    assert set(summary["failed_gates"]) == {
        "two_of_three_metrics_improve_8pct_positive_ci",
        "unresolved_math_infeasibility_at_most_0p1pct",
        "fallback_at_most_1pct",
        "plant_a_b_direction_consistent_positive",
    }
    hypotheses = pd.read_csv(I6 / "HYPOTHESES_H1_H6.csv").set_index("hypothesis")
    assert hypotheses.loc["H5", "status"] == "NOT_SUPPORTED"
    ledger = pd.read_csv(I6 / "FAILURE_LEDGER.csv")
    assert not ledger.deleted.any()
    assert not ledger.standard_changed.any()


def test_execution_repair_is_auditable_and_protocol_preserving() -> None:
    repair = json.loads((I6 / "I6_EXECUTION_REPAIR_1.json").read_text("utf-8"))
    assert repair["classification"] == "EXECUTION_INFRASTRUCTURE_NATIVE_PROCESS_EXIT"
    assert repair["repair_round"] == 1
    assert not repair["scientific_protocol_changed"]
    assert not repair["algorithm_weights_thresholds_scenarios_seeds_changed"]
    assert repair["completed_plant_a_method_rows_reused"] == 240
    assert repair["interrupted_native_method_rows_preserved"] == 3
    interrupted = pd.read_parquet(I6 / "INTERRUPTED_RUN_1_ALL_EPISODES_CHECKPOINT.parquet")
    assert len(interrupted) == 243


def test_physical_infeasibility_is_not_imputed_as_controller_failure() -> None:
    episodes = pd.read_parquet(I6 / "VALIDATION_EPISODES.parquet")
    infeasible = episodes[episodes.evaluation_status.eq("PHYSICALLY_INFEASIBLE_CERTIFIED")]
    assert len(infeasible) == 48
    assert not infeasible.physical_success.any()
    evaluated = episodes[episodes.evaluation_status.eq("EVALUATED")]
    assert len(evaluated) == 240
