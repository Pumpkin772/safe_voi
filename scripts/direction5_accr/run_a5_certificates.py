"""Recompute the registered P1--P7 ACCR finite-horizon certificates."""

from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.probing import ProbeCandidate, candidate_models, simulate_hypothesis
from direction5freq.controllers.dcsv_cr_mpc import DCSVContractRecourseMPC
from direction5freq.controllers.dcsv_mpc_final import DCSVInput
from direction5freq.controllers.domain_supervisor import DomainSupervisor
from direction5freq.estimation.deliverability_set_membership import DeliverabilitySetMembership
from direction5freq.models.plant_a_full import PlantAFull
from direction5freq.theory.contract_branch_certificate import compute_contract_branch_certificate
from direction5freq.theory.impossibility import construct_same_instant_impossibility_witness
from direction5freq.theory.recourse_certificate import compute_surplus_loss_recourse_certificate
from direction5freq.theory.terminal_set import compute_local_rpi_certificate


LOCK = REPO / "configs/direction5_accr/a5_theory_lock.yaml"
A3_LOCK = REPO / "configs/direction5_accr/a3_probe_lock.yaml"
RESULTS = REPO / "results_accr/A5"
THEORY = REPO / "research_outputs_accr/07_THEORY"
PROGRESS = REPO / "progress_accr/A5.json"


def _probe_separation(a3_lock: dict, residual_bound: float) -> dict:
    selected = json.loads((REPO / "results_accr/A3/A3_SUMMARY.json").read_text("utf-8"))["selected_probe_policy"]
    probe = ProbeCandidate(
        selected["probe_id"], float(selected["amplitude_pu"]),
        np.asarray(selected["normalized_sequence"], dtype=float),
    )
    models = candidate_models(a3_lock)
    outputs = [simulate_hypothesis(
        model, probe, period_s=float(a3_lock["period_s"]),
        dt_s=float(a3_lock["physical_dt_s"]), base_power_pu=0.05,
    ) for model in models]
    separations = []
    for first in range(len(models)):
        for second in range(first + 1, len(models)):
            count = min(len(outputs[first]), len(outputs[second]))
            separations.append(float(np.max(np.abs(outputs[first][:count] - outputs[second][:count]))))
    values = np.asarray(separations)
    return {
        "pair_count": int(len(values)),
        "noise_diameter_pu": float(2.0 * residual_bound),
        "separable_pair_count": int(np.sum(values > 2.0 * residual_bound)),
        "separable_pair_fraction": float(np.mean(values > 2.0 * residual_bound)),
        "maximum_output_separation_pu": float(np.max(values)),
        "all_pair_separations": values,
    }


def _contract_and_terminal(lock: dict) -> tuple[dict, dict, list[dict], dict[str, np.ndarray]]:
    plant = PlantAFull()
    observation = plant.public_observation(0.0, plant.equilibrium(), np.zeros(4))
    base = DeliverabilitySetMembership(
        plant.parameters.bess.contract, float(lock["period_s"])
    ).update(0.0, np.zeros(2), np.zeros(2))
    certified = replace(
        base,
        performance_power_pu=np.array((0.065, 0.065)),
        performance_ramp_pu_per_s=np.array((0.040, 0.040)),
        delay_interval_s=np.array(((0.0, 0.8), (0.0, 0.8))),
    )
    load = np.array((0.045, 0.030))
    domain = DomainSupervisor(plant.parameters).classify(load, observation.measured_soc)
    inputs = DCSVInput(observation, load, certified, domain)
    controller = DCSVContractRecourseMPC(
        float(lock["period_s"]), int(lock["horizon_steps"]), plant.parameters
    )
    result = controller.propose(inputs)
    contract = compute_contract_branch_certificate(
        controller, inputs, result, dense_delay_points=int(lock["dense_delay_points"])
    )
    recourse = compute_surplus_loss_recourse_certificate(controller, result)
    terminal_rows = []
    arrays: dict[str, np.ndarray] = {}
    for index, terminal_load in enumerate(lock["terminal_loads_pu"]):
        certificate = compute_local_rpi_certificate(float(lock["period_s"]), np.asarray(terminal_load))
        terminal_rows.append({
            "load0_pu": terminal_load[0], "load1_pu": terminal_load[1],
            "admissible": certificate.admissible,
            "nonempty": certificate.nonempty,
            "closed_loop_spectral_radius": certificate.closed_loop_spectral_radius,
            "absolute_closed_loop_spectral_radius": certificate.absolute_closed_loop_spectral_radius,
            "invariance_residual": certificate.invariance_residual,
            "minimum_state_margin_pu": certificate.minimum_state_margin_pu,
            "minimum_input_margin_pu": certificate.minimum_input_margin_pu,
            "claim_level": certificate.claim_level,
        })
        arrays[f"terminal_{index}_radius"] = certificate.error_box_radius
        arrays[f"terminal_{index}_gain"] = certificate.terminal_feedback_gain
        arrays[f"terminal_{index}_equilibrium"] = certificate.equilibrium_state
    return asdict(contract), asdict(recourse), terminal_rows, arrays


def _write_documents(status: dict) -> None:
    THEORY.mkdir(parents=True, exist_ok=True)
    THEORY.joinpath("ASSUMPTIONS.md").write_text("""# ACCR certificate assumptions

1. The true command-to-actual capability belongs to the registered finite candidate set and contains the contract floor during a certificate validity interval.
2. Measurement/model error is bounded by the registered residual bound; timestamps and actual BESS POI power are causal and correct.
3. A capability certificate expires after 40 s and is revoked on a change-reset; no certificate survives an unannounced loss as a hard floor.
4. The A3 probe safety result covers the full nonlinear Plant A, every registered candidate and the no-surplus branch over the registered finite horizon.
5. Contract-branch replay uses the registered Plant-A prediction model, delay grid, measured SoC and quiescent initial command pipeline.
6. The local terminal RPI result applies only near a load-parameterized Plant-A equilibrium; it is not a native ANDES DAE or global recursive-feasibility theorem.
7. Surplus loss is detected by the next control cycle; only then may SG/slow-reserve future recourse differ by branch.
""", encoding="utf-8")
    THEORY.joinpath("THEOREMS_AND_PROOFS.md").write_text(r"""# ACCR P1--P7 theorems and bounded proofs

## P1 — command allocation neutrality

For each area, the probe adds `[-q, +q]` to `[SG, BESS]`; therefore `[1,1][-q,+q]^T=0`. This is command-level neutrality only and does not assert zero instantaneous actual-power effect.

## P2 — conditional set containment

Let the true hypothesis be in the prior candidate set and let its prediction residual be bounded by epsilon. The membership update deletes only hypotheses whose residual exceeds epsilon. Hence the true hypothesis remains. If the set becomes empty or a change-reset occurs, the implementation revokes the old certificate instead of asserting containment.

## P3 — registered finite-horizon probe safety

The selected probe was replayed on the full nonlinear Plant A for every registered power/ramp/delay candidate and the no-surplus interpretation. Frequency, ACE, tie and device inequalities were evaluated directly. This certifies only that registered finite experiment, not arbitrary models or infinite time.

## P4 — sufficient distinguishability

For hypotheses h and j with bounded output errors of radius epsilon, `||y_h-y_j||_infinity > 2 epsilon` makes their error tubes disjoint. At most one can remain consistent with a measurement, so the other is excluded. Pairs that do not satisfy this separation are deliberately not claimed distinguishable.

## P5 — finite capability lower bound

When P2 holds over a stationary interval, the minimum power and ramp and maximum delay over the retained set are conservative bounds for the true hypothesis. They are valid only until the registered expiry or earlier reset; energy remains a measured-SoC constraint, not a hidden certificate dimension.

## P6 — unannounced loss boundary

Two worlds can share the complete public history through a decision instant yet differ by an unannounced capability collapse. Causality forces the same command in both; a command feasible in the retained world can be infeasible in the collapsed world. Same-instant unconditional protection is impossible beyond the contract and the method therefore uses next-cycle loss recourse.

## P7 — contract terminal and surplus-loss recourse

The contract branch directly replays guaranteed power/ramp, dense registered delays, predicted physical power/ramp/energy and frequency/ACE/tie inequalities. The local RPI boxes verify `|Acl|z+w<=z` with positive state/input margins around load-dependent equilibria. Both branches share the current action; from the next step, registered SG and slow-reserve headroom dominates the removed certified surplus. These are conditional finite-horizon and local certificates, not global recursive safety.

## Allowed claim

`registered-set finite-horizon safe active capability certification with a separately certified contract fallback and next-cycle surplus-loss recourse`.
""", encoding="utf-8")
    THEORY.joinpath("CERTIFICATE_STATUS.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    THEORY.joinpath("REPRODUCE_CERTIFICATES.py").write_text("""from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'src'))
from scripts.direction5_accr.run_a5_certificates import main

main()
""", encoding="utf-8")


def main() -> None:
    lock = yaml.safe_load(LOCK.read_text("utf-8"))
    a3_lock = yaml.safe_load(A3_LOCK.read_text("utf-8"))
    a3_safety = pd.read_csv(REPO / "results_accr/A3/A3_ALL_CANDIDATE_SAFETY.csv")
    a3_validation = pd.read_csv(REPO / "results_accr/A3/A3_VALIDATION_EPISODES.csv")
    selected_probe = json.loads(
        (REPO / "results_accr/A3/A3_SUMMARY.json").read_text("utf-8")
    )["selected_probe_policy"]
    separation = _probe_separation(a3_lock, float(lock["active_filter_residual_bound_pu"]))
    contract, recourse, terminal, arrays = _contract_and_terminal(lock)
    impossibility = construct_same_instant_impossibility_witness(
        np.array((0.060, 0.060)), np.array((0.065, 0.065)), np.array((0.040, 0.040))
    )
    p_status = {
        "P1": bool(abs(sum(selected_probe["normalized_sequence"])) <= 1e-12),
        "P2": bool(a3_validation.truth_contained.all()),
        "P3": bool(a3_safety.safe.all() and not a3_safety.hard_violation.any()),
        "P4": bool(separation["separable_pair_count"] > 0),
        "P5": bool(a3_validation.truth_contained.all() and not a3_validation.false_optimism.any()),
        "P6": bool(impossibility.impossibility_established),
        "P7": bool(
            contract["finite_horizon_certified"]
            and recourse["certified"]
            and all(row["admissible"] for row in terminal)
        ),
    }
    status = {
        "project": "DIRECTION5", "stage": "A5",
        "status": "PASS" if all(p_status.values()) else "FAIL",
        "theorems": {name: ("PASS" if passed else "FAIL") for name, passed in p_status.items()},
        "claim_level": lock["claim_level"],
        "global_recursive_safety_claimed": False,
        "native_plant_b_theory_claimed": False,
        "finite_horizon_probe_candidates": int(len(a3_safety)),
        "finite_horizon_probe_safe_candidates": int(a3_safety.safe.sum()),
        "empirical_certificate_coverage": float(a3_validation.truth_contained.mean()),
        "distinguishable_pair_fraction": separation["separable_pair_fraction"],
        "contract_branch_certified": bool(contract["finite_horizon_certified"]),
        "surplus_loss_recourse_certified": bool(recourse["certified"]),
        "terminal_sets_admissible": int(sum(row["admissible"] for row in terminal)),
        "terminal_sets_total": int(len(terminal)),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(terminal).to_csv(RESULTS / "A5_TERMINAL_CERTIFICATES.csv", index=False)
    RESULTS.joinpath("A5_CONTRACT_BRANCH_CERTIFICATE.json").write_text(json.dumps(contract, indent=2, default=lambda x: x.tolist()) + "\n", encoding="utf-8")
    RESULTS.joinpath("A5_SURPLUS_LOSS_RECOURSE.json").write_text(json.dumps(recourse, indent=2, default=lambda x: x.tolist()) + "\n", encoding="utf-8")
    RESULTS.joinpath("A5_IMPOSSIBILITY_WITNESS.json").write_text(json.dumps(asdict(impossibility), indent=2, default=lambda x: x.tolist()) + "\n", encoding="utf-8")
    RESULTS.joinpath("A5_SUMMARY.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    arrays["probe_pair_separations_pu"] = separation.pop("all_pair_separations")
    arrays["p_status"] = np.asarray(list(p_status.values()), dtype=np.int8)
    THEORY.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(THEORY / "CERTIFICATE_DATA.npz", **arrays)
    _write_documents(status)
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps({
        "stage": "A5", "status": status["status"],
        "summary": "results_accr/A5/A5_SUMMARY.json",
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2))
    if status["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
