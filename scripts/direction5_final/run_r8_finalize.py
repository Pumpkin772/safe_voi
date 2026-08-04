"""Finalize bounded claims, stopping records and paper analysis after R5."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "results_final"
FINAL = RESULTS / "final"
OUTPUTS = REPO / "research_outputs_final"
PAPER = OUTPUTS / "14_PAPER_ANALYSIS"
STATUS_DIR = OUTPUTS / "17_FINAL_STATUS"
FAILURES = OUTPUTS / "13_FAILURES"
FIGURES = REPO / "figures_final/R8"
PROGRESS = REPO / "progress_final"

FINAL_STATE = "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def load_progress(stage: str) -> dict:
    return json.loads((PROGRESS / f"{stage}.json").read_text("utf-8"))


def git_value(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def write_stopping_progress() -> None:
    for stage, reason in (
        ("R6", "R5_FATAL_VALIDATION_GATE_FAILED_FINAL_LOCK_FORBIDDEN"),
        ("R7", "R5_FATAL_VALIDATION_GATE_FAILED_FINAL_EVIDENCE_FORBIDDEN"),
    ):
        record = {
            "schema": "direction5.final_repair.progress.v1",
            "stage": stage,
            "status": "NOT_EVALUATED",
            "gate": reason,
            "final_seeds_consumed": False,
            "not_evaluated_is_not_failure_or_success": True,
            "next_stage": "R8_NEGATIVE_PACKAGE",
        }
        (PROGRESS / f"{stage}.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )


def hypothesis_table() -> pd.DataFrame:
    return pd.DataFrame([
        ("H1", "SUPPORTED", "R1: 4/6 material mechanism-tension cells"),
        ("H2", "SUPPORTED", "R2: constrained MHE actual-POI RMSE 0.000817 vs command comparator 0.005858"),
        ("H3", "SUPPORTED_WITH_FINITE_SAMPLE_SCOPE", "R2: power/ramp/delay coverage 60/60; false optimism 0/5340"),
        ("H4", "SUPPORTED_FOR_HARD_SAFETY_SEMANTICS", "R3/R5: contract/online split, zero hard violations, contract breach reported separately"),
        ("H5", "NOT_SUPPORTED", "R5: 0/3 metric Gate, success/terminal drops, backup and direction Gates failed"),
        ("H6", "SUPPORTED_WITH_CONDITIONAL_SCOPE", "R4: local Plant-A RPI plus finite contract/recourse/bridge certificates"),
    ], columns=("hypothesis", "status", "evidence"))


def all_gates() -> pd.DataFrame:
    records = []
    for stage in ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7"):
        progress = load_progress(stage)
        gates = progress.get("gates", {})
        if gates:
            for gate, passed in gates.items():
                records.append({
                    "stage": stage,
                    "gate": gate,
                    "status": "PASS" if passed else "FAIL",
                    "not_evaluated": False,
                })
        else:
            records.append({
                "stage": stage,
                "gate": progress["gate"],
                "status": progress["status"],
                "not_evaluated": progress["status"] == "NOT_EVALUATED",
            })
    records.append({
        "stage": "R8",
        "gate": "NEGATIVE_REVIEW_PACKAGE_BUILD_AND_FRESH_REPLAY",
        "status": "PENDING_PACKAGE_BUILD",
        "not_evaluated": False,
    })
    return pd.DataFrame(records)


def make_figures() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    metric = pd.read_csv(RESULTS / "R5/CORE_METRIC_GATES.csv")
    labels = ["Frequency peak", "ACE IAE", "Tie RMS"]
    relative = 100.0 * metric.aggregate_mean_relative_improvement.to_numpy()
    lower = 100.0 * metric.relative_improvement_lower.to_numpy()
    figure, axis = plt.subplots(figsize=(7.2, 4.2))
    axis.bar(labels, relative, color=["#4C78A8", "#59A14F", "#E15759"])
    axis.errorbar(labels, relative, yerr=np.maximum(relative - lower, 0.0), fmt="none", color="black", capsize=4)
    axis.axhline(8.0, color="black", linestyle="--", label="registered +8% Gate")
    axis.axhline(0.0, color="gray", linewidth=0.8)
    axis.set_ylabel("Scenario-balanced relative improvement (%)")
    axis.set_title("DCSV-CR-MPC vs contract-only rolling MPC")
    axis.legend()
    figure.tight_layout()
    figure.savefig(FIGURES / "CORE_METRIC_GATE.png", dpi=180)
    plt.close(figure)

    failure = pd.read_csv(RESULTS / "R5/PAIRED_FAILURE_TABLE.csv")
    overall = failure[failure.scope.eq("ALL")]
    figure, axis = plt.subplots(figsize=(8.0, 4.2))
    axis.bar(overall.category, overall.scenarios, color="#4C78A8")
    axis.tick_params(axis="x", rotation=35)
    axis.set_ylabel("Paired scenarios")
    axis.set_title("Success-first paired outcome accounting")
    figure.tight_layout()
    figure.savefig(FIGURES / "PAIRED_FAILURE_CATEGORIES.png", dpi=180)
    plt.close(figure)

    normal = pd.read_csv(RESULTS / "R5/NORMAL1H_QUALITY.csv").sort_values("frequency_peak_hz")
    figure, axis = plt.subplots(figsize=(8.5, 4.8))
    axis.barh(normal.method, normal.frequency_peak_hz, color="#F28E2B")
    axis.axvline(1.0, color="black", linestyle="--", label="registered 1 Hz Gate")
    axis.set_xlabel("Worst 3600 s frequency peak (Hz)")
    axis.set_title("Registered synthetic normal1h frequency-quality audit")
    axis.legend()
    figure.tight_layout()
    figure.savefig(FIGURES / "NORMAL1H_FREQUENCY_QUALITY.png", dpi=180)
    plt.close(figure)

    known = pd.read_csv(RESULTS / "R5/KNOWN_OOD_SUMMARY.csv")
    plant_a = known[known.plant.eq("A_full_nonlinear")]
    pivot = plant_a.pivot(index="condition", columns="method", values="success_rate")
    figure, axis = plt.subplots(figsize=(6.8, 4.2))
    x = np.arange(len(pivot.index))
    width = 0.36
    axis.bar(x - width / 2, pivot["contract_only_rolling_mpc"], width, label="Contract MPC")
    axis.bar(x + width / 2, pivot["dcsv_cr_mpc"], width, label="DCSV-CR")
    axis.set_xticks(x, pivot.index)
    axis.set_ylim(0.0, 1.05)
    axis.set_ylabel("Physical success rate")
    axis.set_title("Plant A known/OOD success")
    axis.legend()
    figure.tight_layout()
    figure.savefig(FIGURES / "PLANT_A_KNOWN_OOD_SUCCESS.png", dpi=180)
    plt.close(figure)

    directions = pd.read_csv(RESULTS / "R5/PLANT_DIRECTION_CONSISTENCY.csv")
    figure, axis = plt.subplots(figsize=(7.0, 4.0))
    colors = ["#59A14F" if value > 0 else "#E15759" for value in directions.paired_frequency_absolute_difference_hz]
    axis.bar(directions.plant, directions.paired_frequency_absolute_difference_hz, color=colors)
    axis.axhline(0.0, color="black", linewidth=0.8)
    axis.set_ylabel("Contract minus DCSV frequency peak (Hz)")
    axis.set_title("Cross-plant direction inconsistency")
    axis.tick_params(axis="x", rotation=12)
    figure.tight_layout()
    figure.savefig(FIGURES / "PLANT_DIRECTION.png", dpi=180)
    plt.close(figure)

    cycles = pd.read_parquet(RESULTS / "R5/ALL_CONTROL_CYCLES.parquet")
    candidate = cycles[
        cycles.scenario_id.eq("R5-V-A-000")
        & cycles.method.isin(("dcsv_cr_mpc", "contract_only_rolling_mpc"))
    ]
    figure, axis = plt.subplots(figsize=(8.0, 4.2))
    for method_name, block in candidate.groupby("method"):
        axis.plot(block.time_s, block.frequency0_hz, label=method_name)
    axis.axvline(60.0, color="gray", linestyle=":", label="warm-up minimum")
    axis.set_xlabel("Time (s)")
    axis.set_ylabel("Area-0 frequency deviation (Hz)")
    axis.set_title("Representative full rolling Plant-A trace")
    axis.legend(fontsize=8)
    figure.tight_layout()
    figure.savefig(FIGURES / "REPRESENTATIVE_PLANT_A_TRACE.png", dpi=180)
    plt.close(figure)


def main() -> None:
    for directory in (FINAL, PAPER, STATUS_DIR, FAILURES, FIGURES, PROGRESS):
        directory.mkdir(parents=True, exist_ok=True)
    write_stopping_progress()
    h = hypothesis_table()
    h.to_csv(FINAL / "HYPOTHESES_H1_H6.csv", index=False)
    gates = all_gates()
    gates.to_csv(FINAL / "ALL_GATES.csv", index=False)
    claims = pd.DataFrame([
        ("Capability materiality", "SUPPORTED_BOUNDED", "4/6 registered R1 cells; delay alone not universally material"),
        ("Actual-POI load observer", "SUPPORTED", "selected before validation"),
        ("Deliverability set coverage", "SUPPORTED_FINITE_SAMPLE", "60 area samples per dimension; registered R2 protocol"),
        ("Contract-safe finite horizon", "SUPPORTED_CONDITIONALLY", "contract containment/model/SoC assumptions"),
        ("Plant-A local recursive feasibility", "SUPPORTED_CONDITIONALLY", "local linear RPI and quiescent pipeline only"),
        ("Native Plant-B recursive feasibility", "UNSUPPORTED", "empirical RMS/DAE validation only"),
        ("DCSV-CR performance advantage", "NOT_SUPPORTED", "R5 failed 7 registered Gates"),
        ("Normal operating frequency quality", "NOT_SUPPORTED", "all seven methods exceeded registered normal1h quality Gate"),
        ("Same-instant arbitrary contract-collapse safety", "IMPOSSIBLE_UNCONDITIONALLY", "causal indistinguishable-world theorem"),
    ], columns=("claim", "status", "boundary_or_evidence"))
    claims.to_csv(FINAL / "SUPPORTED_UNSUPPORTED_CLAIMS.csv", index=False)
    limitations = pd.DataFrame([
        ("L1", "DCSV-CR failed all three registered core metric improvements", "DECISIVE"),
        ("L2", "Known in-contract backup fraction was 6.86%, above 1%", "DECISIVE"),
        ("L3", "Plant A direction negative while native Plant B direction slightly positive", "DECISIVE"),
        ("L4", "All normal1h profiles are explicit synthetic data, not public measured windows", "HIGH"),
        ("L5", "All seven methods failed the registered normal1h frequency-quality Gate", "DECISIVE"),
        ("L6", "Native ANDES logs retain generated-pycode/initialization warnings although all runs converged", "HIGH"),
        ("L7", "Plant B has no DAE RPI/recursive certificate", "HIGH"),
        ("L8", "Contract-violation scenarios are outside the guarantee; some peaks exceeded 1 Hz", "HIGH"),
    ], columns=("id", "limitation", "severity"))
    limitations.to_csv(FINAL / "LIMITATIONS.csv", index=False)
    r5 = load_progress("R5")
    r2 = load_progress("R2")
    r4 = load_progress("R4")
    status = {
        "schema": "direction5.final_repair.final_status.v1",
        "project": "DIRECTION5",
        "method": "DCSV-CR-MPC",
        "final_status": FINAL_STATE,
        "scientific_commit": git_value("rev-parse", "HEAD"),
        "branch": git_value("branch", "--show-current"),
        "R0_R8": {
            "R0": "PASS", "R1": "PASS", "R2": "PASS", "R3": "PASS",
            "R4": "PASS", "R5": "FAIL", "R6": "NOT_EVALUATED",
            "R7": "NOT_EVALUATED", "R8": "PENDING_PACKAGE_BUILD",
        },
        "phase_i_termination_withdrawn": True,
        "materiality": "SUPPORTED_IN_4_OF_6_REGISTERED_MECHANISM_TENSION_CELLS",
        "selected_observer": r2["selected_observer"],
        "selected_capability_estimator": r2["selected_capability_estimator"],
        "best_deployable_baseline": r5["best_deployable_baseline"],
        "final_seeds_consumed": False,
        "known_backup_fraction": r5["known_backup_fraction"],
        "solver": {
            "optimization_decisions": r5["optimization_decisions"],
            "raw_solver_invocations": r5["attempted_solver_calls"],
            "restoration_calls": r5["restoration_calls"],
            "fallback_calls": r5["fallback_calls"],
            "numerical_failures": r5["numerical_failures"],
            "accuracy_warnings": r5["accuracy_warnings"],
        },
        "certificate_status": r4["certificate_status"],
        "recursive_feasibility_claim": r4["recursive_feasibility_claim"],
        "plant_a": "DECISIVE_NEGATIVE_METHOD_DIRECTION",
        "plant_b": "NATIVE_ANDES_EMPIRICAL_COMPLETE_SLIGHT_POSITIVE_DIRECTION_NO_DAE_THEOREM",
        "normal1h": "FULL_3600S_SYNTHETIC_6_PER_METHOD_FREQUENCY_QUALITY_FAIL",
        "most_severe_failure": "0_OF_3_CORE_METRICS_PASSED_AND_ALL_METHODS_FAILED_NORMAL1H_FREQUENCY_QUALITY",
        "review_package": "DIRECTION5_FINAL_REPAIR_AND_DECISION_SINGLE_REVIEW_PACKAGE.zip",
    }
    (FINAL / "FINAL_STATUS.json").write_text(
        json.dumps(status, indent=2) + "\n", encoding="utf-8"
    )
    make_figures()
    write_text(PAPER / "FINAL_PAPER_ANALYSIS.md", f"""
# Direction5 final paper analysis

## Decision

**{FINAL_STATE}**

The corrected question is material in four of six registered mechanism/tension
cells, and the observer, finite-sample deliverability set, contract/online
semantics, recourse formulation and bounded Plant-A certificates are supported.
The unique DCSV-CR-MPC method is not supported as a performance contribution.

Against contract-only rolling MPC, both-success scenario-balanced improvement
was 0.23% for frequency peak, 3.21% for ACE IAE and -9.07% for tie RMS; no metric
reached +8% with a positive hierarchical-bootstrap lower bound. Proposed success
dropped 2.73 pp, terminal recovery dropped 3.64 pp, known backup was 6.86%, and
Plant A/B directions disagreed. All seven methods failed the registered synthetic
normal1h frequency-quality Gate, so no paper-ready controller claim is allowed.

Final seeds 100–159 were not run. R6 and R7 are `NOT_EVALUATED`, not failures.
There will be no new Direction5 phase or substitute method.
""")
    write_text(STATUS_DIR / "FINAL_DECISION.md", f"""
# Unique final status

```text
{FINAL_STATE}
```

R5 failed after the two permitted ordered audits. R6 final lock and R7 final
seeds were therefore not evaluated. The negative status preserves materiality,
observer/estimator and bounded theory findings while rejecting the registered
DCSV-CR performance claim.
""")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
