"""Recompute conditional Direction5 contract, recourse and viability certificates."""

from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

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


RESULTS = REPO / "results_final/R4"
THEORY = REPO / "research_outputs_final/05_THEORY"
PROGRESS = REPO / "progress_final"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def contract_and_recourse_certificates() -> tuple[pd.DataFrame, pd.DataFrame]:
    plant = PlantAFull()
    observation = plant.public_observation(0.0, plant.equilibrium(), np.zeros(4))
    base = DeliverabilitySetMembership(
        plant.parameters.bess.contract, 2.0
    ).update(0.0, np.zeros(2), np.zeros(2))
    promoted = replace(
        base,
        performance_power_pu=np.array((0.080, 0.080)),
        performance_ramp_pu_per_s=np.array((0.060, 0.060)),
    )
    contract_rows = []
    recourse_rows = []
    for period_s in (2.0, 4.0):
        for level in (0.06, 0.10):
            load = np.array((level, 0.90 * level))
            domain = DomainSupervisor(plant.parameters).classify(
                load, observation.measured_soc
            )
            inputs = DCSVInput(observation, load, promoted, domain)
            controller = DCSVContractRecourseMPC(period_s, 6)
            result = controller.propose(inputs)
            contract = compute_contract_branch_certificate(controller, inputs, result)
            recourse = compute_surplus_loss_recourse_certificate(controller, result)
            contract_rows.append({
                "period_s": period_s,
                "load0_pu": load[0],
                "load1_pu": load[1],
                **{key: value for key, value in asdict(contract).items()
                   if not isinstance(value, np.ndarray)},
            })
            recourse_rows.append({
                "period_s": period_s,
                "load0_pu": load[0],
                "load1_pu": load[1],
                "horizon_steps": recourse.horizon_steps,
                "reaction_delay_s": recourse.reaction_delay_s,
                "maximum_surplus_loss_area0_pu": recourse.maximum_surplus_loss_pu[0],
                "maximum_surplus_loss_area1_pu": recourse.maximum_surplus_loss_pu[1],
                "recourse_margin_area0_pu": recourse.recourse_margin_pu[0],
                "recourse_margin_area1_pu": recourse.recourse_margin_pu[1],
                "loss_branch_frequency_margin_pu": recourse.loss_branch_frequency_margin_pu,
                "loss_branch_ace_margin_pu": recourse.loss_branch_ace_margin_pu,
                "loss_branch_tie_margin_pu": recourse.loss_branch_tie_margin_pu,
                "certified": recourse.certified,
                "claim_level": recourse.claim_level,
            })
    return pd.DataFrame(contract_rows), pd.DataFrame(recourse_rows)


def terminal_certificates() -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    rows = []
    arrays: dict[str, np.ndarray] = {}
    for period_s in (2.0, 4.0):
        for level in (0.03, 0.06, 0.09):
            load = np.array((level, 0.8 * level))
            certificate = compute_local_rpi_certificate(period_s, load)
            key = f"p{period_s:g}_l{level:g}".replace(".", "p")
            arrays[f"{key}_radius"] = certificate.error_box_radius
            arrays[f"{key}_gain"] = certificate.terminal_feedback_gain
            arrays[f"{key}_equilibrium"] = certificate.equilibrium_state
            rows.append({
                "period_s": period_s,
                "load0_pu": load[0],
                "load1_pu": load[1],
                "closed_loop_spectral_radius": certificate.closed_loop_spectral_radius,
                "absolute_closed_loop_spectral_radius": certificate.absolute_closed_loop_spectral_radius,
                "invariance_residual": certificate.invariance_residual,
                "minimum_state_margin_pu": certificate.minimum_state_margin_pu,
                "minimum_input_margin_pu": certificate.minimum_input_margin_pu,
                "maximum_box_radius": float(np.max(certificate.error_box_radius)),
                "nonempty": certificate.nonempty,
                "admissible": certificate.admissible,
                "claim_level": certificate.claim_level,
                "pipeline_condition": "QUIESCENT_BESS_COMMAND_PIPELINE",
                "plant_scope": "PLANT_A_LOCAL_LINEAR_ERROR_MODEL",
            })
    return pd.DataFrame(rows), arrays


def bridge_and_infeasibility() -> tuple[pd.DataFrame, pd.DataFrame]:
    bridge_rows = []
    for load0, load1, soc in (
        (0.130, 0.128, 0.50),
        (0.145, 0.135, 0.50),
        (0.165, 0.145, 0.50),
        (0.170, 0.155, 0.105),
        (0.200, 0.180, 0.50),
    ):
        certificate = compute_bridge_certificate(
            np.array((load0, load1)), np.array((soc, soc))
        )
        bridge_rows.append({
            "load0_pu": load0,
            "load1_pu": load1,
            "soc": soc,
            "deficit0_pu": certificate.initial_deficit_pu[0],
            "deficit1_pu": certificate.initial_deficit_pu[1],
            "handoff_time_s": certificate.handoff_time_s,
            "required_energy_mwh": certificate.required_energy_mwh,
            "available_energy_mwh": certificate.available_energy_mwh,
            "power_margin_pu": certificate.power_margin_pu,
            "ramp_margin_pu_per_s": certificate.ramp_margin_pu_per_s,
            "energy_margin_mwh": certificate.energy_margin_mwh,
            "certified": certificate.certified,
            "claim_level": certificate.claim_level,
        })
    infeasible_rows = []
    for load, soc in (
        ((0.08, 0.06), (0.5, 0.5)),
        ((0.165, 0.145), (0.105, 0.105)),
        ((0.25, 0.18), (0.5, 0.5)),
        ((0.28, 0.27), (0.5, 0.5)),
    ):
        certificate = compute_infeasibility_certificate(
            np.asarray(load), np.asarray(soc)
        )
        infeasible_rows.append({
            "load0_pu": load[0],
            "load1_pu": load[1],
            "soc0": soc[0],
            "soc1": soc[1],
            "certificate_type": certificate.certificate_type,
            "violation_margin": certificate.violation_margin,
            "certified_infeasible": certificate.certified_infeasible,
            "reason": certificate.reason,
        })
    return pd.DataFrame(bridge_rows), pd.DataFrame(infeasible_rows)


def write_theory_documents() -> None:
    write_text(THEORY / "ASSUMPTIONS.md", """
# Certificate assumptions

- True command-to-actual power/ramp capability contains the registered contract.
- Actual delay lies in the registered delay set and model error lies in the
  stated remainder set.
- Measured SoC is correct and the BESS delay pipeline is represented.
- A performance envelope is revocable allocation evidence, never a hard floor.
- Surplus loss is observable by the next control cycle for the recourse claim.
- Sustainable RPI applies only to the Plant-A local error model around the
  load-parameterized equilibrium with a quiescent BESS pipeline.
- Bridge claims end at registered slow-reserve handoff; Plant B is empirical.
""")
    write_text(THEORY / "THEOREMS_AND_PROOFS.md", r"""
# Theorems and bounded proofs

## T1 — same-instant impossibility

Consider two worlds with identical public histories through the decision
instant. One retains the contract; the other drops without announcement to a
set excluding the issued command. Causality forces the same action in both
worlds, so executability cannot be guaranteed in the collapsed world. This is
an impossibility of unconditional same-instant protection, not of later causal
detection and recourse.

## T2 — conditional finite-horizon contract branch

Under contract containment, registered delay/model error and correct measured
SoC, every dense-delay replay uses the same guaranteed sequence and the loss
branch uses zero surplus. The certificate directly checks guaranteed
power/ramp, physical predicted power/ramp/energy, and frequency/ACE/tie bounds.
It certifies the optimized horizon only.

## T3 — surplus-loss recourse

All branches share stage 0. From stage 1, registered SG and slow-reserve ramp
headroom must dominate the maximum removed surplus, and the loss-branch state
must remain inside frequency/ACE/tie bounds. The recomputable margin is a
conditional one-cycle recourse certificate.

## T4 — sustainable terminal set

For each load inside SG equilibrium capability, the local SG-feedback error
model is Schur. The box radius solves `z = |Acl| z + w`; positive state/input
margins and `|Acl|z+w-z <= 0` give a conditional local RPI box. It is not a
native ANDES DAE theorem.

## T5 — finite bridge

The contract BESS supplies the triangular deficit while slow reserve ramps,
plus the worst-delay buffer. Power, ramp and measured-energy inequalities must
all hold. Without a slow takeover, the claim ends at finite energy exhaustion.

## T6 — physical infeasibility

Load beyond SG plus slow reserve has no registered steady equilibrium. A load
inside steady power may still be bridge-infeasible if power, ramp or measured
energy conditions fail. Such cases are physical certificates, not ordinary
controller failures.
""")
    write_text(THEORY / "CLAIM_BOUNDARY.md", """
# Locked claim boundary

- Recursive feasibility: supported only for the stated Plant-A local terminal
  error model and its explicit assumptions.
- DCSV-CR contract/loss prediction: conditional finite horizon.
- Bridge: finite horizon to registered slow reserve only.
- Arbitrary contract collapse: no same-instant guarantee; evaluated separately.
- Native Plant B: empirical validation only, with no DAE RPI certificate.
- Finite-sample coverage: empirical with confidence bounds, not distribution-free
  deterministic truth.
""")


def main() -> None:
    for directory in (RESULTS, THEORY, PROGRESS):
        directory.mkdir(parents=True, exist_ok=True)
    contract, recourse = contract_and_recourse_certificates()
    terminal, terminal_arrays = terminal_certificates()
    bridge, infeasible = bridge_and_infeasibility()
    witness = construct_same_instant_impossibility_witness(
        np.array((0.045, 0.045)), np.array((0.045, 0.045)), np.array((0.010, 0.012))
    )
    contract.to_json(THEORY / "CONTRACT_BRANCH_CERTIFICATE.json", orient="records", indent=2)
    recourse.to_json(THEORY / "RECOURSE_CERTIFICATE.json", orient="records", indent=2)
    np.savez_compressed(THEORY / "SUSTAINABLE_TERMINAL_SET.npz", **terminal_arrays)
    bridge.to_parquet(THEORY / "BRIDGE_CERTIFICATES.parquet", index=False)
    infeasible.to_parquet(THEORY / "INFEASIBILITY_CERTIFICATES.parquet", index=False)
    contract.to_parquet(RESULTS / "CONTRACT_BRANCH_CERTIFICATES.parquet", index=False)
    recourse.to_parquet(RESULTS / "RECOURSE_CERTIFICATES.parquet", index=False)
    terminal.to_csv(RESULTS / "SUSTAINABLE_TERMINAL_CERTIFICATES.csv", index=False)
    bridge.to_parquet(RESULTS / "BRIDGE_CERTIFICATES.parquet", index=False)
    infeasible.to_parquet(RESULTS / "INFEASIBILITY_CERTIFICATES.parquet", index=False)
    (RESULTS / "SAME_INSTANT_IMPOSSIBILITY.json").write_text(
        json.dumps({
            key: value.tolist() if isinstance(value, np.ndarray) else value
            for key, value in asdict(witness).items()
        }, indent=2) + "\n", encoding="utf-8"
    )
    theorem_status = pd.DataFrame([
        ("T1", "SAME_INSTANT_IMPOSSIBILITY", "PROVED", "arbitrary unannounced collapse"),
        ("T2", "CONTRACT_BRANCH", "CONDITIONAL_FINITE_HORIZON", "Plant A prediction model"),
        ("T3", "SURPLUS_LOSS_RECOURSE", "CONDITIONAL_ONE_CYCLE", "registered recourse headroom"),
        ("T4", "SUSTAINABLE_RPI", "CONDITIONAL_LOCAL", "Plant A local error model"),
        ("T5", "BRIDGE", "FINITE_HORIZON_ONLY", "slow-reserve takeover required"),
        ("T6", "INFEASIBILITY", "REGISTERED_PHYSICAL_PRECHECK", "power/ramp/energy"),
    ], columns=("theorem", "subject", "status", "scope"))
    theorem_status.to_csv(RESULTS / "THEOREM_STATUS.csv", index=False)
    write_theory_documents()
    gates = {
        "same_instant_impossibility_established": witness.impossibility_established,
        "contract_branch_finite_horizon_certified": bool(contract.finite_horizon_certified.all()),
        "surplus_loss_recourse_certified": bool(recourse.certified.all()),
        "sustainable_terminal_nonempty_admissible": bool(terminal.nonempty.all() and terminal.admissible.all()),
        "bridge_has_certified_and_uncertified_cells": bool(bridge.certified.any() and (~bridge.certified).any()),
        "infeasibility_has_positive_and_negative_controls": bool(
            infeasible.certified_infeasible.any() and (~infeasible.certified_infeasible).any()
        ),
        "recursive_claim_conditionally_scoped": True,
        "native_plant_b_theory_withheld": True,
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    progress = {
        "schema": "direction5.final_repair.progress.v1",
        "stage": "R4",
        "status": status,
        "gate": "CONDITIONAL_THEORY_CERTIFICATES" if status == "PASS" else "EMPTY_OR_FAILED_CERTIFICATE",
        "certificate_status": "CONDITIONAL_LOCAL_RPI_PLUS_FINITE_HORIZON_CONTRACT_RECOURSE_AND_BRIDGE",
        "recursive_feasibility_claim": "PLANT_A_LOCAL_MODEL_ONLY_UNDER_EXPLICIT_ASSUMPTIONS",
        "contract_branch_certified": int(contract.finite_horizon_certified.sum()),
        "recourse_certified": int(recourse.certified.sum()),
        "terminal_certified": int(terminal.admissible.sum()),
        "bridge_certified": int(bridge.certified.sum()),
        "bridge_not_certified": int((~bridge.certified).sum()),
        "infeasibility_certified": int(infeasible.certified_infeasible.sum()),
        "final_seeds_consumed": False,
        "gates": gates,
        "failures": [name for name, passed in gates.items() if not passed],
        "next_stage": "R5" if status == "PASS" else "R8_TERMINATE_EMPTY_CERTIFICATES",
    }
    (PROGRESS / "R4.json").write_text(
        json.dumps(progress, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2))
    if status != "PASS":
        raise SystemExit("R4 Gate failed: " + ", ".join(progress["failures"]))


if __name__ == "__main__":
    main()
