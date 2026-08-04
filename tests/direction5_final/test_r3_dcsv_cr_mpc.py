from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

import numpy as np

from direction5freq.controllers.contract_violation_supervisor import (
    ContractViolationSupervisor,
)
from direction5freq.controllers.dcsv_cr_mpc import DCSVContractRecourseMPC
from direction5freq.controllers.dcsv_mpc_final import DCSVInput
from direction5freq.controllers.domain_supervisor import DomainSupervisor
from direction5freq.controllers.recourse_tree import RecourseTree
from direction5freq.estimation.deliverability_set_membership import DeliverabilitySetMembership
from direction5freq.models.plant_a_full import PlantAFull


REPO = Path(__file__).resolve().parents[2]


def controller_input(load: np.ndarray, promoted: bool = False) -> DCSVInput:
    plant = PlantAFull()
    observation = plant.public_observation(0.0, plant.equilibrium(), np.zeros(4))
    envelope = DeliverabilitySetMembership(
        plant.parameters.bess.contract, 2.0
    ).update(0.0, np.zeros(2), np.zeros(2))
    if promoted:
        envelope = replace(
            envelope,
            performance_power_pu=np.array((0.080, 0.080)),
            performance_ramp_pu_per_s=np.array((0.060, 0.060)),
        )
    domain = DomainSupervisor(plant.parameters).classify(load, observation.measured_soc)
    return DCSVInput(observation, load, envelope, domain)


def test_registered_recourse_tree_has_hard_zero_surplus_loss_branch() -> None:
    tree = RecourseTree.registered(1.5)
    tree.validate()
    assert tree.shared_action_steps == 1
    loss = next(branch for branch in tree.branches if branch.name == "SURPLUS_LOSS")
    assert loss.surplus_delivery_fraction == 0.0
    assert loss.future_sg_recourse and loss.future_reserve_recourse


def test_dcsv_cr_is_rolling_shared_and_online_envelope_changes_surplus() -> None:
    load = np.array((0.10, 0.09))
    contract_result = DCSVContractRecourseMPC(2.0, 4).propose(
        controller_input(load, promoted=False)
    )
    online_result = DCSVContractRecourseMPC(2.0, 4).propose(
        controller_input(load, promoted=True)
    )
    assert online_result.diagnostics.status in {"optimal", "optimal_inaccurate"}
    assert online_result.shared_current_action_verified
    assert online_result.surplus_loss_branch_verified
    assert online_result.predicted_state_sequence.shape[:2] == (2, 2)
    assert online_result.predicted_input_sequence.shape == (2, 4, 4)
    assert np.max(np.abs(contract_result.predicted_surplus_bess_sequence_pu)) < 1e-7
    assert np.max(np.abs(online_result.predicted_surplus_bess_sequence_pu)) > 1e-5


def test_commit_records_applied_action_not_unexecuted_proposal() -> None:
    controller = DCSVContractRecourseMPC(2.0, 3)
    result = controller.propose(controller_input(np.array((0.05, 0.04)), promoted=True))
    applied = result.proposed_action_pu.copy()
    applied[[0, 2]] += np.array((0.003, -0.002))
    controller.commit(applied, np.array((0.001, -0.001)))
    assert np.allclose(controller.last_committed_action, applied)


def test_contract_supervisor_uses_only_causal_public_signals() -> None:
    plant = PlantAFull()
    observation = plant.public_observation(0.0, plant.equilibrium(), np.zeros(4))
    supervisor = ContractViolationSupervisor(plant.parameters.bess.contract, 2.0)
    decisions = []
    for index in range(5):
        current = replace(
            observation,
            time_s=2.0 * index,
            bess_actual_power_pu=np.zeros(2),
        )
        decisions.append(supervisor.update(np.array((0.045, 0.045)), current))
    assert decisions[-1].detected
    source = inspect.getsource(ContractViolationSupervisor)
    assert "true_capability" not in source
    assert "future_event" not in source


def test_r3_outputs_pass_registered_gate() -> None:
    progress = json.loads((REPO / "progress_final/R3.json").read_text("utf-8"))
    assert progress["status"] == "PASS"
    assert progress["hard_violations"] == 0
    assert progress["action_application_rate"] == 1.0
    assert progress["all_attempted_calls_in_denominator"]
