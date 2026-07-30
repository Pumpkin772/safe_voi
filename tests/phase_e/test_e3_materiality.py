from __future__ import annotations

import inspect
import json
from pathlib import Path

import pandas as pd

from direction1freq.controllers.nominal_mpc import FiniteHorizonMPC, NominalModelMPC
from direction1freq.evaluation.oracles.current_capability_nmpc import CurrentCapabilityNMPCOracle
from direction1freq.controllers.rls_adaptive_mpc import RLSAdaptiveMPC
from direction1freq.controllers.robust_capability_mpc import RobustCapabilityMPC


ROOT = Path(__file__).resolve().parents[2]
RESULT = ROOT / "results_phase_e" / "E3" / "full"


def test_every_mpc_is_true_rolling_finite_horizon_optimization() -> None:
    source = inspect.getsource(FiniteHorizonMPC)
    for token in (
        "horizon", "cp.Variable", "predicted_state", "decision_action",
        "constraints", "self.problem.solve", "previous_action", "first_action_pu",
    ):
        assert token in source
    for controller in (NominalModelMPC, RLSAdaptiveMPC, RobustCapabilityMPC):
        assert "FiniteHorizonMPC" in inspect.getsource(controller)


def test_oracle_is_evaluation_only_multiple_shooting_and_nonclairvoyant() -> None:
    source = inspect.getsource(CurrentCapabilityNMPCOracle)
    assert CurrentCapabilityNMPCOracle.evaluation_only is True
    assert "nonlinear_multiple_shooting" in source
    assert "future_load" not in inspect.signature(
        CurrentCapabilityNMPCOracle.solve_evaluation_only
    ).parameters
    assert "future" not in inspect.signature(
        CurrentCapabilityNMPCOracle.solve_evaluation_only
    ).parameters
    import direction1freq.controllers as deployable
    assert not hasattr(deployable, "CurrentCapabilityNMPCOracle")


def test_e3_manifest_seed_balance_and_no_final_seeds() -> None:
    manifest = pd.read_csv(RESULT / "E3_EXPERIMENT_MANIFEST.csv")
    main = manifest[manifest.sfr_period_s == 4.0]
    assert main.groupby(["mechanism", "sg_tension"]).size().min() >= 20
    assert manifest["load_seed"].max() < 50
    required = {
        "plant", "load_seed", "solver_seed", "mechanism", "sg_tension",
        "sfr_period_s", "load_timing", "disturbance_area", "disturbance_sign",
        "disturbance_magnitude_pu", "capability_change_time_s", "known_ood",
    }
    assert required <= set(manifest.columns)


def test_e3_oracle_qualification_and_failure_retention() -> None:
    episodes = pd.read_parquet(RESULT / "E3_MATERIALITY_EPISODES.parquet")
    oracle = episodes[episodes.method == "oracle_o2_nmpc"]
    assert (oracle.solver_success_fraction >= 0.95).mean() >= 0.95
    finite = oracle.loc[
        oracle.solver_residual_p99.map(lambda value: value < float("inf")),
        "solver_residual_p99",
    ]
    assert finite.quantile(0.99) <= 1e-5
    nonfinite = oracle[~oracle.index.isin(finite.index)]
    assert (nonfinite.fallback_count > 0).all()
    assert episodes.failure_class.notna().all()
    assert len(episodes) == episodes.scenario_id.nunique() * 6


def test_e3_materiality_gate_and_plant_direction() -> None:
    progress = json.loads((ROOT / "progress_phase_e" / "E3_full.json").read_text())
    summary = pd.read_csv(RESULT / "E3_MATERIALITY_SUMMARY.csv")
    assert progress["oracle_qualified"]
    assert progress["gate_passed"]
    assert summary[summary.cell_materiality_pass].mechanism.nunique() >= 2
    assert summary[summary.cell_materiality_pass].sg_tension.nunique() >= 2
    assert progress["gate_components"]["plant_a_b_direction_consistent"]
