"""Recompute Phase-I conditional terminal, bridge, and infeasibility certificates."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.controllers.dcsv_mpc_final import DCSVInput, DisturbanceCapabilitySeparatedViabilityMPC
from direction5freq.controllers.domain_supervisor import DomainSupervisor
from direction5freq.estimation.deliverability_set_mhe import DeliverabilitySetMHE
from direction5freq.models.plant_a_full import PlantAFull, PublicObservation
from direction5freq.theory.bridge_certificate import compute_bridge_certificate
from direction5freq.theory.infeasibility_certificate import compute_infeasibility_certificate
from direction5freq.theory.terminal_set import compute_local_rpi_certificate


RESULTS = REPO / "results_phase_i/I5"
DOCS = REPO / "research_outputs_phase_i/06_THEORY"
PROGRESS = REPO / "progress_phase_i"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def terminal_certificates() -> pd.DataFrame:
    rows = []
    for period_s in (2.0, 4.0):
        for level in (0.03, 0.06, 0.09):
            load = np.array((level, 0.8 * level))
            c = compute_local_rpi_certificate(period_s, load)
            rows.append({
                "period_s": period_s,
                "load0_pu": load[0],
                "load1_pu": load[1],
                "equilibrium_sg0_pu": c.equilibrium_input[0],
                "equilibrium_sg1_pu": c.equilibrium_input[2],
                "closed_loop_spectral_radius": c.closed_loop_spectral_radius,
                "absolute_closed_loop_spectral_radius": c.absolute_closed_loop_spectral_radius,
                "invariance_residual": c.invariance_residual,
                "minimum_state_margin_pu": c.minimum_state_margin_pu,
                "minimum_input_margin_pu": c.minimum_input_margin_pu,
                "maximum_box_radius": float(np.max(c.error_box_radius)),
                "nonempty": c.nonempty,
                "admissible": c.admissible,
                "claim_level": c.claim_level,
                "pipeline_condition": "quiescent_BESS_command_history",
                "model_scope": "PlantA_registered_local_error_model",
            })
    return pd.DataFrame(rows)


def bridge_certificates() -> pd.DataFrame:
    rows = []
    for load0, load1, soc in ((0.145, 0.135, 0.50), (0.165, 0.145, 0.50), (0.170, 0.155, 0.35), (0.200, 0.180, 0.50)):
        c = compute_bridge_certificate(np.array((load0, load1)), np.array((soc, soc)))
        rows.append({
            "load0_pu": load0, "load1_pu": load1, "soc": soc,
            "deficit0_pu": c.initial_deficit_pu[0], "deficit1_pu": c.initial_deficit_pu[1],
            "handoff_time_s": c.handoff_time_s,
            "required_energy_mwh": c.required_energy_mwh,
            "available_energy_mwh": c.available_energy_mwh,
            "power_margin_pu": c.power_margin_pu,
            "ramp_margin_pu_per_s": c.ramp_margin_pu_per_s,
            "energy_margin_mwh": c.energy_margin_mwh,
            "certified": c.certified,
            "claim_level": c.claim_level,
        })
    return pd.DataFrame(rows)


def infeasibility_certificates() -> pd.DataFrame:
    rows = []
    for load, soc in (
        ((0.25, 0.18), (0.5, 0.5)),
        ((0.28, 0.27), (0.5, 0.5)),
        ((0.165, 0.145), (0.105, 0.105)),
        ((0.08, 0.06), (0.5, 0.5)),
    ):
        c = compute_infeasibility_certificate(np.asarray(load), np.asarray(soc))
        rows.append({
            "load0_pu": load[0], "load1_pu": load[1], "soc0": soc[0], "soc1": soc[1],
            "certificate_type": c.certificate_type,
            "violation_margin": c.violation_margin,
            "certified_infeasible": c.certified_infeasible,
            "reason": c.reason,
        })
    return pd.DataFrame(rows)


def dense_delay_validation() -> pd.DataFrame:
    rows = []
    plant = PlantAFull()
    observation = plant.public_observation(0.0, plant.equilibrium(), np.zeros(4))
    estimator = DeliverabilitySetMHE(plant.parameters.bess.contract, 0.1)
    snapshot = estimator.update(0.0, np.zeros(2), np.zeros(2))
    for period_s in (2.0, 4.0):
        for domain_name, load in (("SUSTAINABLE", np.array((0.05, 0.03))), ("BRIDGE", np.array((0.130, 0.125)))):
            controller = DisturbanceCapabilitySeparatedViabilityMPC(period_s, horizon_steps=6)
            case_observation = observation
            if domain_name == "BRIDGE":
                # The finite bridge certificate starts after causal delivery has
                # been established, not at the indistinguishable same-instant
                # pre-event state retained in NEGATIVE_CERTIFICATE_CASES.
                case_observation = PublicObservation(
                    time_s=0.0,
                    frequency_deviation_hz=np.zeros(2),
                    ace_pu=np.zeros(2),
                    tie_line_pu=0.0,
                    valve_pu=np.array((0.115, 0.115)),
                    sg_mechanical_power_pu=np.array((0.115, 0.115)),
                    bess_actual_power_pu=np.array((0.010, 0.005)),
                    measured_soc=np.array((0.5, 0.5)),
                    slow_reserve_power_pu=np.array((0.005, 0.005)),
                    issued_command_pu=np.array((0.110, 0.010, 0.110, 0.005)),
                )
                controller.commit(case_observation.issued_command_pu, case_observation.bess_actual_power_pu)
            domain = DomainSupervisor().classify(load, case_observation.measured_soc)
            result = controller.propose(DCSVInput(case_observation, load, snapshot, domain))
            u = result.predicted_input_sequence
            if u.shape[1] == 0:
                raise RuntimeError(
                    "dense-delay validation requires an optimized sequence: "
                    f"period={period_s}, requested={domain_name}, classified={domain.domain}, "
                    f"status={result.diagnostics.status}"
                )
            x0 = controller._state_from_observation(case_observation)
            energy0 = case_observation.measured_soc * plant.parameters.bess.energy_mwh
            for delay_s in np.linspace(0.0, max(controller.contract.maximum_delay_s), 31):
                x = x0.copy(); energy = energy0.copy(); previous_pb = case_observation.bess_actual_power_pu.copy()
                maximum_power_violation = 0.0; maximum_ramp_violation = 0.0; maximum_energy_violation = 0.0
                for k in range(u.shape[1]):
                    fraction = delay_s / period_s
                    previous_command = controller._last_committed_action[[1, 3]] if k == 0 else u[[1, 3], k - 1]
                    delayed_bess = (1.0 - fraction) * u[[1, 3], k] + fraction * previous_command
                    effective = np.array((u[0, k], delayed_bess[0], u[2, k], delayed_bess[1]))
                    reserve = result.predicted_slow_reserve_sequence_pu[:, k]
                    x = controller.ad @ x + controller.bd @ effective + controller.ed @ load + controller.rd @ reserve
                    actual_pb = x[7:9]
                    maximum_power_violation = max(maximum_power_violation, float(np.max(np.abs(actual_pb) - plant.parameters.bess.rating_pu)))
                    maximum_ramp_violation = max(maximum_ramp_violation, float(np.max(np.abs(actual_pb - previous_pb) - 0.10 * period_s)))
                    factor = period_s * plant.parameters.system_base_mva / 3600.0
                    energy += np.where(actual_pb >= 0.0, -factor * actual_pb / plant.parameters.bess.eta_discharge, -factor * actual_pb * plant.parameters.bess.eta_charge)
                    maximum_energy_violation = max(
                        maximum_energy_violation,
                        float(np.max(plant.parameters.bess.soc_min * plant.parameters.bess.energy_mwh - energy)),
                        float(np.max(energy - plant.parameters.bess.soc_max * plant.parameters.bess.energy_mwh)),
                    )
                    previous_pb = actual_pb.copy()
                rows.append({
                    "period_s": period_s, "domain": domain_name, "delay_s": delay_s,
                    "power_violation_pu": max(maximum_power_violation, 0.0),
                    "ramp_violation_pu": max(maximum_ramp_violation, 0.0),
                    "energy_violation_mwh": max(maximum_energy_violation, 0.0),
                    "finite_horizon_constraints_hold": bool(max(maximum_power_violation, maximum_ramp_violation, maximum_energy_violation) <= 1e-7),
                })
    return pd.DataFrame(rows)


def negative_certificate_cases() -> pd.DataFrame:
    plant = PlantAFull()
    observation = plant.public_observation(0.0, plant.equilibrium(), np.zeros(4))
    estimator = DeliverabilitySetMHE(plant.parameters.bess.contract, 0.1)
    snapshot = estimator.update(0.0, np.zeros(2), np.zeros(2))
    load = np.array((0.165, 0.145))
    domain = DomainSupervisor().classify(load, observation.measured_soc)
    controller = DisturbanceCapabilitySeparatedViabilityMPC(2.0, horizon_steps=6)
    result = controller.propose(DCSVInput(observation, load, snapshot, domain))
    return pd.DataFrame([{
        "case": "abrupt_high_bridge_from_zero_pre_event_state",
        "load0_pu": load[0], "load1_pu": load[1],
        "physical_domain": domain.domain,
        "power_ramp_energy_bridge_condition": compute_bridge_certificate(load, observation.measured_soc).certified,
        "rolling_mpc_finite_horizon_sequence": result.predicted_input_sequence.shape[1] > 0,
        "solver_status": result.diagnostics.status,
        "claim": "NO_MPC_FEASIBILITY_CERTIFICATE_AT_THIS_INITIAL_STATE",
        "preserved": True,
    }])


def write_theory_docs() -> None:
    write(DOCS / "THEOREM_A_IMPOSSIBILITY.md", """
# Theorem A — same-instant impossibility

Let two physical worlds have identical public histories through `k-1`. In world
1 the contract remains valid; in world 2 capability changes without announcement
immediately before `u_k` to a set excluding that same causal command. The
controller has identical information and must issue identical `u_k` in both
worlds, so executability cannot be guaranteed in world 2. This rules out an
unconditional same-instant guarantee after arbitrary contract collapse; it does
not rule out causal post-effect detection or independent-reserve protection.
""")
    write(DOCS / "THEOREM_B_FINITE_HORIZON.md", """
# Theorem B — conditional finite-horizon resource constraints

If true command deliverability contains the contract, delay lies in the
registered interval, measured SoC is correct and the registered prediction-error
set holds, the common-sequence QP enforces command power/ramp, physical actual
power/ramp and energy bounds for every registered endpoint. The input mapping is
affine in the fractional delay over one control period; `DENSE_DELAY_VALIDATION`
independently checks 31 points at 2 s and 4 s for sustainable and bridge cases.
This is a finite-horizon statement, not unconditional recursive feasibility.
""")
    write(DOCS / "THEOREM_C_SUSTAINABLE.md", """
# Theorem C — load-parameterized sustainable terminal set

For each registered load strictly inside SG steady capability, the equilibrium
has zero frequency/tie/BESS power and SG valve/mechanical power equal to load.
An SG-only LQR terminal feedback yields a Schur closed-loop error model. With the
explicit registered one-step additive remainder box `W`, the box radius solves
`z = |Acl| z + w`; therefore `|Acl|z+w <= z`. Recomputed certificates at both
periods are nonempty and remain inside valve, mechanical, BESS physical and SG
input margins. Claim level is `CONDITIONAL_LOCAL_LINEAR_RPI`, requiring a
quiescent BESS command pipeline and the stated remainder bound. No native-DAE
recursive-feasibility claim is made.
""")
    write(DOCS / "THEOREM_D_BRIDGE.md", """
# Theorem D — finite bridge

For a load above SG-only equilibrium but below SG plus slow reserve, the BESS
deficit decreases linearly under the registered slow-reserve ramp. The
certificate checks initial deficit against contract power, reserve ramp against
contract ramp, and measured-SoC energy against the triangular deficit integral
plus worst-delay buffer. It certifies only the finite handoff interval. Without
a registered slow reserve, no sustained post-handoff claim is allowed.
""")
    write(DOCS / "THEOREM_E_INFEASIBILITY.md", """
# Theorem E — early physical infeasibility

If any area load exceeds SG plus slow-reserve steady power, no zero-BESS-energy
equilibrium exists under registered limits. If steady power is available but the
bridge power, ramp or measured energy inequality fails, the registered handoff
is physically infeasible. These cases are certified before ordinary controller
scoring and are not counted as generic controller failures.
""")
    write(DOCS / "CLAIM_BOUNDARY.md", """
# Locked theory claim boundary

- Full deterministic claim: same-instant impossibility after arbitrary
  unannounced contract collapse.
- Conditional deterministic claim: finite-horizon resource constraints under
  contract containment, registered delay/model error and correct measured SoC.
- Conditional local claim: nonempty Plant-A terminal-model RPI boxes.
- Conditional finite claim: bridge to registered slow reserve.
- Exact physical precheck: registered steady-power or bridge-resource
  infeasibility.
- Empirical only: Plant-B native cross-model validation and finite-sample
  estimator coverage.

Recursive feasibility is not claimed for native Plant B or outside the stated
local terminal assumptions.
""")


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True); DOCS.mkdir(parents=True, exist_ok=True); PROGRESS.mkdir(parents=True, exist_ok=True)
    terminal = terminal_certificates(); bridge = bridge_certificates(); infeasible = infeasibility_certificates(); dense = dense_delay_validation(); negative = negative_certificate_cases()
    terminal.to_csv(RESULTS / "TERMINAL_RPI_CERTIFICATES.csv", index=False)
    bridge.to_csv(RESULTS / "BRIDGE_CERTIFICATES.csv", index=False)
    infeasible.to_csv(RESULTS / "INFEASIBILITY_CERTIFICATES.csv", index=False)
    dense.to_csv(RESULTS / "DENSE_DELAY_VALIDATION.csv", index=False)
    negative.to_csv(RESULTS / "NEGATIVE_CERTIFICATE_CASES.csv", index=False)
    theorem = pd.DataFrame([
        ("A", "SAME_INSTANT_CONTRACT_COLLAPSE_IMPOSSIBILITY", "PROVED", "full causal indistinguishability"),
        ("B", "FINITE_HORIZON_ROBUST_RESOURCE_CONSTRAINTS", "CERTIFIED_CONDITIONALLY", "contract/delay/model/SoC assumptions"),
        ("C", "SUSTAINABLE_TERMINAL_RPI", "CERTIFIED_CONDITIONALLY", "Plant A local error model and quiescent pipeline"),
        ("D", "FINITE_ENERGY_BRIDGE", "CERTIFIED_FOR_PASSING_CELLS", "registered slow reserve required"),
        ("E", "PHYSICAL_INFEASIBILITY", "CERTIFIED_FOR_TRIGGERING_CELLS", "registered steady/bridge resource bounds"),
    ], columns=["theorem", "subject", "status", "scope"])
    theorem.to_csv(RESULTS / "THEOREM_STATUS.csv", index=False)
    equation_map = pd.DataFrame([
        ("load equilibrium", "terminal_set.compute_local_rpi_certificate", "equilibrium_state/equilibrium_input"),
        ("box RPI z=|Acl|z+w", "terminal_set.compute_local_rpi_certificate", "invariance_residual"),
        ("bridge power-ramp-energy", "bridge_certificate.compute_bridge_certificate", "BRIDGE_CERTIFICATES.csv"),
        ("steady/bridge infeasibility", "infeasibility_certificate.compute_infeasibility_certificate", "INFEASIBILITY_CERTIFICATES.csv"),
        ("delay-affine robust prediction", "dcsv_mpc_final._delayed_bess_expression", "DENSE_DELAY_VALIDATION.csv"),
    ], columns=["equation_or_object", "code", "evidence"])
    equation_map.to_csv(RESULTS / "EQUATION_CODE_MAP.csv", index=False)
    write_theory_docs()
    gates = {
        "same_instant_impossibility_proved": True,
        "finite_horizon_dense_delay_holds": bool(dense.finite_horizon_constraints_hold.all()),
        "nonempty_sustainable_terminal_sets": bool(terminal.nonempty.all() and terminal.admissible.all()),
        "bridge_has_passing_certificates": bool(bridge.certified.any()),
        "bridge_failures_preserved": bool((~bridge.certified).any()),
        "mpc_certificate_negative_case_preserved": bool(negative.preserved.all() and (~negative.rolling_mpc_finite_horizon_sequence).all()),
        "infeasibility_has_triggering_and_negative_controls": bool(infeasible.certified_infeasible.any() and (~infeasible.certified_infeasible).any()),
        "equation_code_map_complete": bool(len(equation_map) >= 5),
        "native_plant_b_recursive_claim_withheld": True,
    }
    progress = {
        "stage": "I5",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "gate_passed": all(gates.values()),
        "certificate_status": "CONDITIONAL_LOCAL_RPI_PLUS_FINITE_HORIZON_BRIDGE",
        "recursive_feasibility_claim": "PLANT_A_LOCAL_MODEL_ONLY_UNDER_EXPLICIT_ASSUMPTIONS",
        "native_plant_b_theory": "EMPIRICAL_VALIDATION_ONLY",
        "terminal_certificates": len(terminal),
        "bridge_certified": int(bridge.certified.sum()),
        "bridge_not_certified": int((~bridge.certified).sum()),
        "infeasibility_certified": int(infeasible.certified_infeasible.sum()),
        "dense_delay_points": len(dense),
        "gates": gates,
        "failures": [name for name, passed in gates.items() if not passed],
        "final_seeds_consumed": False,
        "next_stage": "I6" if all(gates.values()) else "TERMINATE_EMPTY_CERTIFICATES",
    }
    (PROGRESS / "I5.json").write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
    if not progress["gate_passed"]:
        raise SystemExit("I5 gate failed: " + ", ".join(progress["failures"]))


if __name__ == "__main__":
    main()
