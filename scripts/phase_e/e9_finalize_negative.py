"""Create binding Phase-E negative status after the fatal G6 Gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
FINAL = ROOT / "research_outputs_phase_e" / "final"
RESULT = ROOT / "results_phase_e" / "E9"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    FINAL.mkdir(parents=True, exist_ok=True); RESULT.mkdir(parents=True, exist_ok=True)
    e3 = json.loads((ROOT / "progress_phase_e" / "E3_full.json").read_text(encoding="utf-8"))
    e4 = json.loads((ROOT / "progress_phase_e" / "E4.json").read_text(encoding="utf-8"))
    e5 = json.loads((ROOT / "progress_phase_e" / "E5.json").read_text(encoding="utf-8"))
    e6 = json.loads((ROOT / "progress_phase_e" / "E6_full.json").read_text(encoding="utf-8"))
    stopped = {
        "status": "STOPPED", "gate_passed": None,
        "reason": "fatal G6 METHOD_NOT_SUPPORTED_BY_EVIDENCE",
        "not_evaluated_is_not_failure": True, "next_stage": "E9",
    }
    write_json(ROOT / "progress_phase_e" / "E7.json", {
        "stage": "E7", "goal": "Theory and code-matched certificates", **stopped,
        "available_pre_stop_evidence": {
            "finite_horizon_tube_containment": e6["gate_components"]["tube_numerical_containment"],
            "forced_failure_sg_backup": e6["gate_components"]["forced_failure_reaches_sg_backup"],
        },
        "claim_boundary": "No recursive-feasibility or unconditional robust-safety theorem is claimed.",
    })
    write_json(ROOT / "progress_phase_e" / "E8.json", {
        "stage": "E8", "goal": "Locked final known/OOD experiments", **stopped,
        "final_manifest_created": False, "final_seeds_consumed": False,
        "known_results": "not_evaluated", "ood_results": "not_evaluated",
    })
    gates = pd.DataFrame([
        ("G0", "Baseline forensic freeze", "PASS", "Phase D frozen; old H2 invalidated by closed-loop/evaluation defects"),
        ("G1", "Novelty and scientific question", "PASS", "conditional intersection supported; 75 verified records"),
        ("G2", "Physics and stable closed loop", "PASS", "Plant A and native ANDES Plant B passed"),
        ("G3", "Oracle materiality", "PASS", "qualified O2; 5 mechanisms and 3 SG tensions; A/B direction consistent"),
        ("G4", "Passive capability information", "FAIL", "0/3 estimators met timing and contraction; continue to E5"),
        ("G5", "Safe active information", "FAIL", "unsafe/costly and 0/5 timing; branch R selected"),
        ("G6", "Selected method validation", "FAIL_FATAL", "1.846% solver infeasibility exceeds 1% despite performance gains"),
        ("G7", "Theory certificate", "NOT_EVALUATED", "stopped after fatal G6; no theorem claim"),
        ("G8", "Final known/OOD", "NOT_EVALUATED", "stopped before final lock; no final seeds consumed"),
        ("G9", "Review package", "PENDING", "set to PASS only by package verifier"),
    ], columns=["gate", "name", "status", "evidence"])
    gates.to_csv(RESULT / "ALL_GATES.csv", index=False)
    hypotheses = pd.DataFrame([
        ("H1", "SUPPORTED_DEVELOPMENT", "qualified current-capability Oracle materially improves control in Plant A/B"),
        ("H2", "FALSIFIED", "natural public I/O did not contract/update capability sets before Tcrit"),
        ("H3", "FALSIFIED", "informative active probe increased failures/performance cost and exceeded mileage budget"),
        ("H4", "NOT_SUPPORTED_BY_G6", "branch R improved continuous metrics but exceeded solver-infeasibility Gate; final not run"),
        ("H5", "NOT_EVALUATED", "E7 stopped; only finite-horizon numerical tube/fallback checks exist"),
    ], columns=["hypothesis", "status", "evidence"])
    hypotheses.to_csv(RESULT / "HYPOTHESES_STATUS.csv", index=False)
    failure_ledger = pd.DataFrame([
        ("E2", "physical/controller", "FAILED_ATTEMPT_1_LQI_LIMIT_CYCLE", "retained", "aggressive LQI created 4 s nonlinear limit cycle"),
        ("E3", "scenario_generation", "PILOT_ATTEMPT_1_NO_LOAD", "repaired_and_retained", "pilot resize generated no-load only"),
        ("E3", "solver", "ORACLE_FAILED_SOLVES", "retained", "22 episodes contained at least one nonfinite failed-solve residual"),
        ("E4", "scientific", "PASSIVE_INFORMATION_NOT_SUPPORTED", "binding", "no estimator met timing and width Gate"),
        ("E5", "physical/scientific", "ACTIVE_IDENTIFICATION_NOT_SAFE", "binding", "failures, 261/280% IAE increases, 3.68 pu mileage"),
        ("E6", "solver/method", "METHOD_NOT_SUPPORTED_BY_EVIDENCE", "fatal_binding", "1.846% infeasibility >1%, concentrated in delay"),
        ("E7", "not_evaluated", "STOPPED_AFTER_FATAL_G6", "not_failure", "theory development prohibited after stop"),
        ("E8", "not_evaluated", "STOPPED_AFTER_FATAL_G6", "not_failure", "known/OOD final not run and no final seeds used"),
    ], columns=["stage", "failure_class", "code", "disposition", "detail"])
    failure_ledger.to_csv(RESULT / "FAILURE_LEDGER.csv", index=False)
    validation = e6["tests"]["validation_comparison"]
    final_status = {
        "schema": "direction1.phase_e.final_status.v1",
        "project": "DIRECTION1",
        "phase": "E_SCIENCE_RECOVERY_AND_CAPABILITY_CONTROL",
        "final_research_status": "METHOD_NOT_SUPPORTED_BY_EVIDENCE",
        "fatal_stage": "E6",
        "selected_branch": "R",
        "selected_method": "Capability-Set Robust Tube MPC",
        "best_deployable_baseline": e3["best_deployable_baseline"],
        "gates": {row.gate: row.status for row in gates.itertuples()},
        "hypotheses": {row.hypothesis: row.status for row in hypotheses.itertuples()},
        "plant_a_validation": {
            "proposed_success_rate": validation["proposed_success_rate"],
            "baseline_success_rate": validation["baseline_success_rate"],
            "frequency_iae_improvement": validation["frequency_iae_hz_s_improvement"],
            "ace_iae_improvement": validation["ace_iae_pu_s_improvement"],
            "tie_iae_improvement": validation["tie_iae_pu_s_improvement"],
            "solver_infeasibility": e6["tests"]["solver_infeasibility"],
            "solver_time_p99_s": e6["tests"]["solver_time_p99_s"],
        },
        "plant_b_validation": {
            "direction_consistent": e6["gate_components"]["plant_a_b_direction_consistent"],
            "rows": e6["tests"]["plant_b_rows"],
        },
        "known_results": "not_evaluated_after_fatal_G6",
        "ood_results": "not_evaluated_after_fatal_G6",
        "final_manifest_locked": False,
        "final_seeds_consumed": False,
        "final_seeds_used_for_tuning": False,
        "failures_deleted": False,
        "ordinary_controller_reads_truth": False,
        "oracle_evaluation_only": True,
        "most_severe_limitation": "Delay-capability validation caused 1.846% rolling-QP infeasibility, exceeding the preregistered 1% Gate; no final known/OOD claim is authorized.",
        "claim_boundary": "H1 materiality is supported on development/validation evidence, H2/H3 are falsified, and the selected branch-R method is not supported for final claims.",
        "next_step_boundary": "Stop for external review. Do not implement or tune another controller under this Goal.",
    }
    write_json(FINAL / "FINAL_STATUS.json", final_status)
    (FINAL / "FINAL_RESULTS_INTERPRETATION.md").write_text(f"""# Final results interpretation

Phase E recovered a stable physical platform and a qualified current-capability Oracle. H1 is supported: O2 qualified at 97.75% of episodes with successful-solve residual p99 2.23e-7, and material cells covered all five mechanisms and all three SG tensions with Plant A/B direction consistency.

Natural closed-loop data did not support passive capability sets (H2 falsified). Safe active probing produced information in three mechanisms but increased frequency IAE by 261%, ACE IAE by 280%, physical failures, and exceeded the mileage budget (H3 falsified). The immutable Gate rule therefore selected branch R.

Branch R passed success, performance, real-time, tube, fallback, and Plant A/B direction components. On validation, success was {validation['proposed_success_rate']:.1%} versus {validation['baseline_success_rate']:.1%}; paired improvements were {validation['frequency_iae_hz_s_improvement']:.1%} frequency IAE, {validation['ace_iae_pu_s_improvement']:.1%} ACE IAE, and {validation['tie_iae_pu_s_improvement']:.1%} tie-line IAE. Nevertheless, solver infeasibility was {e6['tests']['solver_infeasibility']:.3%}, above the 1% Gate. G6 is fatal, so the binding result is **METHOD_NOT_SUPPORTED_BY_EVIDENCE**.

E7 and E8 are explicitly not evaluated. No final seed, known/OOD final comparison, recursive-feasibility theorem, or robust-safety claim is supplied.
""", encoding="utf-8")
    (FINAL / "SUPPORTED_AND_UNSUPPORTED_CLAIMS.md").write_text("""# Supported and unsupported claims

Supported: the repaired 2/4 s Plant A and native ANDES Plant B are stable in their registered tests; current capability knowledge is materially valuable; passive natural I/O is insufficient; the tested active probe is unsafe/costly; branch R has strong conditional continuous-metric gains and real-time solves in successful cases.

Unsupported: passive-identifiable capability labels; safe active identification; a final-performing proposed controller; final known/OOD generalization; unconditional recursive feasibility; unconditional robust constraint satisfaction; global optimality of O2; equivalence of Plant A and Plant B.
""", encoding="utf-8")
    (FINAL / "PAPER_OUTLINE.md").write_text("""# Paper outline for the retained negative result

1. Scientific question and correction of the invalid Phase-D Gate.
2. Stable two-area and native multi-machine platforms.
3. Fair current-capability Oracle and materiality evidence.
4. Passive structural/excitation limits and causal Tcrit timing.
5. Safety-information tradeoff that rejects active probing.
6. Gate-selected robust tube MPC, its conditional gains, and fatal delay-solver limitation.
7. Negative conclusion, reproducibility, and boundary for future work.
""", encoding="utf-8")
    (FINAL / "REVIEWER_LIMITATIONS.md").write_text("""# Reviewer-style limitations

The Oracle online implementation is a real-time-iteration nonlinear multiple-shooting approximation with independent nonlinear multi-start qualification, not a globally optimal exact Oracle. E3 sensitivity did not rerun the entire matrix at doubled horizon/refined integration. Plant B uses a native ANDES Kundur network but a reduced controller prediction model. E6 infeasibility is concentrated in delay scenarios and exceeds the frozen threshold. E7/E8 were governance-stopped, so theory and final known/OOD evidence are absent by design. These omissions constrain publication claims to a carefully documented negative method result.
""", encoding="utf-8")
    (FINAL / "NEXT_STEP_BOUNDARY.md").write_text("""# Next-step boundary

This Goal stops after the fatal G6 result and E9 packaging. External review may authorize a new Goal focused on delay-robust feasibility restoration, but this package must not be used to continue tuning, switch branches, or consume final seeds.
""", encoding="utf-8")
    print(json.dumps(final_status, indent=2))


if __name__ == "__main__":
    main()
