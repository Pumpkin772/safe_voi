from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from direction5freq.controllers.dcsv_cr_mpc import DCSVContractRecourseMPC
from direction5freq.controllers.dcsv_mpc_final import DCSVInput
from direction5freq.controllers.domain_supervisor import DomainSupervisor
from direction5freq.estimation.deliverability_set_membership import DeliverabilitySetMembership
from direction5freq.models.plant_a_full import PlantAFull
from direction5freq.theory.bridge_certificate import compute_bridge_certificate
from direction5freq.theory.contract_branch_certificate import compute_contract_branch_certificate
from direction5freq.theory.impossibility import construct_same_instant_impossibility_witness
from direction5freq.theory.infeasibility_certificate import compute_infeasibility_certificate
from direction5freq.theory.recourse_certificate import compute_surplus_loss_recourse_certificate
from direction5freq.theory.terminal_set import compute_local_rpi_certificate


REPO = Path(__file__).resolve().parents[2]


def certified_controller_case():
    plant = PlantAFull()
    observation = plant.public_observation(0.0, plant.equilibrium(), np.zeros(4))
    envelope = DeliverabilitySetMembership(
        plant.parameters.bess.contract, 2.0
    ).update(0.0, np.zeros(2), np.zeros(2))
    envelope = replace(
        envelope,
        performance_power_pu=np.array((0.080, 0.080)),
        performance_ramp_pu_per_s=np.array((0.060, 0.060)),
    )
    load = np.array((0.10, 0.09))
    domain = DomainSupervisor(plant.parameters).classify(load, observation.measured_soc)
    inputs = DCSVInput(observation, load, envelope, domain)
    controller = DCSVContractRecourseMPC(2.0, 6)
    result = controller.propose(inputs)
    return controller, inputs, result


def test_same_instant_impossibility_and_conditional_scope() -> None:
    witness = construct_same_instant_impossibility_witness(
        np.array((0.045, 0.045)), np.array((0.045, 0.045)), np.array((0.010, 0.012))
    )
    assert witness.public_history_identical
    assert witness.causal_actions_identical
    assert witness.retained_world_executable
    assert not witness.collapsed_world_executable
    assert witness.impossibility_established


def test_contract_and_surplus_loss_recourse_certificates_recompute() -> None:
    controller, inputs, result = certified_controller_case()
    contract = compute_contract_branch_certificate(controller, inputs, result)
    recourse = compute_surplus_loss_recourse_certificate(controller, result)
    assert contract.finite_horizon_certified
    assert contract.claim_level == "CONDITIONAL_FINITE_HORIZON_CONTRACT_BRANCH"
    assert recourse.certified
    assert np.all(recourse.recourse_margin_pu > 0.0)


def test_terminal_bridge_and_infeasibility_claims_remain_distinct() -> None:
    terminal = compute_local_rpi_certificate(2.0, np.array((0.06, 0.048)))
    bridge = compute_bridge_certificate(np.array((0.145, 0.135)), np.array((0.5, 0.5)))
    infeasible = compute_infeasibility_certificate(
        np.array((0.28, 0.27)), np.array((0.5, 0.5))
    )
    assert terminal.admissible and terminal.claim_level == "CONDITIONAL_LOCAL_LINEAR_RPI"
    assert bridge.certified and bridge.claim_level == "FINITE_HORIZON_BRIDGE_TO_SLOW_RESERVE"
    assert infeasible.certified_infeasible


def test_r4_outputs_pass_and_withhold_native_plant_b_theorem() -> None:
    progress = json.loads((REPO / "progress_final/R4.json").read_text("utf-8"))
    assert progress["status"] == "PASS"
    assert progress["gates"]["native_plant_b_theory_withheld"]
    assert progress["recursive_feasibility_claim"].startswith("PLANT_A_LOCAL_MODEL_ONLY")
