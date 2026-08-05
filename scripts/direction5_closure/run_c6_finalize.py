"""Seal the only admissible Direction5 closure state from frozen evidence."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results_closure" / "final"
REPORT = ROOT / "research_outputs_closure" / "06_FINAL"
PROGRESS = ROOT / "progress_closure" / "C6.json"
NEGATIVE = "DIRECTION5_NEGATIVE_RESULT_CONFIRMED_AND_ARCHIVED"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seal-report", type=Path, help="Successful pre-seal package verification JSON")
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    validation = load(ROOT / "results_final/R5/R5_SUMMARY.json")
    confirm = load(ROOT / "results_closure/C2/C2_SUMMARY.json")
    c0 = load(ROOT / "progress_closure/C0.json")
    c1 = load(ROOT / "progress_closure/C1.json")
    c2 = load(ROOT / "progress_closure/C2.json")
    c3 = load(ROOT / "progress_closure/C3.json")
    c4 = load(ROOT / "progress_closure/C4.json")
    c5 = load(ROOT / "progress_closure/C5.json")

    validation_positive = bool(validation["core_metrics_passing"] >= 2 and validation["gates"]["success_drop_at_most_2pp"] and validation["gates"]["plant_a_b_direction_consistent_positive"])
    confirm_positive = bool(confirm["confirmatory_positive_gate"])
    joint_positive = validation_positive and confirm_positive
    if joint_positive:
        raise RuntimeError("evidence unexpectedly requests the positive route; inspect frozen Gates")

    package_status = "PENDING_PACKAGE_VERIFICATION"
    package_verification: dict[str, object] = {"passed": False, "report": None}
    if args.seal_report:
        seal_path = args.seal_report.resolve()
        seal = load(seal_path)
        required = (
            seal.get("passed") is True
            and seal.get("manifest_verification", {}).get("passed") is True
            and seal.get("minimal_replay", {}).get("passed") is True
            and int(seal.get("zip_bytes", 512 * 1024 * 1024)) < 512 * 1024 * 1024
        )
        if not required:
            raise RuntimeError("pre-seal package report did not pass all checks")
        package_status = "PASS"
        package_verification = {
            "passed": True,
            "preseal_zip_sha256": seal["zip_sha256"],
            "preseal_zip_bytes": seal["zip_bytes"],
            "manifest_files": seal["manifest_verification"]["manifest_files"],
            "fresh_extract_manifest": True,
            "fresh_extract_minimal_replay": True,
            "report": seal_path.name,
        }

    now = datetime.now(timezone.utc).isoformat()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    final = {
        "schema": "direction5.closure.final_status.v1",
        "project": "DIRECTION5",
        "method": "DCSV-CR-MPC",
        "final_status": NEGATIVE,
        "validation_positive_gate": validation_positive,
        "confirmatory_positive_gate": confirm_positive,
        "joint_validation_confirmatory_positive": joint_positive,
        "paper_route": "NEGATIVE_RESULT_BOUNDARY_PAPER",
        "selected_observer": "constrained_mhe_actual_poi",
        "selected_capability_estimator": "causal_grid_outer_set_membership_ab_delay",
        "best_primary_deployable_baseline": "contract_only_rolling_mpc",
        "best_validation_deployable_baseline_by_ranking": validation["best_deployable_baseline"],
        "deterministic_bug_repairs": [
            {
                "scope": "C2_DIRECT_ENTRY_EXECUTION_ONLY",
                "repair": "insert repository root and src on sys.path before imports",
                "scientific_method_changed": False,
                "weights_thresholds_scenarios_changed": False,
                "repaired_before_final_lock": True,
            }
        ],
        "validation": {
            "plant_a_scenarios": validation["plant_a_scenarios"],
            "plant_b_scenarios": validation["plant_b_scenarios"],
            "success_drop_pp": validation["success_drop_pp"],
            "core_metrics_passing": validation["core_metrics_passing"],
            "optimization_decisions": validation["optimization_decisions"],
            "raw_solver_invocations": validation["attempted_solver_calls"],
            "restoration_calls": validation["restoration_calls"],
            "fallback_calls": validation["fallback_calls"],
            "normal1h_quality": validation["gates"]["normal1h_frequency_quality"],
        },
        "confirmatory": {
            "plant_a_scenarios": confirm["plant_a_scenarios"],
            "plant_b_scenarios": confirm["plant_b_scenarios"],
            "success_drop_pp": confirm["success_drop_pp"],
            "core_metrics_passing": confirm["core_metrics_passing"],
            "optimization_decisions": confirm["optimization_decisions"],
            "raw_solver_invocations": confirm["raw_solver_invocations"],
            "restoration_calls": confirm["restoration_calls"],
            "fallback_calls": confirm["fallback_calls"],
            "numerical_failures": confirm["numerical_failures"],
            "normal1h_quality": confirm["confirmatory_gates"]["normal1h_frequency_quality"],
            "final_seeds_consumed_once": confirm["final_seeds_consumed"],
            "post_result_tuning_permitted": confirm["post_result_tuning_permitted"],
        },
        "mechanism": {
            "fallback_explained_fraction": c1["fallback_explained_fraction"],
            "performance_rows_explained_fraction": c1["performance_rows_explained_fraction"],
            "surplus_active_calls": c1["surplus_active_calls"],
            "surplus_total_calls": c1["surplus_total_calls"],
            "registered_excitation_performance_above_contract_fraction": c1["r2_performance_above_contract_fraction"],
        },
        "theory_certificate": "CONDITIONAL_LOCAL_AND_FINITE_HORIZON_ONLY; NO_GLOBAL_RECURSIVE_FEASIBILITY_CLAIM",
        "most_severe_limitation": "The causal lower capability envelope almost never certified exploitable surplus, while Plant-A robust predictions produced substantial mathematical-infeasibility fallback and all methods failed the registered synthetic normal1h quality Gate.",
        "no_new_phase_or_method": True,
        "package_verification": package_verification,
        "prepared_from_git_head": head,
        "generated_utc": now,
    }
    (RESULTS / "FINAL_STATUS.json").write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8", newline="\n")

    stages = [c0, c1, c2, c3, c4, c5]
    stage_rows = [{"stage": item["stage"], "status": item["status"], "gate": item.get("gate", item.get("route", "DELIVERABLE_COMPLETE"))} for item in stages]
    stage_rows.append({"stage": "C6", "status": package_status, "gate": "FINAL_NEGATIVE_STATE_AND_ARCHIVE"})
    write_csv(RESULTS / "ALL_STAGE_GATES.csv", ["stage", "status", "gate"], stage_rows)

    scientific_rows = [
        {"gate": "A0_INDEPENDENT_AUDIT_CONSISTENCY", "validation": "PASS", "confirmatory": "NOT_APPLICABLE", "joint": "PASS"},
        {"gate": "A1_MECHANISM_EXPLANATION_AT_LEAST_90PCT", "validation": "PASS", "confirmatory": "PASS", "joint": "PASS"},
        {"gate": "A2_FINAL_LOCK_AND_SINGLE_EXECUTION", "validation": "NOT_APPLICABLE", "confirmatory": "PASS", "joint": "PASS"},
        {"gate": "REGISTERED_POSITIVE_PERFORMANCE", "validation": "FAIL", "confirmatory": "FAIL", "joint": "FAIL"},
        {"gate": "A3_NEGATIVE_RESULT_CONFIRMATION", "validation": "NEGATIVE", "confirmatory": "NEGATIVE", "joint": "PASS"},
        {"gate": "ZERO_HARD_VIOLATIONS", "validation": "PASS", "confirmatory": "PASS", "joint": "PASS"},
        {"gate": "SOLVER_DENOMINATOR_IDENTITIES", "validation": "PASS", "confirmatory": "PASS", "joint": "PASS"},
        {"gate": "NORMAL1H_FREQUENCY_QUALITY", "validation": "FAIL", "confirmatory": "FAIL", "joint": "FAIL"},
    ]
    write_csv(RESULTS / "SCIENTIFIC_GATES.csv", ["gate", "validation", "confirmatory", "joint"], scientific_rows)

    comparison = [
        {"quantity": "success_drop_pp", "validation": validation["success_drop_pp"], "confirmatory": confirm["success_drop_pp"]},
        {"quantity": "core_metrics_passing_of_3", "validation": validation["core_metrics_passing"], "confirmatory": confirm["core_metrics_passing"]},
        {"quantity": "fallback_calls", "validation": validation["fallback_calls"], "confirmatory": confirm["fallback_calls"]},
        {"quantity": "raw_solver_invocations", "validation": validation["attempted_solver_calls"], "confirmatory": confirm["raw_solver_invocations"]},
        {"quantity": "normal1h_quality", "validation": validation["gates"]["normal1h_frequency_quality"], "confirmatory": confirm["confirmatory_gates"]["normal1h_frequency_quality"]},
    ]
    write_csv(RESULTS / "VALIDATION_CONFIRMATORY_COMPARISON.csv", ["quantity", "validation", "confirmatory"], comparison)

    claims_src = ROOT / "research_outputs_closure/03_PAPER/CLAIM_LEDGER.csv"
    (RESULTS / "SUPPORTED_UNSUPPORTED_CLAIMS.csv").write_bytes(claims_src.read_bytes())
    limitations = [
        {"limitation": "simulation_only", "severity": "HIGH", "detail": "No hardware or field validation."},
        {"limitation": "synthetic_normal_profiles", "severity": "HIGH", "detail": "Six registered AR2+multi-sine profiles; all methods failed quality."},
        {"limitation": "online_envelope_not_actionable", "severity": "HIGH", "detail": "Surplus active in 2/22392 validation DCSV calls."},
        {"limitation": "plant_a_mathematical_infeasibility", "severity": "HIGH", "detail": "Fallback burden concentrated on full nonlinear Plant A."},
        {"limitation": "certificate_scope", "severity": "HIGH", "detail": "Conditional local/finite-horizon certificates only."},
    ]
    write_csv(RESULTS / "LIMITATIONS.csv", ["limitation", "severity", "detail"], limitations)

    decision = f"""# Direction5 final closure decision

The registered positive performance Gate failed in corrected validation and again in the one-time untouched-seed confirmation. DCSV-CR-MPC passed 0/3 core metric Gates in both stages; confirmation reduced success by {confirm['success_drop_pp']:.2f} percentage points, produced {confirm['fallback_calls']:,} fallbacks, and did not show a consistent positive direction across full nonlinear Plant A and native ANDES Plant B.

Perfect capability information retained bounded value, but the causal online envelope did not realize it. Surplus was activated only 2 times in 22,392 validation calls, and the fallback root cause was mathematical infeasibility rather than numerical solver failure. All seven controllers failed the registered synthetic normal1h quality Gate.

The only final state is:

```text
{NEGATIVE}
```

No post-confirmation tuning, new method, new phase, or broader impossibility claim is authorized.
"""
    (REPORT / "FINAL_DECISION.md").write_text(decision, encoding="utf-8", newline="\n")

    progress = {
        "schema": "direction5.closure.progress.v1",
        "stage": "C6",
        "status": package_status,
        "gate": "FINAL_NEGATIVE_STATE_AND_ARCHIVE",
        "final_status": NEGATIVE,
        "validation_positive_gate": validation_positive,
        "confirmatory_positive_gate": confirm_positive,
        "joint_positive_gate": joint_positive,
        "package_verification": package_verification,
        "post_result_tuning": False,
        "new_phase_created": False,
        "generated_utc": now,
    }
    PROGRESS.write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(progress, indent=2))


if __name__ == "__main__":
    main()
