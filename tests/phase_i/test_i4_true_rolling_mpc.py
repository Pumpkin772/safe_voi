from __future__ import annotations

import inspect
import json
from pathlib import Path

import pandas as pd

from direction5freq.controllers.dcsv_mpc_final import (
    DCSVInput,
    DisturbanceCapabilitySeparatedViabilityMPC,
    RollingContractMPC,
)


REPO = Path(__file__).resolve().parents[2]


def test_all_objects_named_mpc_are_true_rolling_optimizers() -> None:
    for controller in (
        DisturbanceCapabilitySeparatedViabilityMPC(2.0, horizon_steps=3),
        RollingContractMPC(2.0, horizon_steps=3),
    ):
        assert controller.is_true_rolling_mpc
        source = inspect.getsource(type(controller)) + inspect.getsource(DisturbanceCapabilitySeparatedViabilityMPC)
        assert "cp.Problem" in source
        assert "predicted_state_sequence" in source
        assert "predicted_input_sequence" in source
        assert "energy" in source
        assert "_delayed_bess_expression" in source


def test_ordinary_dcsv_input_has_no_truth_or_future_fields() -> None:
    fields = set(DCSVInput.__dataclass_fields__)
    forbidden = {"true_capability", "true_load", "hidden_parameter", "future_event", "future_mode"}
    assert fields.isdisjoint(forbidden)


def test_i4_cycle_evidence_has_predictions_constraints_and_diagnostics() -> None:
    cycles = pd.read_parquet(REPO / "results_phase_i/I4/ROLLING_CYCLE_DIAGNOSTICS.parquet")
    solved = cycles[cycles.predicted_state_steps.gt(0)]
    assert len(solved) > 0
    assert solved.predicted_state_steps.ge(2).all()
    assert solved.predicted_input_steps.ge(1).all()
    assert solved.predicted_energy_steps.ge(2).all()
    assert solved.vertex_count.ge(2).all()
    assert solved.solver_status.isin(["optimal", "optimal_inaccurate"]).all()
    assert solved.solver_residual.max() <= 1e-5


def test_i4_transactions_bridge_and_hard_constraints_pass() -> None:
    transactions = pd.read_csv(REPO / "results_phase_i/I4/ACTION_TRANSACTION_AUDIT.csv")
    assert transactions.action_issued.all()
    assert transactions.actual_action_committed.all()
    assert not transactions.stored_unexecuted_proposal.any()
    bridge = pd.read_csv(REPO / "results_phase_i/I4/BRIDGE_CLOCK_AUDIT.csv")
    assert bridge.bridge_remaining_s.is_monotonic_decreasing
    assert bridge.bridge_remaining_s.nunique() == len(bridge)


def test_i4_gate_passes_and_fallback_is_bounded() -> None:
    progress = json.loads((REPO / "progress_phase_i/I4.json").read_text("utf-8"))
    assert progress["gate_passed"]
    assert progress["fallback_cycles"] / progress["controller_cycles"] <= 0.01
    assert progress["p99_solve_time_s"] < 1.0
    assert not progress["final_seeds_consumed"]
