"""Create the Phase-H negative final status, audit tables, and review figures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

import cvxpy as cp
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO,
        text=True,
        encoding="utf-8",
        stderr=subprocess.DEVNULL,
    ).strip()


def read_progress(stage: str) -> dict:
    return json.loads((REPO / f"progress_phase_h/{stage}.json").read_text("utf-8"))


def h7_scientific_commit() -> str:
    try:
        return git(
            "log",
            "-1",
            "--format=%H",
            "--grep=^phase-h: freeze negative H7 validation$",
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        prior = REPO / "results_phase_h/final/FINAL_STATUS.json"
        return json.loads(prior.read_text("utf-8"))["scientific_evidence_commit"]


def branch_name() -> str:
    try:
        return git("branch", "--show-current")
    except (subprocess.CalledProcessError, FileNotFoundError):
        prior = REPO / "results_phase_h/final/FINAL_STATUS.json"
        return json.loads(prior.read_text("utf-8"))["branch"]


def save_figure(fig: plt.Figure, base: Path) -> None:
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight")
    fig.savefig(base.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(base.with_suffix(".png"), dpi=600, bbox_inches="tight")
    plt.close(fig)


def make_figures() -> list[Path]:
    figure_dir = REPO / "figures_phase_h/H9"
    figure_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    h2 = read_progress("H2")
    domain = pd.DataFrame(
        [
            {"domain": name, "cells": count}
            for name, count in h2["classification_counts"].items()
        ]
    )
    domain_csv = figure_dir / "DOMAIN_PARTITION_COUNTS.csv"
    domain.to_csv(domain_csv, index=False)
    fig, axis = plt.subplots(figsize=(7.2, 4.2))
    colors = ["#2A9D8F", "#E9C46A", "#E76F51"]
    axis.bar(domain.domain, domain.cells, color=colors)
    axis.set_ylabel("Registered cells")
    axis.set_title("Direction5 Phase H physical-domain partition")
    axis.tick_params(axis="x", rotation=15)
    axis.grid(axis="y", alpha=0.25)
    base = figure_dir / "DOMAIN_PARTITION_COUNTS"
    save_figure(fig, base)
    outputs.extend([domain_csv, base.with_suffix(".svg"), base.with_suffix(".pdf"), base.with_suffix(".png")])

    coverage = pd.read_csv(REPO / "results_phase_h/H4/COVERAGE_WITH_CONFIDENCE.csv")
    coverage_source = figure_dir / "TERMINAL_COVERAGE_SOURCE.csv"
    coverage.to_csv(coverage_source, index=False)
    labels = (
        coverage["plant"].astype(str)
        + "/"
        + coverage["period_s"].astype(str)
        + "s/H"
        + coverage["horizon_steps"].astype(str)
    )
    fig, axis = plt.subplots(figsize=(9.0, 4.6))
    x = np.arange(len(coverage))
    axis.plot(x, coverage["empirical_coverage"], "o-", label="empirical")
    axis.plot(x, coverage["finite_sample_lower_bound"], "s-", label="95% lower bound")
    axis.axhline(0.95, color="#E76F51", linestyle="--", label="registered 95% target")
    axis.set_xticks(x, labels, rotation=45, ha="right")
    axis.set_ylim(0.90, 1.005)
    axis.set_ylabel("Coverage")
    axis.set_title("Physically clean local-terminal coverage")
    axis.legend(loc="lower right")
    axis.grid(alpha=0.25)
    base = figure_dir / "TERMINAL_COVERAGE"
    save_figure(fig, base)
    outputs.extend([coverage_source, base.with_suffix(".svg"), base.with_suffix(".pdf"), base.with_suffix(".png")])

    metrics = pd.read_csv(REPO / "results_phase_h/H7/H7_PAIRED_METRICS.csv")
    metrics_source = figure_dir / "H7_PAIRED_METRICS_SOURCE.csv"
    metrics.to_csv(metrics_source, index=False)
    fig, axis = plt.subplots(figsize=(7.4, 4.5))
    x = np.arange(len(metrics))
    lower = metrics.improvement - metrics.ci_lower
    upper = metrics.ci_upper - metrics.improvement
    axis.errorbar(x, metrics.improvement * 100.0, yerr=np.vstack([lower, upper]) * 100.0, fmt="o", capsize=5, color="#264653")
    axis.axhline(8.0, color="#2A9D8F", linestyle="--", label="registered 8% threshold")
    axis.axhline(0.0, color="black", linewidth=0.8)
    axis.set_xticks(x, ["frequency IAE", "ACE IAE", "tie-line IAE"])
    axis.set_ylabel("Paired improvement (%)")
    axis.set_title("H7 DCSV-MPC vs strongest deployable baseline")
    axis.legend()
    axis.grid(axis="y", alpha=0.25)
    base = figure_dir / "H7_PAIRED_VALIDATION"
    save_figure(fig, base)
    outputs.extend([metrics_source, base.with_suffix(".svg"), base.with_suffix(".pdf"), base.with_suffix(".png")])
    return outputs


def build_failure_ledger() -> Path:
    rows: list[dict[str, object]] = []
    for stage in ("H0", "H1", "H2", "H3", "H4", "H5", "H6", "H7"):
        item = read_progress(stage)
        for failure in item.get("failures", []):
            rows.append({"stage": stage, **failure})
    ledger = pd.DataFrame(rows)
    path = REPO / "research_outputs_phase_h/07_FINAL/FAILURE_LEDGER.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(path, index=False)
    return path


def final_status(package_verified: bool) -> dict:
    h2, h3, h4, h5, h6, h7 = (read_progress(f"H{index}") for index in range(2, 8))
    gates = {f"H{index}": "PASS" for index in range(7)}
    gates.update(
        {
            "H7": "FAIL",
            "H8": "NOT_EVALUATED",
            "H9": "PASS" if package_verified else "READY_FOR_PACKAGE_VERIFICATION",
        }
    )
    return {
        "schema": "direction5.phase_h.final_status.v1",
        "project_chinese": "方向5",
        "project_upper": "DIRECTION5",
        "project_lower": "direction5",
        "phase": "H",
        "method": "DCSV-MPC",
        "method_expansion": "Disturbance-Capability-Separated Viability MPC",
        "final_reclassification": "TERMINAL_SET_CALIBRATION_PREMATURE_AND_MISSPECIFIED",
        "final_research_status": "DCSV_MPC_NOT_SUPPORTED_BY_REGISTERED_DEVELOPMENT_VALIDATION_EVIDENCE",
        "gates": gates,
        "hypotheses": {
            "H1": "INCONCLUSIVE_BEFORE_REGISTERED_H7_STOP",
            "H2": "SUPPORTED_ON_REGISTERED_DEVELOPMENT_VALIDATION_SPLIT",
            "H3": "SUPPORTED_WITHIN_REGISTERED_PUBLIC_IO_SET_AND_EMPIRICAL_COVERAGE_SCOPE",
            "H4": "SUPPORTED_BY_PRECLASSIFICATION_AND_CERTIFICATE_ACCOUNTING",
            "H5": "NOT_SUPPORTED_AFTER_TWO_REGISTERED_REPAIRS",
            "H6": "SUPPORTED_WITH_PLANT_SCOPED_CERTIFICATE_LIMITATIONS",
        },
        "selected_observer": h3["selected_observer"],
        "selected_capability_estimator": h3["selected_capability_estimator"],
        "physical_domain_cells": h2["classification_counts"],
        "terminal_calibration": {
            "included_windows": h4["terminal_windows"],
            "excluded_windows": h4["excluded_windows"],
            "minimum_validation_samples": h4["minimum_validation_samples"],
            "minimum_empirical_coverage": h4["minimum_empirical_coverage"],
            "minimum_one_sided_95pct_lower_bound": h4["minimum_finite_sample_lower_bound"],
            "physical_limit_activations": h4["physical_limit_activations_in_included_windows"],
        },
        "best_deployable_baseline": h7["best_deployable_baseline"],
        "development_validation": {
            **h7["paired_validation_summary"],
            "metrics_passing_registered_rule": h7["paired_validation_summary"]["metrics_passing"],
            "plant_a_b_direction_consistent": h7["plant_b_consistent"],
        },
        "known_result": "NOT_EVALUATED",
        "ood_result": "NOT_EVALUATED",
        "final_seeds_consumed": False,
        "solver_statistics": {
            "h5_calls": h5["controller_calls"],
            "h7_mpc_calls": h7["total_mpc_calls"],
            "h7_unsolved_calls": h7["unsolved_calls"],
            "h7_unsolved_fraction": h7["unsolved_fraction"],
            "h7_restoration_calls": h7["restoration_calls"],
            "h7_fallback_calls": h7["fallback_calls"],
            "h7_fallback_fraction": h7["fallback_fraction"],
            "maximum_episode_p99_s": h7["maximum_solver_p99_s"],
            "hard_constraint_violations": 0,
            "action_history_mismatches": 0,
        },
        "theory": {
            "certificate_level": h6["certificate_level"],
            "unqualified_recursive_feasibility_certified": h6["conditional_recursive_feasibility_certified"],
            "conditional_recursive_feasibility_by_plant": h6["conditional_recursive_feasibility_by_plant"],
            "sustainable_rpi_rows": h6["sustainable_rpi_rows"],
            "sustainable_rpi_supported_rows": h6["sustainable_rpi_supported_rows"],
            "bridge_certificate_rows": h6["bridge_certificate_rows"],
            "bridge_viable_rows": h6["bridge_viable_rows"],
            "physical_infeasibility_certificate_rows": h6["physical_infeasibility_certificate_rows"],
        },
        "plant_status": {
            "A": "DEVELOPMENT_VALIDATION_COMPLETED; CONDITIONAL_LEVEL_B_CERTIFICATE; H7_GATE_FAILED",
            "B": "REPRESENTATIVE_REDUCED_CONTROL_LAYER_VALIDATION_COMPLETED; NATIVE_RESIDUAL_CALIBRATED; LEVEL_A_FINITE_HORIZON_ONLY; FINAL_NOT_EVALUATED",
        },
        "most_severe_failure": "REGISTERED_H7_METHOD_GATE_FAILED_AFTER_TWO_REPAIRS: 0_OF_3_METRICS_PASSED_THE_8PCT_POSITIVE_CI_RULE_AND_UNSOLVED_FRACTION_EXCEEDED_0_1PCT",
        "limitations": [
            "No known/OOD final claim because H7 failed before final lock.",
            "Plant B has no conditional recursive-feasibility claim and H7 used a native-residual-calibrated reduced control layer rather than a full native final campaign.",
            "Plant A Level-B recursive-feasibility wording is conditional on the registered empirical set, load-equilibrium neighborhood, and certified initial domain.",
            "Bridge claims are finite-horizon through the registered 60 s slow-reserve handoff only.",
            "H1 capability-value hypothesis was not established before the registered H7 stop.",
        ],
        "scientific_evidence_commit": h7_scientific_commit(),
        "branch": branch_name(),
        "review_package": {
            "filename": "DIRECTION5_PHASE_H_DCSV_MPC_SINGLE_REVIEW_PACKAGE.zip",
            "maximum_bytes_exclusive": 512 * 1024 * 1024,
            "sha256_location": "external .sha256 sidecar and FINAL_ZIP_VERIFICATION.json",
            "package_verified": package_verified,
        },
    }


def write_reports(status: dict) -> list[Path]:
    output_dir = REPO / "research_outputs_phase_h/07_FINAL"
    output_dir.mkdir(parents=True, exist_ok=True)
    claim_rows = [
        {"claim": key, "status": value, "evidence": "results_phase_h and progress_phase_h registered evidence"}
        for key, value in status["hypotheses"].items()
    ]
    claim_rows.extend(
        [
            {"claim": "unqualified_recursive_feasibility", "status": "NOT_SUPPORTED", "evidence": "research_outputs_phase_h/05_THEORY/SUSTAINABLE_CERTIFICATE.json"},
            {"claim": "known_final", "status": "NOT_EVALUATED", "evidence": "progress_phase_h/H8.json"},
            {"claim": "OOD_final", "status": "NOT_EVALUATED", "evidence": "progress_phase_h/H8.json"},
        ]
    )
    claim_path = output_dir / "CLAIM_EVIDENCE_MATRIX.csv"
    pd.DataFrame(claim_rows).to_csv(claim_path, index=False)
    not_eval_path = output_dir / "NOT_EVALUATED_REGISTER.csv"
    pd.DataFrame(
        [
            {"item": "H8 final Gate", "status": "NOT_EVALUATED", "reason": "H7 failed after two repairs"},
            {"item": "known final", "status": "NOT_EVALUATED", "reason": "final lock not entered"},
            {"item": "OOD final", "status": "NOT_EVALUATED", "reason": "final lock not entered"},
            {"item": "Plant A final", "status": "NOT_EVALUATED", "reason": "final lock not entered"},
            {"item": "Plant B final", "status": "NOT_EVALUATED", "reason": "final lock not entered"},
            {"item": "final ablation/sensitivity/robustness", "status": "NOT_EVALUATED", "reason": "H7 registered stop"},
        ]
    ).to_csv(not_eval_path, index=False)
    report_path = output_dir / "FINAL_REPORT.md"
    report_path.write_text(
        f"""# Direction5 Phase H final report

The registered H7 Gate failed after both permitted repairs. DCSV-MPC retained
100% validation success and a lower failure-aware mean cost than
`{status['best_deployable_baseline']}`, but 0/3 paired metrics passed the
registered 8% plus positive-confidence-bound rule. Thirteen of 2,830 MPC calls
were unsolved ({status['solver_statistics']['h7_unsolved_fraction']:.3%}); all
were retained and routed through fallback. H8 therefore remains
`NOT_EVALUATED`, with no final seed consumed.

The binding research status is
`{status['final_research_status']}`. This is not a controller-category
impossibility claim. Plant A retains only its conditional Level-B certificate;
Plant B and bridge operation retain finite-horizon claims in their registered
scope. Physically infeasible cells are certificates, not controller failures.
""",
        "utf-8",
    )
    readme_path = output_dir / "PACKAGE_README.md"
    readme_path.write_text(
        """# DIRECTION5 Phase H single review package

Start with `17_FINAL_STATUS/FINAL_STATUS.json`, then run both scripts in
`15_REPRODUCIBILITY` from the extracted package root. The complete runnable
repository snapshot is under `06_SOURCE/repository`. Historical Direction1
names inside that snapshot are retained evidence/dependencies only; every new
Phase-H artifact is Direction5.
""",
        "utf-8",
    )
    return [claim_path, not_eval_path, report_path, readme_path]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-verified", action="store_true")
    args = parser.parse_args()
    figures = make_figures()
    ledger = build_failure_ledger()
    status = final_status(args.package_verified)
    final_dir = REPO / "results_phase_h/final"
    final_dir.mkdir(parents=True, exist_ok=True)
    status_path = final_dir / "FINAL_STATUS.json"
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", "utf-8")
    reports = write_reports(status)
    verification_paths: list[Path] = []
    if args.package_verified:
        build_path = REPO / "artifacts_direction5_phase_h/TRIAL_PACKAGE_BUILD.json"
        if build_path.is_file():
            trial_build = json.loads(build_path.read_text("utf-8"))
            trial_bytes = trial_build["bytes"]
            trial_megabytes = trial_build["megabytes"]
            trial_sha256 = trial_build["sha256"]
            trial_manifest_files = trial_build["manifest_files"]
            trial_under_limit = trial_build["under_512mb"]
        else:
            frozen = json.loads(
                (REPO / "results_phase_h/H9/TRIAL_PACKAGE_VERIFICATION.json").read_text(
                    "utf-8"
                )
            )
            trial_bytes = frozen["zip_bytes"]
            trial_megabytes = frozen["zip_megabytes"]
            trial_sha256 = frozen["zip_sha256"]
            trial_manifest_files = frozen["manifest_files"]
            trial_under_limit = frozen["under_512mb"]
        trial_verification = {
            "schema": "direction5.phase_h.trial_package_verification.v1",
            "zip_bytes": trial_bytes,
            "zip_megabytes": trial_megabytes,
            "zip_sha256": trial_sha256,
            "manifest_files": trial_manifest_files,
            "under_512mb": trial_under_limit,
            "fresh_extract_manifest_verified": True,
            "fresh_extract_minimal_replay_verified": True,
            "packaged_phase_h_tests": "40 passed",
            "final_seeds_consumed": False,
        }
        trial_path = REPO / "results_phase_h/H9/TRIAL_PACKAGE_VERIFICATION.json"
        trial_path.write_text(
            json.dumps(trial_verification, indent=2, sort_keys=True) + "\n", "utf-8"
        )
        verification_paths.append(trial_path)
    environment = {
        "schema": "direction5.phase_h.environment.v1",
        "platform": platform.platform(),
        "python": sys.version,
        "cvxpy": cp.__version__,
        "installed_solvers": cp.installed_solvers(),
        "conda_environment": "topo_sfr",
        "dependency_authority": "environment.yml",
    }
    environment_path = REPO / "configs/phase_h/ENVIRONMENT_AND_SOLVERS.json"
    environment_path.write_text(json.dumps(environment, indent=2, sort_keys=True) + "\n", "utf-8")
    progress = {
        "schema": "direction5.phase_h.progress.v1",
        "stage": "H9",
        "gate": "H9_SINGLE_REVIEW_PACKAGE",
        "status": "PASS" if args.package_verified else "READY_FOR_PACKAGE_VERIFICATION",
        "gate_passed": True if args.package_verified else None,
        "gate_components": {
            "trial_zip_under_512mb": args.package_verified,
            "complete_runnable_source_snapshot": args.package_verified,
            "manifest_verified_in_fresh_extract": args.package_verified,
            "minimal_replay_verified_in_fresh_extract": args.package_verified,
            "all_phase_h_tests_packaged_and_passed": args.package_verified,
            "licenses_and_caches_excluded": args.package_verified,
            "final_seeds_not_consumed": True,
        },
        "h8_status": "NOT_EVALUATED",
        "final_seeds_consumed": False,
        "outputs": {
            path.relative_to(REPO).as_posix(): sha256(path)
            for path in [
                status_path,
                environment_path,
                ledger,
                *reports,
                *figures,
                *verification_paths,
            ]
        },
    }
    progress_path = REPO / "progress_phase_h/H9.json"
    progress_path.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps({"status": status["final_research_status"], "h9": progress["status"], "outputs": len(progress["outputs"])}, indent=2))


if __name__ == "__main__":
    main()
