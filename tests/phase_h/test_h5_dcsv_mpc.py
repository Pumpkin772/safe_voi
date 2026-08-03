from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction5_freq.controllers import (
    ContractRobustMPC,
    DCSVInput,
    DisturbanceCapabilitySeparatedViabilityMPC,
    NominalOffsetFreeMPC,
    RLSAdaptiveMPC,
)
from direction5_freq.controllers.feasibility_restoration import RestorationPolicy
from direction5_freq.models.load_parameterized_equilibrium import (
    solve_sustainable_equilibrium,
)


REPO = Path(__file__).resolve().parents[2]


def _input(load=(0.02, 0.0), reserve=0.025) -> DCSVInput:
    load_array = np.asarray(load, dtype=float)
    equilibrium = solve_sustainable_equilibrium(
        load_array,
        np.full(2, -reserve),
        np.full(2, reserve),
        0.08,
    )
    state = equilibrium.state_pu if equilibrium.feasible else np.zeros(9)
    return DCSVInput(
        state,
        load_array,
        np.zeros(4),
        np.zeros(2),
        np.full(2, 25.0),
        np.full(2, 0.05),
        np.full(2, 0.05),
        np.full(2, 0.04),
        np.full(2, 0.04),
        np.array([[0.1, 0.4], [0.1, 0.4]]),
        np.full(2, 10.0),
        np.array([[0.5, 1.0], [0.5, 1.0]]),
    )


def test_dcsv_is_true_rolling_common_sequence_and_commits_applied_action() -> None:
    controller = DisturbanceCapabilitySeparatedViabilityMPC(
        2.0, 3, sg_reserve_pu=0.025
    )
    data = _input()
    action, diagnostic = controller.control(data)
    assert diagnostic.solved
    assert diagnostic.common_control_sequence
    assert diagnostic.predicted_states.shape == (3, 4, 9)
    assert diagnostic.predicted_actions.shape == (3, 4)
    assert np.allclose(action, diagnostic.predicted_actions[0])
    next_data = replace(
        data,
        state_estimate_pu=diagnostic.predicted_states[0, 1],
        previous_actual_action_pu=action,
        actual_bess_power_pu=action[[1, 3]],
    )
    _, second = controller.control(next_data)
    assert second.action_history_match
    assert not second.physical_hard_violation


def test_domain_routing_bridge_and_physical_infeasibility_are_distinct() -> None:
    bridge = DisturbanceCapabilitySeparatedViabilityMPC(
        2.0, 3, sg_reserve_pu=0.025
    )
    action, diagnostic = bridge.control(_input((0.06, 0.0)))
    assert diagnostic.domain == "BRIDGE_ONLY"
    assert diagnostic.solved
    assert np.sum(np.abs(action[[1, 3]])) > 1e-3
    assert diagnostic.finite_horizon_only
    infeasible = DisturbanceCapabilitySeparatedViabilityMPC(
        2.0, 3, sg_reserve_pu=0.025
    )
    _, failed = infeasible.control(_input((0.22, 0.22)))
    assert failed.physical_infeasibility_preclassified
    assert not failed.fallback_used
    assert failed.scenario_count == 0
    assert failed.primary_status.startswith("NOT_SOLVED_PRECLASSIFIED")


def test_all_deployable_named_mpc_baselines_have_state_and_input_sequences() -> None:
    for controller_type in (
        NominalOffsetFreeMPC,
        RLSAdaptiveMPC,
        ContractRobustMPC,
    ):
        action, diagnostic = controller_type(
            2.0, 3, sg_reserve_pu=0.025
        ).control(_input())
        assert diagnostic.solved
        assert diagnostic.predicted_states.shape[-2:] == (4, 9)
        assert diagnostic.predicted_actions.shape == (3, 4)
        assert np.allclose(action, diagnostic.first_predicted_action_pu)


def test_restoration_and_ordinary_information_boundary_are_hard() -> None:
    policy = RestorationPolicy()
    assert policy.physical_constraints_never_relaxed()
    source = inspect.getsource(DisturbanceCapabilitySeparatedViabilityMPC)
    for forbidden in ("future_event", "future_mode", "final_seed", "hidden_parameter"):
        assert forbidden not in source


def test_h5_saved_gate_and_mpc_structure_audit_pass() -> None:
    progress = json.loads((REPO / "progress_phase_h/H5.json").read_text("utf-8"))
    assert progress["gate_passed"]
    assert progress["fallback_calls"] == 0
    assert progress["p99_solve_time_s"] < 1.0
    audit = pd.read_csv(REPO / "results_phase_h/H5/TRUE_MPC_STRUCTURE_AUDIT.csv")
    required = [
        "true_rolling_optimization",
        "predicted_state_sequence",
        "control_input_sequence",
        "dynamics_constraints",
        "power_constraints",
        "ramp_constraints",
        "delay_constraints",
        "energy_constraints",
        "terminal_or_bridge_condition",
        "solver_diagnostics",
    ]
    assert audit[required].all(axis=None)
