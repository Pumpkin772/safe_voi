from __future__ import annotations

import numpy as np

from direction1freq.controllers.feasibility_restoration import (
    restore_action_lexicographically,
)
from direction1freq.controllers.nominal_mpc import FiniteHorizonMPC
from direction1freq.controllers.proposed_robust_tube_mpc import (
    CapabilitySetRobustTubeMPC,
)
from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2


def _public_excitation():
    plant = TwoAreaPlantAV2(dt_s=0.05)
    state = plant.equilibrium()
    for _ in range(80):
        state, _ = plant.step(state, np.zeros(4), np.array([0.07, -0.01]))
    return (
        plant,
        plant.public_observation(4.0, state, np.zeros(4)),
        plant.state_vector(state),
    )


class _RejectAll:
    def contains(self, *_args, **_kwargs) -> bool:
        return False


class _RejectOnce:
    def __init__(self) -> None:
        self.calls = 0

    def contains(self, *_args, **_kwargs) -> bool:
        self.calls += 1
        return self.calls > 1


def _proposal(optimizer: FiniteHorizonMPC):
    plant, _observation, state = _public_excitation()
    del plant
    return optimizer.propose(
        state,
        np.array([0.07, -0.01]),
        np.array([-0.05, -0.03, -0.05, -0.03]),
        np.array([0.05, 0.03, 0.05, 0.03]),
        np.array([-0.03, -0.03]),
        np.array([0.03, 0.03]),
        np.array([0.04, 0.03, 0.04, 0.03]),
        delay_s=optimizer.nominal_delay_s,
    )


def test_successful_proposal_has_no_physical_side_effect_until_commit() -> None:
    optimizer = FiniteHorizonMPC(4.0, 5, nominal_delay_s=1.999)
    before = optimizer.previous_action.copy()
    action, diagnostic = _proposal(optimizer)
    assert diagnostic.solved
    assert np.array_equal(optimizer.previous_action, before)
    optimizer.commit_applied_action(action)
    assert np.allclose(optimizer.previous_action, action)


def test_terminal_reject_commits_fallback_and_next_model_uses_it() -> None:
    _plant, observation, state = _public_excitation()
    controller = CapabilitySetRobustTubeMPC(4.0, 5)
    controller.terminal_set = _RejectAll()
    applied, first = controller.update(
        observation, state, np.array([0.07, -0.01]), 0.05
    )
    assert first.terminal_backup_predicted is False
    assert first.mpc.terminal_reject
    assert first.used_fallback
    assert np.allclose(controller.optimizer.previous_action, applied)
    applied2, second = controller.update(
        observation, state, np.array([0.07, -0.01]), 0.05
    )
    assert np.allclose(second.mpc.previous_model_action, applied)
    assert second.mpc.history_match
    assert second.mpc.consecutive_backup_count == 2
    assert np.allclose(controller.optimizer.previous_action, applied2)


def test_fallback_then_recovered_qp_keeps_history_synchronized() -> None:
    _plant, observation, state = _public_excitation()
    controller = CapabilitySetRobustTubeMPC(4.0, 5)
    controller.terminal_set = _RejectOnce()
    fallback, first = controller.update(
        observation, state, np.array([0.07, -0.01]), 0.05
    )
    recovered, second = controller.update(
        observation, state, np.array([0.07, -0.01]), 0.05
    )
    assert first.used_fallback
    assert not second.used_fallback
    assert np.allclose(second.mpc.previous_model_action, fallback)
    assert np.allclose(controller.optimizer.previous_action, recovered)
    assert second.mpc.consecutive_backup_count == 0


def test_restoration_never_softens_power_or_slew() -> None:
    result = restore_action_lexicographically(
        reference_action=np.array([2.0, -2.0]),
        previous_applied_action=np.zeros(2),
        input_lower=np.array([-0.1, -0.1]),
        input_upper=np.array([0.1, 0.1]),
        command_slew=np.array([0.02, 0.03]),
        performance_matrix=np.eye(2),
        performance_target=np.array([1.0, -1.0]),
        performance_limit=np.zeros(2),
    )
    assert result.succeeded
    assert not result.physical_constraints_softened
    assert result.hard_constraint_residual <= 1e-7
    assert np.all(np.abs(result.action) <= np.array([0.02, 0.03]) + 1e-7)

