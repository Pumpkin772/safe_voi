"""Seal the registered G2 stop and prepare Phase-G negative-result evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction1freq.models.delay_augmented_prediction import build_registered_delay_vertices
from direction1freq.models.guaranteed_capability_envelope import GuaranteedCapabilityEnvelope


REPO = Path(__file__).resolve().parents[2]
STOP_STATUS = "LOCAL_TERMINAL_MODEL_NOT_CERTIFIABLE"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_not_evaluated_progress(stage: int, reason: str) -> None:
    progress = {
        "schema": "direction1.phase_g.progress.v1",
        "stage": f"G{stage}",
        "gate": f"G{stage}",
        "gate_passed": None,
        "gate_status": "NOT_EVALUATED",
        "reason": reason,
        "episodes_run": 0,
        "final_seeds_consumed": False,
        "not_evaluated_is_not_failure": True,
        "next_stage": "G9_NEGATIVE_PACKAGE",
    }
    (REPO / "progress_phase_g" / f"G{stage}.json").write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def local_one_step_table() -> pd.DataFrame:
    local = np.load(
        REPO / "research_outputs_phase_g" / "03_MODEL" / "LOCAL_TERMINAL_SET.npz"
    )
    model_radius = np.asarray(local["state_prediction_radii"][0], dtype=float)
    load_radius = np.asarray(local["structured_load_error_radii"][0], dtype=float)
    envelope = GuaranteedCapabilityEnvelope.phase_f_registered()
    effects = [
        np.abs(vertex.ed) @ load_radius
        for period in (2.0, 4.0)
        for vertex in build_registered_delay_vertices(
            period, envelope.delay_vertices_s
        )
    ]
    effective = model_radius + np.max(effects, axis=0)
    quantities = {
        "frequency_area_1_hz": (50.0 * effective[0], 0.30),
        "frequency_area_2_hz": (50.0 * effective[1], 0.30),
        "tie_pu": (effective[2], 0.08),
        "ace_area_1_pu": (21.0 * effective[0] + effective[2], 0.15),
        "ace_area_2_pu": (21.0 * effective[1] + effective[2], 0.15),
    }
    return pd.DataFrame(
        [
            {
                "quantity": name,
                "effective_one_step_radius": value,
                "terminal_limit": limit,
                "compatible": bool(value <= limit),
                "excess": value - limit,
            }
            for name, (value, limit) in quantities.items()
        ]
    )


def main() -> None:
    result_dir = REPO / "results_phase_g" / "G9"
    final_dir = REPO / "research_outputs_phase_g" / "final"
    theory_dir = REPO / "research_outputs_phase_g" / "05_THEORY"
    paper_dir = REPO / "research_outputs_phase_g" / "13_PAPER"
    model_dir = REPO / "research_outputs_phase_g" / "03_MODEL"
    method_dir = REPO / "research_outputs_phase_g" / "04_METHOD"
    config_dir = REPO / "configs" / "phase_g"
    for directory in (
        result_dir,
        final_dir,
        theory_dir,
        paper_dir,
        model_dir,
        method_dir,
        config_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    reason = (
        "G2 exhausted the two registered uncertainty/observer repairs; the "
        "validated local model/load sets still violate the one-step terminal limits"
    )
    for stage in range(3, 9):
        write_not_evaluated_progress(stage, reason)

    compatibility = local_one_step_table()
    compatibility_path = (
        REPO / "results_phase_g" / "G2" / "LOCAL_ONE_STEP_TERMINAL_COMPATIBILITY.csv"
    )
    compatibility.to_csv(compatibility_path, index=False)

    domain_manifest_path = model_dir / "SUSTAINABLE_BRIDGE_INFEASIBLE_MANIFEST.csv"
    pd.DataFrame(
        [
            {
                "scope": "all_registered_phase_g_scenarios",
                "classification": "NOT_EVALUATED",
                "stage": "G3",
                "episodes": 0,
                "reason": "registered G2 local-terminal compatibility stop",
                "not_evaluated_is_not_failure": True,
            }
        ]
    ).to_csv(domain_manifest_path, index=False)
    g3_status_path = model_dir / "G3_PARTITION_STATUS.md"
    g3_status_path.write_text(
        """# G3 partition status

`NOT_EVALUATED`. The sustainable, finite-energy bridge, and physically
infeasible domains were not computed because the binding G2 Gate stopped the
phase. The manifest contains an explicit zero-episode sentinel and must not be
read as a physical classification of any scenario.
""",
        encoding="utf-8",
    )
    local_set = np.load(
        REPO / "research_outputs_phase_g" / "03_MODEL" / "LOCAL_TERMINAL_SET.npz"
    )
    model_radius = np.asarray(local_set["state_prediction_radii"][0], dtype=float)
    load_radius = np.asarray(
        local_set["structured_load_error_radii"][0], dtype=float
    )
    envelope = GuaranteedCapabilityEnvelope.phase_f_registered()
    load_effects = np.asarray(
        [
            np.abs(vertex.ed) @ load_radius
            for period in (2.0, 4.0)
            for vertex in build_registered_delay_vertices(
                period, envelope.delay_vertices_s
            )
        ]
    )
    maximum_load_effect = np.max(load_effects, axis=0)
    effective_radius = model_radius + maximum_load_effect
    certificate_npz_path = theory_dir / "LOCAL_TERMINAL_INCOMPATIBILITY_CERTIFICATE.npz"
    np.savez_compressed(
        certificate_npz_path,
        model_observer_radius=model_radius,
        structured_load_error_radius=load_radius,
        load_state_effect_by_period_vertex=load_effects,
        maximum_load_state_effect=maximum_load_effect,
        effective_state_radius=effective_radius,
        frequency_bias=np.array([21.0, 21.0]),
        nominal_frequency_hz=np.array(50.0),
        terminal_limits=np.array([0.30, 0.15, 0.08]),
    )
    certificate_json_path = theory_dir / "LOCAL_TERMINAL_INCOMPATIBILITY_CERTIFICATE.json"
    certificate_json_path.write_text(
        json.dumps(
            {
                "schema": "direction1.phase_g.local_terminal_incompatibility.v1",
                "status": STOP_STATUS,
                "global_minimum_validation_coverage": 0.993006993006993,
                "local_minimum_validation_coverage": 0.9666666666666667,
                "effective_metrics": compatibility.to_dict(orient="records"),
                "all_registered_terminal_metrics_incompatible": bool(
                    not compatibility.compatible.any()
                ),
                "cvxpy_required_for_verification": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    gates = pd.DataFrame(
        [
            ("G0", "PASS", "Phase F frozen and certificate formulation reclassified"),
            ("G1", "PASS", "four non-delay mechanisms and three SG tensions remain material"),
            ("G2", "FAIL", "local one-step effective set exceeds every registered terminal limit"),
            ("G3", "NOT_EVALUATED", "stopped by G2"),
            ("G4", "NOT_EVALUATED", "stopped by G2"),
            ("G5", "NOT_EVALUATED", "stopped by G2"),
            ("G6", "NOT_EVALUATED", "stopped by G2"),
            ("G7", "NOT_EVALUATED", "stopped by G2"),
            ("G8", "NOT_EVALUATED", "final seeds prohibited after G2 stop"),
            ("G9", "PENDING", "set by post-package verification"),
        ],
        columns=["gate", "status", "evidence"],
    )
    gates_path = result_dir / "ALL_GATES.csv"
    gates.to_csv(gates_path, index=False)

    failure_rows = [
        {
            "stage": "G2",
            "attempt": 1,
            "class": "MODEL_SET",
            "failure": "delay vertex spread double-counted as additive residual",
            "disposition": "repaired using preregistered delay truth; evidence retained",
            "resolved": True,
        },
        {
            "stage": "G2",
            "attempt": 2,
            "class": "MODEL_SET",
            "failure": "local total residual undercovered 4 s validation windows",
            "disposition": "separated local model/observer residual from structured load error",
            "resolved": True,
        },
        {
            "stage": "G2",
            "attempt": 3,
            "class": "SCIENTIFIC_HYPOTHESIS",
            "failure": "validated combined local model/load one-step set exceeds terminal frequency ACE and tie limits",
            "disposition": "fatal registered stop; no threshold relaxation or extra repair",
            "resolved": False,
        },
    ]
    failures = pd.DataFrame(failure_rows)
    failures_path = result_dir / "FAILURE_LEDGER.csv"
    failures.to_csv(failures_path, index=False)

    status = {
        "schema": "direction1.phase_g.final_status.v1",
        "project": "DIRECTION1",
        "method": "CDSR-MPC",
        "final_research_status": STOP_STATUS,
        "phase_f_reclassification": "CERTIFICATE_FORMULATION_INCOMPATIBLE",
        "gates": dict(zip(gates.gate, gates.status, strict=True)),
        "hypotheses": {
            "H1": "SUPPORTED_FOR_POWER_RAMP_ENERGY_AVAILABILITY",
            "H2": "TESTED_PASSIVE_ESTIMATORS_NOT_SUPPORTED_UNDER_REGISTERED_EXCITATION",
            "H3": "TESTED_ACTIVE_PROBE_NOT_SAFE",
            "H4": "NOT_EVALUATED_AFTER_G2_STOP",
            "H5": "NOT_EVALUATED_AFTER_G2_STOP",
        },
        "global_prediction_minimum_validation_coverage": 0.993006993006993,
        "local_model_load_minimum_validation_coverage": 0.9666666666666667,
        "local_terminal_one_step_compatible": False,
        "sustainable_partition": "NOT_EVALUATED",
        "bridge_partition": "NOT_EVALUATED",
        "physically_infeasible_partition": "NOT_EVALUATED",
        "sustainable_terminal_certificate": "NOT_EVALUATED",
        "bridge_certificate": "NOT_EVALUATED",
        "conditional_recursive_feasibility_certified": False,
        "finite_horizon_bridge_certified": False,
        "best_deployable_baseline": "fixed_allocation_pi",
        "known_results": "NOT_EVALUATED",
        "ood_results": "NOT_EVALUATED",
        "plant_a_status": "G0-G2_FORENSIC_OBSERVER_MODEL_SET_ONLY",
        "plant_b_status": "NOT_EVALUATED_AFTER_G2_STOP",
        "solver_statistics": "NOT_EVALUATED_AFTER_G2_STOP",
        "restoration_statistics": "NOT_EVALUATED_AFTER_G2_STOP",
        "backup_statistics": "NOT_EVALUATED_AFTER_G2_STOP",
        "final_seeds_consumed": False,
        "final_seeds_used_for_tuning": False,
        "failures_deleted": False,
        "not_evaluated_imputed_as_failure": False,
        "most_severe_limitation": (
            "the causal observer's validated event-free local load uncertainty, "
            "combined with local model error, exceeds all old terminal performance limits in one step"
        ),
        "next_step_boundary": "STOP_FOR_REVIEW; no further observer/set repair under this Goal",
    }
    status_path = final_dir / "FINAL_STATUS.json"
    status_path.write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    claim_rows = [
        ("Phase F G5 was a certificate-formulation incompatibility", "SUPPORTED", "G0"),
        ("four non-delay capability mechanisms remain material", "SUPPORTED", "G1"),
        ("global prediction validation coverage is at least 95 percent", "SUPPORTED", "G2"),
        ("local model and load sets separately cover at least 95 percent", "SUPPORTED", "G2"),
        ("a nontrivial local terminal domain is certifiable", "NOT_SUPPORTED", "G2"),
        ("sustainable or bridge certificates exist", "NOT_EVALUATED", "G3-G4"),
        ("revised CDSR outperforms baselines on Plant A/B known/OOD", "NOT_EVALUATED", "G5-G8"),
        ("recursive feasibility holds", "NOT_SUPPORTED", "G2 stop before G4/G7"),
    ]
    claims = pd.DataFrame(claim_rows, columns=["claim", "status", "evidence"])
    claim_path = final_dir / "CLAIM_EVIDENCE_MATRIX.csv"
    claims.to_csv(claim_path, index=False)

    (final_dir / "FINAL_RESULTS_INTERPRETATION.md").write_text(
        """# Final Phase-G interpretation

Phase G confirmed that Phase F mixed event-scale residuals and an SG-only
backup contract in a physically incompatible terminal certificate. It then
implemented a causal augmented observer, pre-registered all five delay truths,
and separated global prediction, local model/observer, and structured load
uncertainty. Global and separated local validation coverage passed.

The effective one-step local set nevertheless exceeds every registered
frequency, ACE, and tie terminal limit. After the two allowed repairs, G2
therefore stopped as `LOCAL_TERMINAL_MODEL_NOT_CERTIFIABLE`. This is not a
CDSR-MPC category failure: terminal/bridge design, revised closed-loop CDSR,
Plant B, known/OOD, and final evidence were not evaluated. No final seed was
consumed and no failure was deleted.
""",
        encoding="utf-8",
    )
    (final_dir / "NEXT_STEP_BOUNDARY.md").write_text(
        """# Next-step boundary

Stop for external review. A future preregistered phase may change the observer
measurement/contract, terminal performance limits with physical justification,
or local load-rate model. It must not continue tuning this validation evidence,
must not claim Phase G tested CDSR closed-loop performance, and must retain all
three G2 attempts.
""",
        encoding="utf-8",
    )
    (final_dir / "SUPPORTED_AND_UNSUPPORTED_CLAIMS.md").write_text(
        """# Supported and unsupported claims

Supported: Phase-F certificate incompatibility; H1 materiality excluding delay;
causal observer API; five-vertex preregistered residual calibration; empirical
global and separated-local validation coverage.

Unsupported/not evaluated: nonempty sustainable RPI/RCI; bridge certificate;
conditional recursive feasibility; repaired CDSR closed-loop performance;
real-time Gate; Plant A/B comparative evidence; known/OOD superiority.
""",
        encoding="utf-8",
    )

    (theory_dir / "ASSUMPTIONS.md").write_text(
        """# Phase G stopped theory assumptions

The G2 sets are empirical 95-percent validation-coverage objects. Physical
power/ramp/energy/delay contracts remain deterministic but were not integrated
into a G4 certificate because the local terminal compatibility Gate failed.
No RPI, RCI, bridge, or recursive-feasibility theorem is asserted.
""",
        encoding="utf-8",
    )
    (theory_dir / "UNSUPPORTED_THEORY_CLAIMS.md").write_text(
        """# Unsupported Phase-G theory claims

- No nonempty sustainable RPI/RCI was computed.
- No finite-energy bridge certificate was computed.
- No conditional recursive-feasibility theorem applies.
- No robust-switching or all-disturbance safety claim applies.
- Empirical 95-percent coverage is not deterministic robustness.
""",
        encoding="utf-8",
    )
    certificate_status_path = theory_dir / "G4_TERMINAL_AND_BRIDGE_CERTIFICATE_STATUS.md"
    certificate_status_path.write_text(
        """# G4 certificate status

`NOT_EVALUATED`. No sustainable-domain RPI/RCI set and no bridge-domain
power-ramp-energy certificate were computed. Consequently there is no
recursive-feasibility, robust-switching, or finite-horizon bridge claim.
The only recomputable Phase-G certificate is the preceding G2 local terminal
incompatibility certificate.
""",
        encoding="utf-8",
    )
    method_status_path = method_dir / "G5_CDSR_REPAIR_STATUS.md"
    method_status_path.write_text(
        """# G5 CDSR repair status

`NOT_EVALUATED`. The registered G2 stop occurred before the CDSR-MPC prediction
repair, acceleration, closed-loop G5 Gate, solver timing, restoration, and
backup experiments. The active method remains CDSR-MPC; this phase did not
replace it or add AI/RL. The registered formulation specification is packaged
for review, but its implementation is not claimed complete.
""",
        encoding="utf-8",
    )
    (paper_dir / "PAPER_ROUTE.md").write_text(
        """# Paper route

Negative terminal-model result. Do not submit a positive CDSR-MPC performance
paper: G3-G8 were not evaluated. A methods/audit note may report why separating
event uncertainty from local terminal uncertainty is necessary, while clearly
retaining the failed local-certifiability outcome.
""",
        encoding="utf-8",
    )
    (paper_dir / "REVIEWER_RISK_REGISTER.md").write_text(
        """# Reviewer risk register

1. Small 4 s local-validation sample sizes: report exact counts and coverage.
2. Empirical sets: never call them deterministic all-disturbance bounds.
3. Early stop: do not imply CDSR closed-loop, Plant B, or known/OOD evidence.
4. Observer load uncertainty: it is the binding limitation, not a solver error.
5. Phase-F reclassification: scope it to the old set/backup architecture.
""",
        encoding="utf-8",
    )

    (config_dir / "slow_reserve_or_bridge_contract.yaml").write_text(
        """schema: direction1.phase_g.bridge_contract.v1
status: NOT_EVALUATED_AFTER_G2_STOP
slow_reserve_model_registered: false
claim_boundary: no_bridge_or_recursive_claim
""",
        encoding="utf-8",
    )
    (config_dir / "FINAL_SEED_FIREWALL.yaml").write_text(
        """schema: direction1.phase_g.final_seed_firewall.v1
final_seed_range: [100, 159]
consumed: false
reason: G2_LOCAL_TERMINAL_MODEL_NOT_CERTIFIABLE
""",
        encoding="utf-8",
    )

    outputs = [
        compatibility_path,
        gates_path,
        failures_path,
        status_path,
        claim_path,
        final_dir / "FINAL_RESULTS_INTERPRETATION.md",
        final_dir / "NEXT_STEP_BOUNDARY.md",
        final_dir / "SUPPORTED_AND_UNSUPPORTED_CLAIMS.md",
        theory_dir / "ASSUMPTIONS.md",
        theory_dir / "UNSUPPORTED_THEORY_CLAIMS.md",
        certificate_npz_path,
        certificate_json_path,
        domain_manifest_path,
        g3_status_path,
        certificate_status_path,
        method_status_path,
        paper_dir / "PAPER_ROUTE.md",
        paper_dir / "REVIEWER_RISK_REGISTER.md",
        config_dir / "slow_reserve_or_bridge_contract.yaml",
        config_dir / "FINAL_SEED_FIREWALL.yaml",
        *[REPO / "progress_phase_g" / f"G{stage}.json" for stage in range(3, 9)],
    ]
    summary_path = result_dir / "G9_PREPACKAGE_SUMMARY.json"
    summary = {
        "schema": "direction1.phase_g.prepackage.v1",
        "final_research_status": STOP_STATUS,
        "final_seeds_consumed": False,
        "g3_through_g8": "NOT_EVALUATED",
        "outputs_sha256": {
            path.relative_to(REPO).as_posix(): sha256(path) for path in outputs
        },
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
