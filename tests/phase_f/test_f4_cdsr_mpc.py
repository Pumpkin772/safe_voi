from __future__ import annotations

import inspect
import json
from pathlib import Path

import numpy as np

from direction1freq.controllers.cdsr_mpc import CapabilityDelaySetRobustMPC
from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2


ROOT = Path(__file__).resolve().parents[2]


def _equilibrium(period: float = 4.0):
    plant = TwoAreaPlantAV2()
    state = plant.equilibrium()
    observation = plant.public_observation(0.0, state, np.zeros(4))
    controller = CapabilityDelaySetRobustMPC(period, 3)
    return plant, state, observation, controller


def test_cdsr_is_real_common_sequence_rolling_qp_without_truth_api() -> None:
    _plant, _state, _observation, controller = _equilibrium()
    assert controller.primary_problem.is_qp()
    assert len(controller.vertices) == 5
    assert controller.u.shape == (4, 3)
    assert len(controller.x) == 5
    signature = inspect.signature(CapabilityDelaySetRobustMPC.update)
    for forbidden in ("true_capability", "hidden_parameter", "true_load", "future_event"):
        assert forbidden not in signature.parameters


def test_propose_is_side_effect_free_and_commit_matches_applied_action() -> None:
    plant, state, observation, controller = _equilibrium()
    before = controller.previous_action.copy()
    candidate, proposal = controller.propose(
        observation,
        plant.state_vector(state),
        np.zeros(2),
        0.05,
        public_energy_mwh=state.bess.energy_mwh,
    )
    assert proposal.solved
    assert np.array_equal(controller.previous_action, before)
    controller.commit_applied_action(candidate, np.zeros(2))
    assert np.allclose(controller.previous_action, candidate)


def test_restoration_and_terminal_backup_are_distinct_paths() -> None:
    plant, state, observation, restoration_controller = _equilibrium()
    action, restored = restoration_controller.update(
        observation,
        plant.state_vector(state),
        np.zeros(2),
        0.05,
        public_energy_mwh=state.bess.energy_mwh,
        force_primary_secondary_failure=True,
    )
    assert restored.restoration_used and restored.solved
    assert not restored.backup_used
    assert np.allclose(restoration_controller.previous_action, action)

    fallback_controller = CapabilityDelaySetRobustMPC(4.0, 3)
    fallback, failed = fallback_controller.update(
        observation,
        plant.state_vector(state),
        np.zeros(2),
        0.05,
        public_energy_mwh=state.bess.energy_mwh,
        force_all_solver_failure=True,
    )
    assert not failed.restoration_used
    assert failed.backup_used
    assert np.allclose(fallback[[1, 3]], 0.0)
    assert np.allclose(fallback_controller.previous_action, fallback)


def test_f4_gate_and_physical_hard_constraints() -> None:
    progress = json.loads((ROOT / "progress_phase_f" / "F4.json").read_text())
    assert progress["gate_passed"] is True
    assert progress["gate_components"]["physical_hard_constraint_violations_zero"]
    assert progress["gate_components"]["history_synchronized"]

