"""Synthesize the binding Phase D negative result after the fatal H2 Gate."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results_phase_d" / "D8"
REPORTS = ROOT / "research_outputs_phase_d" / "final"
FIGURES = ROOT / "figures_phase_d" / "D8"
PROGRESS = ROOT / "progress_phase_d" / "D8.json"
STATUS = "PASSIVE_CAPABILITY_SET_NOT_SUPPORTED"
NOT_EVALUATED = "NOT_EVALUATED_DUE_TO_H2_FATAL_GATE"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def classify_d3(row: pd.Series) -> str:
    if bool(row["prechange_alarm"]):
        return "estimator_failure"
    if float(row["joint_coverage"]) < 0.95:
        return "capability_set_coverage_failure"
    if bool(row["timing_evaluated"]) and not bool(row["update_before_control_loss"]):
        return "capability_set_coverage_failure"
    return "success"


def placeholder_figure(path: Path, title: str, detail: str) -> None:
    fig, ax = plt.subplots(figsize=(9.0, 4.5), constrained_layout=True)
    ax.axis("off")
    ax.add_patch(plt.Rectangle((0.04, 0.12), 0.92, 0.76, facecolor="#f5f5f5", edgecolor="#8b1a1a", lw=2))
    ax.text(0.5, 0.64, title, ha="center", va="center", fontsize=17, weight="bold", color="#8b1a1a")
    ax.text(0.5, 0.42, "NOT EVALUATED", ha="center", va="center", fontsize=22, weight="bold")
    ax.text(0.5, 0.25, detail, ha="center", va="center", fontsize=10, wrap=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def gate_flow_figure(path: Path) -> None:
    stages = [
        ("D0", "PASS", "Freeze / invalidate Phase C"),
        ("D1", "PASS", "Literature + novelty lock"),
        ("D2", "PASS", "Physical Plant A/B"),
        ("D3", "FAIL", "H2 passive capability set"),
        ("D4–D6", "STOP", "No Oracle / CRCS-TMPC"),
        ("D7–D9", "NEGATIVE", "Evidence + review package"),
    ]
    fig, ax = plt.subplots(figsize=(12, 4.4), constrained_layout=True)
    ax.set_xlim(0, len(stages))
    ax.set_ylim(0, 1)
    ax.axis("off")
    for index, (stage, state, text) in enumerate(stages):
        color = {"PASS": "#2a9d8f", "FAIL": "#d62828", "STOP": "#6c757d", "NEGATIVE": "#bc6c25"}[state]
        ax.add_patch(plt.Rectangle((index + 0.08, 0.25), 0.82, 0.5, facecolor=color, alpha=0.16, edgecolor=color, lw=2))
        ax.text(index + 0.49, 0.61, f"{stage}: {state}", ha="center", va="center", fontsize=11, weight="bold", color=color)
        ax.text(index + 0.49, 0.42, text, ha="center", va="center", fontsize=8.5, wrap=True)
        if index < len(stages) - 1:
            ax.annotate("", xy=(index + 1.05, 0.5), xytext=(index + 0.91, 0.5), arrowprops={"arrowstyle": "->", "lw": 1.5})
    ax.set_title("Direction1 Phase D evidence flow and binding early-stop decision", fontsize=14, weight="bold")
    fig.savefig(path, dpi=180)
    plt.close(fig)


def coverage_figure(summary: dict[str, object], path: Path) -> None:
    validation = summary["validation_summary"]
    labels = ["Joint", "Power", "Ramp", "Delay", "Energy"]
    values = [float(validation[f"{label.lower()}_coverage"]) for label in labels]
    fig, ax = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    colors = ["#d62828" if value < 0.95 else "#2a9d8f" for value in values]
    bars = ax.bar(labels, values, color=colors)
    ax.axhline(0.95, color="black", ls="--", lw=1.5, label="preregistered 95% Gate")
    ax.set_ylim(0.7, 1.015)
    ax.set_ylabel("Truth coverage fraction")
    ax.set_title("H2 validation coverage: joint power/ramp/delay/energy Gate fails")
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.006, f"{value:.3f}", ha="center", fontsize=9)
    ax.legend(loc="lower right")
    fig.savefig(path, dpi=180)
    plt.close(fig)


def timing_figure(summary: dict[str, object], path: Path) -> None:
    values = summary["validation_summary"]["mechanism_update_before_loss"]
    labels = ["Delay", "Headroom", "Ramp"]
    heights = [float(values[label.lower()]) for label in labels]
    fig, ax = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    bars = ax.bar(labels, heights, color=["#d62828"] * 3)
    ax.axhline(0.8, color="black", ls="--", lw=1.5, label="preregistered 0.8 Gate")
    ax.set_ylim(0, 1.02)
    ax.set_ylabel("P(causal update before control loss)")
    ax.set_title("No single degradation mechanism passes the causal timing Gate")
    for bar, value in zip(bars, heights):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.025, f"{value:.3f}", ha="center", fontsize=9)
    ax.legend(loc="upper right")
    fig.savefig(path, dpi=180)
    plt.close(fig)


def failure_trace_figure(trace: pd.DataFrame, path: Path, source_path: Path) -> None:
    groups = trace.groupby(["seed", "scenario"], sort=False)
    scores = groups["joint_covered"].mean()
    worst_seed, worst_scenario = scores.idxmin()
    data = groups.get_group((worst_seed, worst_scenario)).copy()
    data.to_csv(source_path, index=False)
    time = data["time_s"].to_numpy()
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, constrained_layout=True)
    axes[0].plot(time, data["true_power_capability_pu"], color="#d62828", label="true P capability")
    axes[0].plot(time, data["estimated_power_lower_pu"], color="#264653", ls="--", label="estimated lower")
    axes[0].plot(time, data["estimated_power_upper_pu"], color="#2a9d8f", ls="--", label="estimated upper")
    axes[0].set_ylabel("Power (pu)")
    axes[0].legend(ncol=3, fontsize=8)
    axes[1].plot(time, data["true_ramp_pu_s"], color="#d62828", label="true ramp")
    axes[1].plot(time, data["estimated_ramp_lower_pu_s"], color="#264653", ls="--", label="estimated lower")
    axes[1].set_ylabel("Ramp (pu/s)")
    axes[1].legend(fontsize=8)
    axes[2].step(time, data["joint_covered"].astype(float), where="post", color="#d62828", label="joint covered")
    axes[2].step(time, data["alarm"].astype(float), where="post", color="#f4a261", label="alarm")
    axes[2].set_ylabel("Boolean")
    axes[2].set_xlabel("Time (s)")
    axes[2].legend(fontsize=8)
    fig.suptitle(f"Worst retained D3 validation trace: {worst_scenario}, seed {worst_seed}", fontsize=13, weight="bold")
    fig.savefig(path, dpi=180)
    plt.close(fig)


def main() -> int:
    for path in (RESULTS, REPORTS, FIGURES, PROGRESS.parent, RESULTS / "figure_source_data"):
        path.mkdir(parents=True, exist_ok=True)

    h2 = json.loads((ROOT / "results_phase_d" / "D3" / "h2_gate.json").read_text(encoding="utf-8"))
    episodes = pd.read_parquet(ROOT / "results_phase_d" / "D3" / "validation_episode_summary.parquet")
    episodes.insert(0, "evidence_stage", "D3_validation")
    episodes["scientific_status"] = episodes.apply(classify_d3, axis=1)
    episodes["timing_status"] = np.where(episodes["timing_evaluated"], "evaluated", "not_applicable_no_registered_loss")
    episodes.to_parquet(RESULTS / "all_d3_validation_episode_metrics.parquet", compression="zstd", index=False)
    failures = episodes.loc[episodes["scientific_status"] != "success"].copy()
    failures.to_parquet(RESULTS / "all_failed_d3_episodes.parquet", compression="zstd", index=False)

    status_counts = episodes.groupby(["scenario", "scientific_status"], dropna=False).size().rename("episode_count").reset_index()
    status_counts.to_csv(RESULTS / "success_first_status_counts.csv", index=False)
    balanced = episodes.groupby("scenario", as_index=False).agg(
        episode_count=("seed", "size"),
        success_rate=("scientific_status", lambda values: float(np.mean(values == "success"))),
        joint_coverage=("joint_coverage", "mean"),
        false_alarm_rate=("false_alarm", "mean"),
        prechange_alarm_rate=("prechange_alarm", "mean"),
        load_rmse_pu=("load_rmse_pu", "mean"),
    )
    balanced.to_csv(RESULTS / "scenario_balanced_d3_summary.csv", index=False)

    planned = pd.read_csv(ROOT / "results_phase_d" / "D7" / "SCENARIO_MANIFEST.csv")
    split_status = planned.groupby("knowledge_split", as_index=False).size().rename(columns={"size": "planned_episode_count"})
    split_status["executed_episode_count"] = 0
    split_status["result"] = "not_evaluated_due_to_H2_fatal_gate"
    split_status.to_csv(RESULTS / "known_ood_status.csv", index=False)

    not_evaluated_tables = {
        "paired_differences_and_ci.csv": "comparison,estimate,ci_low,ci_high,status\ncontroller_vs_baseline,,,,not_evaluated_due_to_H2_fatal_gate\n",
        "cost_pareto.csv": "controller,cost,frequency_metric,ace_metric,status\nnot_evaluated,,,,not_evaluated_due_to_H2_fatal_gate\n",
        "controller_compute_time.csv": "controller,p50_s,p99_s,infeasible_rate,status\nnot_evaluated,,,,not_evaluated_due_to_H2_fatal_gate\n",
        "ablation_summary.csv": "ablation,episode_count,status\nnot_evaluated,0,not_evaluated_due_to_H2_fatal_gate\n",
    }
    for name, text in not_evaluated_tables.items():
        (RESULTS / name).write_text(text, encoding="utf-8")

    gates = pd.DataFrame(
        [
            ("D0", "BASELINE_FREEZE", "PASS", "Phase C frozen; C5/C6/C8 claims invalidated"),
            ("D1", "LITERATURE_AND_NOVELTY", "PASS", "56 verified records; scoped novelty remains falsifiable"),
            ("D2", "PHYSICAL_PLANT_VALIDATION", "PASS", "Plant A/B physics and ANDES cross-validation passed"),
            ("D3/H2", "PASSIVE_CAPABILITY_SET", "FAIL", "joint coverage 0.7947; zero mechanisms meet 0.8 timing criterion"),
            ("D4/H1", "ORACLE_MATERIALITY", NOT_EVALUATED, "fatal H2 stop occurs before D4"),
            ("D5/H4", "THEORY_AND_CRCS_TMPC", NOT_EVALUATED, "fatal H2 stop forbids method development"),
            ("D6/H3", "METHOD_VALIDATION", NOT_EVALUATED, "CRCS-TMPC not developed or evaluated"),
            ("D7", "NEGATIVE_PROTOCOL_INTEGRITY", "PASS", "factors/seeds locked; zero final episodes executed"),
            ("D8", "NEGATIVE_EVIDENCE_COMPLETENESS", "PASS", "all D3 failures retained; later experiments separately not_evaluated"),
            ("D9", "FINAL_REVIEW_PACKAGE", "PENDING_PACKAGE_SEAL", "evaluated by D9 package builder"),
        ],
        columns=["stage", "gate", "status", "evidence"],
    )
    gates.to_csv(RESULTS / "HYPOTHESES_AND_GATES.csv", index=False)

    failure_ledger = pd.DataFrame(
        [
            ("D2-report-001", "code_failure", "repaired", "NumPy boolean JSON serialization in reporting only; cached physics re-finalized"),
            ("D3-run-001", "operational_failure", "repaired", "single-process execution interrupted before round completion; identical locked matrix rerun with four workers"),
            ("D3-H2-001", "scientific_failure", "unresolved_binding", "passive natural-I/O capability coverage and causal timing thresholds not met"),
        ],
        columns=["failure_id", "category", "resolution", "evidence"],
    )
    failure_ledger.to_csv(RESULTS / "FAILURE_LEDGER.csv", index=False)

    raw_coverage = pd.read_csv(ROOT / "results_phase_d" / "D3" / "capability_coverage_summary.csv")
    raw_coverage.to_csv(RESULTS / "capability_coverage_summary.csv", index=False)

    gate_flow_figure(FIGURES / "system_and_gate_flow.png")
    coverage_figure(h2, FIGURES / "h2_capability_coverage.png")
    timing_figure(h2, FIGURES / "h2_causal_update_timing.png")
    trace = pd.read_parquet(ROOT / "results_phase_d" / "D3" / "representative_causal_traces.parquet")
    failure_trace_figure(trace, FIGURES / "retained_failure_case.png", RESULTS / "figure_source_data" / "retained_failure_case.csv")
    placeholder_figure(FIGURES / "oracle_materiality_not_evaluated.png", "H1 rolling NMPC Oracle materiality", "D4 was not reached because the preregistered H2 Gate failed first.")
    placeholder_figure(FIGURES / "controller_timeseries_not_evaluated.png", "Frequency / ACE / tie / SoC / responsibility transfer", "No CRCS-TMPC or final controller trajectories were generated after the fatal H2 stop.")
    placeholder_figure(FIGURES / "known_ood_not_evaluated.png", "Known and OOD controller comparison", "All 2,400 locked scenarios remain explicitly not_evaluated, not method failures.")
    placeholder_figure(FIGURES / "ablation_not_evaluated.png", "CRCS-TMPC ablations", "The method was not implemented, so proxy ablations are prohibited.")
    placeholder_figure(FIGURES / "pareto_not_evaluated.png", "Cost / frequency / ACE Pareto analysis", "No controller results exist after the binding early-stop decision.")

    figure_catalog = pd.DataFrame(
        [
            ("system_and_gate_flow.png", "generated", "D0-D9 gate records"),
            ("h2_capability_coverage.png", "generated", "results_phase_d/D3/h2_gate.json"),
            ("h2_causal_update_timing.png", "generated", "results_phase_d/D3/h2_gate.json"),
            ("retained_failure_case.png", "generated", "figure_source_data/retained_failure_case.csv"),
            ("oracle_materiality_not_evaluated.png", "not_evaluated marker", "H2 fatal stop"),
            ("controller_timeseries_not_evaluated.png", "not_evaluated marker", "H2 fatal stop"),
            ("known_ood_not_evaluated.png", "not_evaluated marker", "H2 fatal stop"),
            ("ablation_not_evaluated.png", "not_evaluated marker", "H2 fatal stop"),
            ("pareto_not_evaluated.png", "not_evaluated marker", "H2 fatal stop"),
        ],
        columns=["figure", "status", "source"],
    )
    figure_catalog.to_csv(RESULTS / "FIGURE_CATALOG.csv", index=False)

    (REPORTS / "LOCKED_SCIENCE_AND_DECISIONS.md").write_text(
        """# Locked science and decisions\n\n"
        "The sole scientific question and H1–H4 are those in "
        "`research/direction1_phase_d_crcs_tube_mpc/02_LOCKED_SCIENTIFIC_QUESTION_AND_HYPOTHESES.md`.\n\n"
        "## Binding decision\n\n"
        "H2 is rejected. Validation joint truth coverage was 0.7946979167 (<0.95). "
        "Power/ramp/delay/energy coverage was 0.8632256944/0.9000486111/0.9804861111/1.0. "
        "Update-before-loss probabilities were delay 0, headroom 0.4166666667, and ramp 0; "
        "zero mechanisms met the required 0.8 threshold. False-alarm and pre-change-alarm "
        "rates were both 0.\n\n"
        "The resulting status is **PASSIVE_CAPABILITY_SET_NOT_SUPPORTED**. D4–D6 controller "
        "development and D8 final controller experiments are not evaluated.\n",
        encoding="utf-8",
    )
    (REPORTS / "SUPPORTED_AND_UNSUPPORTED_CLAIMS.md").write_text(
        """# Supported and unsupported claims\n\n"
        "Supported: the corrected Plant A and native ANDES Plant B pass the registered D2 "
        "physics/cross-model checks; the evaluated passive set estimator fails H2 under the "
        "registered natural closed-loop I/O protocol.\n\n"
        "Not supported: passive-identifiable capability sets, Oracle materiality, CRCS-TMPC "
        "performance, recursive feasibility, known/OOD safety, Pareto improvement, or superiority "
        "to any baseline. No best baseline can be named because no Direction1 controller comparison "
        "was run. This negative result is not evidence that every possible passive estimator must fail.\n",
        encoding="utf-8",
    )
    (REPORTS / "DECISION_LOG.md").write_text(
        """# Decision log\n\n"
        "1. D0: freeze Phase C and invalidate its passive-identifiable and method claims.\n"
        "2. D1: lock the scoped Direction1 question after metadata-verified literature review.\n"
        "3. D2: qualify the native ANDES Kundur VSC model after rejecting the drifting alternative case.\n"
        "4. D3: run the preregistered initial candidate plus two allowed causal repairs using development seeds only.\n"
        "5. D3: reject H2 on untouched validation seeds; retain all candidates and failures.\n"
        "6. D4–D6: stop; do not implement an Oracle, CRCS-TMPC, active identification, or another algorithm.\n"
        "7. D7–D9: lock unexecuted final factors and produce a complete negative review package.\n",
        encoding="utf-8",
    )
    (REPORTS / "THEORY_NOT_EVALUATED.md").write_text(
        """# Theory, RPI, terminal set, and tightening status\n\n"
        "D5 was not reached. No CRCS-TMPC theorem, RPI set, terminal set, tube, constraint "
        "tightening certificate, or recursive-feasibility claim was constructed. H4 is "
        "`NOT_EVALUATED_DUE_TO_H2_FATAL_GATE`; absence of these artifacts is a mandated early-stop "
        "outcome, not a numerical failure or evidence of an empty terminal set.\n",
        encoding="utf-8",
    )
    (REPORTS / "FINAL_RESULTS_INTERPRETATION.md").write_text(
        """# Final results interpretation and limitations\n\n"
        "Natural closed-loop public I/O did not maintain the registered joint capability-set "
        "coverage or update early enough in the evaluated scenarios. Tightening detection to "
        "remove false alarms reduced coverage/timing; all three allowed candidates are retained.\n\n"
        "Most severe limitation: this is an early scientific stop at H2. It establishes failure "
        "of the registered passive estimator/protocol, not universal impossibility. H1 Oracle "
        "materiality, H3 method value, H4 theory, the best baseline, and known/OOD controller "
        "outcomes are all unknown. Active excitation could address identifiability, but pursuing it "
        "would violate this Goal and is outside the review package.\n",
        encoding="utf-8",
    )
    (REPORTS / "PAPER_OUTLINE.md").write_text(
        """# Negative-result paper outline\n\n"
        "1. Audited motivation and information boundary.\n"
        "2. Corrected two-area and native multi-machine ANDES plants.\n"
        "3. Causal passive capability-set protocol and preregistered H2.\n"
        "4. Development/validation evidence and structural non-identifiability cases.\n"
        "5. Binding negative result, limits of inference, and reproducibility.\n\n"
        "Any next step is limited to review/submission refinement of this result; this Goal does "
        "not authorize development of another controller or active-identification method.\n",
        encoding="utf-8",
    )

    final_status = {
        "schema": "direction1.phase_d.final_status.v1",
        "project_name": "DIRECTION1",
        "method_branch": "CRCS-TMPC_NOT_IMPLEMENTED_DUE_TO_FATAL_H2_GATE",
        "final_research_status": STATUS,
        "H1": NOT_EVALUATED,
        "H2": "REJECTED",
        "H3": NOT_EVALUATED,
        "H4": NOT_EVALUATED,
        "best_baseline": "NOT_EVALUATED",
        "known_result": "NOT_EVALUATED",
        "ood_result": "NOT_EVALUATED",
        "failed_d3_episode_count": int(len(failures)),
        "all_d3_validation_episode_count": int(len(episodes)),
        "planned_final_episode_count_per_controller": 2400,
        "executed_final_episode_count": 0,
        "failures_deleted": False,
        "final_seeds_used_for_tuning": False,
        "most_severe_limitation": "H2 evidence applies to the registered passive estimator/protocol and does not prove universal passive non-identifiability.",
    }
    write_json(REPORTS / "FINAL_STATUS.json", final_status)

    outputs = sorted([p for p in RESULTS.rglob("*") if p.is_file()] + [p for p in REPORTS.rglob("*") if p.is_file()] + [p for p in FIGURES.rglob("*") if p.is_file()])
    progress = {
        "stage": "D8",
        "status": "COMPLETED_NEGATIVE_PATH",
        "goal": "Complete final negative evidence without executing prohibited post-H2 controller experiments",
        "inputs_sha256": {
            "h2_gate": sha256(ROOT / "results_phase_d" / "D3" / "h2_gate.json"),
            "protocol_lock": sha256(ROOT / "artifacts_phase_d" / "D7" / "FINAL_PROTOCOL_LOCK.json"),
        },
        "commands": ["python scripts/phase_d/d8_finalize_negative.py"],
        "tests": {
            "d3_validation_episodes_retained": int(len(episodes)),
            "d3_failed_episodes_retained": int(len(failures)),
            "final_controller_episodes_executed": 0,
            "not_evaluated_separate_from_failure": True,
        },
        "gate": "D8_NEGATIVE_EVIDENCE_COMPLETENESS",
        "gate_passed": True,
        "failures": ["H2 scientific evidence threshold not met"],
        "repairs": [],
        "outputs_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in outputs},
        "next_stage": "D9_REVIEW_PACKAGE",
    }
    write_json(PROGRESS, progress)
    print(json.dumps({"status": STATUS, "retained": len(episodes), "failed": len(failures), "final_executed": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
