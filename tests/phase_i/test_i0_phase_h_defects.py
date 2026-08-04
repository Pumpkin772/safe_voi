from __future__ import annotations

import inspect
import json
from pathlib import Path

import pandas as pd

from direction5_freq.controllers.dcsv_mpc import DisturbanceCapabilitySeparatedViabilityMPC
from direction5_freq.estimation.capability_set_estimator import CapabilitySetEstimator
from scripts.phase_h import run_h7_validation


REPO = Path(__file__).resolve().parents[2]


def test_h7_seed_factor_confounding_and_no_capability_transition_are_frozen() -> None:
    source = inspect.getsource(run_h7_validation.build_manifest)
    assert "seed % 10" in source
    assert "seed % 2" in source
    assert "seed % len(MECHANISMS)" in source
    assert "capability_change_time_s" not in source


def test_h7_normal_hour_rows_are_artificial_not_simulated() -> None:
    source = inspect.getsource(run_h7_validation.add_normal_hour_rows)
    assert '"physical_success": True' in source
    assert '"controller_calls": 0' in source
    audit = pd.read_csv(REPO / "results_phase_i/I0/NORMAL1H_PROVENANCE_AUDIT.csv")
    assert len(audit) == 28
    assert audit.artificial_zero_row.all()


def test_h7_held_tail_and_reduced_plant_b_are_not_method_evidence() -> None:
    source = inspect.getsource(run_h7_validation.simulate_episode)
    assert "action = last_action.copy()" in source
    assert "native_residual_calibrated_reduced" in source
    replay = pd.read_csv(
        REPO / "results_phase_i/I0/H7_20_SCENARIO_HELD_VS_FULL_ROLLING.csv"
    )
    assert len(replay) >= 20
    assert replay.exact_absolute_difference.max() <= 1e-9
    assert replay.held_tail_s.gt(0).all()
    assert replay.full_rolling_tail_s.eq(0).all()


def test_h7_estimator_energy_availability_and_delay_semantics_are_reproduced() -> None:
    estimator_source = inspect.getsource(CapabilitySetEstimator)
    controller_source = inspect.getsource(DisturbanceCapabilitySeparatedViabilityMPC)
    assert "self.energy_used" in estimator_source
    assert "np.abs(soc_value - self.initial_soc)" in estimator_source
    assert "availability_interval=np.c_[np.zeros(2), np.ones(2)]" in estimator_source
    assert "lower, 0.5 * (lower + upper), upper" in controller_source
    semantic = pd.read_csv(
        REPO / "results_phase_i/I0/H7_SEMANTIC_DEFECT_REPRODUCTION.csv"
    )
    assert {
        "availability_no_op",
        "energy_semantics",
        "continuous_delay_not_enveloped",
        "bridge_clock_not_reused",
        "hard_coded_capability_floors",
    }.issubset(set(semantic.defect))


def test_i0_retracts_h7_claims_but_preserves_phase_h_evidence() -> None:
    progress = json.loads((REPO / "progress_phase_i/I0.json").read_text("utf-8"))
    assert progress["gate_passed"]
    assert progress["phase_h_h7_method_evidence_status"] == "RETRACTED_AS_METHOD_EVIDENCE"
    assert progress["defects_reproduced"] >= 12
    assert not progress["final_seeds_consumed"]
    assert (REPO / "results_phase_h/H7/H7_VALIDATION_EPISODES.parquet").is_file()
