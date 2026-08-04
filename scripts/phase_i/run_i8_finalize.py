"""Seal Phase I evidence, claims, figures, and the only allowed end state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "results_phase_i"
FINAL_RESULTS = RESULTS / "final"
FINAL_DOCS = REPO / "research_outputs_phase_i/08_FINAL"
FIGURES = REPO / "figures_phase_i/I8"
PROGRESS = REPO / "progress_phase_i"
ALLOWED_OUTCOMES = {
    "PAPER_READY_WITH_BOUNDED_CLAIMS",
    "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", "utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.strip() + "\n", "utf-8")


def dataframe_markdown(frame: pd.DataFrame) -> str:
    """Render a compact Markdown table without pandas' optional tabulate."""
    columns = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for values in frame.itertuples(index=False, name=None):
        escaped = [str(value).replace("|", "\\|").replace("\n", " ") for value in values]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True, encoding="utf-8").strip()


def stage_gates(i6: dict[str, Any], package_verified: bool) -> dict[str, str]:
    gates = {}
    for stage in range(6):
        progress = read_json(PROGRESS / f"I{stage}.json")
        if progress.get("status") == "PASS" or progress.get("gate_passed") is True:
            gates[f"I{stage}"] = "PASS"
        elif progress.get("status"):
            gates[f"I{stage}"] = str(progress["status"])
        else:
            gates[f"I{stage}"] = "FAIL"
    gates["I6"] = "PASS" if i6["method_gate_passed"] else "FAIL"
    gates["I7"] = "PASS" if i6["method_gate_passed"] else "NOT_EVALUATED"
    gates["I8"] = "PASS" if package_verified else "PENDING_PACKAGE_VERIFICATION"
    return gates


def summarize_condition(episodes: pd.DataFrame) -> list[dict[str, Any]]:
    evaluated = episodes[episodes.evaluation_status.eq("EVALUATED")]
    rows = []
    for (condition, method), group in evaluated.groupby(["condition", "method"], dropna=False):
        rows.append({
            "condition": str(condition),
            "method": str(method),
            "episodes": len(group),
            "physical_success_rate": float(group.physical_success.mean()),
            "frequency_peak_mean_hz": float(group.frequency_peak_hz.mean()),
            "ace_iae_mean_pu_s": float(group.ace_iae_pu_s.mean()),
            "tie_rms_mean_pu": float(group.tie_rms_pu.mean()),
        })
    return rows


def save_figure(fig: plt.Figure, stem: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / f"{stem}.svg", bbox_inches="tight")
    fig.savefig(FIGURES / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(FIGURES / f"{stem}.png", bbox_inches="tight", dpi=600)
    plt.close(fig)


def make_figures(episodes: pd.DataFrame, normals: pd.DataFrame) -> None:
    metrics = pd.read_csv(RESULTS / "I6/PAIRED_CORE_METRICS.csv")
    fig, axis = plt.subplots(figsize=(7.2, 4.2))
    values = 100.0 * metrics.mean_relative_improvement.to_numpy()
    lower = 100.0 * metrics.cluster_bootstrap_ci_lower.to_numpy()
    upper = 100.0 * metrics.cluster_bootstrap_ci_upper.to_numpy()
    axis.bar(metrics.metric, values, color=["#2A6F97", "#468FAF", "#61A5C2"])
    axis.errorbar(np.arange(len(values)), values, yerr=np.vstack((values-lower, upper-values)), fmt="none", color="black", capsize=4)
    axis.axhline(8.0, color="#B23A48", linestyle="--", label="registered 8%")
    axis.axhline(0.0, color="black", linewidth=0.8)
    axis.set_ylabel("Failure-aware paired improvement (%)")
    axis.set_title("I6 locked validation: DCSV-MPC vs deployable baseline")
    axis.tick_params(axis="x", rotation=18)
    axis.legend()
    fig.tight_layout(); save_figure(fig, "I6_PAIRED_CORE_METRICS")

    directions = pd.read_csv(RESULTS / "I6/PLANT_DIRECTION_CONSISTENCY.csv")
    fig, axis = plt.subplots(figsize=(6.8, 4.0))
    axis.bar(directions.plant, 100.0 * directions.frequency_relative_improvement, color=["#2A9D8F", "#E9C46A"])
    axis.axhline(0.0, color="black", linewidth=0.8)
    axis.set_ylabel("Paired frequency-peak improvement (%)")
    axis.set_title("Plant-direction audit")
    axis.tick_params(axis="x", rotation=12)
    fig.tight_layout(); save_figure(fig, "PLANT_DIRECTION_AUDIT")

    evaluated = episodes[episodes.evaluation_status.eq("EVALUATED")]
    success = evaluated.groupby(["condition", "method"]).physical_success.mean().unstack()
    fig, axis = plt.subplots(figsize=(6.8, 4.0))
    success.plot(kind="bar", ax=axis, color=["#264653", "#F4A261"])
    axis.set_ylim(0.0, 1.0); axis.set_ylabel("Physical success rate")
    axis.set_title("Known/OOD validation success")
    axis.tick_params(axis="x", rotation=0)
    fig.tight_layout(); save_figure(fig, "KNOWN_OOD_SUCCESS")

    fig, axis = plt.subplots(figsize=(6.8, 4.0))
    normal_summary = normals.groupby("method").frequency_peak_hz.agg(["mean", "max"])
    normal_summary.plot(kind="bar", ax=axis, color=["#457B9D", "#A8DADC"])
    axis.set_ylabel("Frequency peak (Hz)"); axis.set_title("Genuine 3600 s normal-profile runs")
    axis.tick_params(axis="x", rotation=0)
    fig.tight_layout(); save_figure(fig, "NORMAL1H_FREQUENCY")

    fig, axis = plt.subplots(figsize=(10.0, 3.2)); axis.axis("off")
    boxes = [
        (0.02, "Public measurements\nfrequency, tie, SG, actual POI, SoC"),
        (0.27, "Actual-POI load observer\nslow persistent load state"),
        (0.52, "Causal set-membership/MHE\npower, ramp, delay envelope"),
        (0.77, "DCSV-MPC\nsustainable / bridge / infeasible"),
    ]
    for x, label in boxes:
        axis.text(x, 0.5, label, transform=axis.transAxes, ha="left", va="center",
                  bbox={"boxstyle": "round,pad=0.5", "facecolor": "#EDF6F9", "edgecolor": "#006D77"}, fontsize=9)
    for x in (0.235, 0.485, 0.735):
        axis.annotate("", xy=(x+0.025, 0.5), xytext=(x, 0.5), xycoords=axis.transAxes,
                      arrowprops={"arrowstyle": "->", "color": "#006D77", "lw": 1.5})
    axis.set_title("Direction5 Phase-I causal information flow")
    fig.tight_layout(); save_figure(fig, "SYSTEM_METHOD_DIAGRAM")

    fig, axis = plt.subplots(figsize=(9.2, 4.2)); axis.axis("off")
    axis.text(0.08, 0.78, "Load-parameterized\ndomain supervisor", transform=axis.transAxes,
              ha="center", va="center", bbox={"boxstyle": "round,pad=0.5", "facecolor": "#E9ECEF"})
    branches = [
        (0.46, 0.84, "SUSTAINABLE\nlocal Plant-A RPI\nconditional terminal constraint", "#D8F3DC"),
        (0.46, 0.50, "BRIDGE\npower-ramp-energy clock\nslow-reserve handoff", "#FFF3B0"),
        (0.46, 0.16, "PHYSICALLY INFEASIBLE\nearly certificate\nnot controller failure", "#FFCCD5"),
    ]
    for x, y, label, color in branches:
        axis.text(x, y, label, transform=axis.transAxes, ha="center", va="center",
                  bbox={"boxstyle": "round,pad=0.5", "facecolor": color, "edgecolor": "#495057"}, fontsize=9)
        axis.annotate("", xy=(x-0.13, y), xytext=(0.17, 0.76), xycoords=axis.transAxes,
                      arrowprops={"arrowstyle": "->", "color": "#495057"})
    axis.text(0.82, 0.50, "Rolling DCSV-MPC\ncommon control sequence\npower/ramp/delay/SoC constraints\nrestoration + transactional commit",
              transform=axis.transAxes, ha="center", va="center",
              bbox={"boxstyle": "round,pad=0.55", "facecolor": "#DDEAF7", "edgecolor": "#1D3557"}, fontsize=9)
    for y in (0.84, 0.50):
        axis.annotate("", xy=(0.69, 0.53), xytext=(0.59, y), xycoords=axis.transAxes,
                      arrowprops={"arrowstyle": "->", "color": "#1D3557"})
    axis.set_title("DCSV-MPC domain and certificate routing")
    fig.tight_layout(); save_figure(fig, "DCSV_DOMAIN_CERTIFICATE_DIAGRAM")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-verification", type=Path)
    args = parser.parse_args()
    package_verified = False
    verification: dict[str, Any] | None = None
    if args.package_verification:
        verification = read_json(args.package_verification.resolve())
        package_verified = bool(
            verification.get("manifest_ok")
            and verification.get("minimal_replay_ok")
            and verification.get("fresh_extract")
        )
        if not package_verified:
            raise RuntimeError("package verification record is not a successful fresh-extract verification")

    i6 = read_json(RESULTS / "I6/I6_SUMMARY.json")
    episodes = pd.read_parquet(RESULTS / "I6/VALIDATION_EPISODES.parquet")
    normals = pd.read_parquet(RESULTS / "I6/NORMAL1H_EPISODES.parquet")
    hypotheses = pd.read_csv(RESULTS / "I6/HYPOTHESES_H1_H6.csv")
    if i6["method_gate_passed"]:
        i7_summary_path = RESULTS / "I7/I7_SUMMARY.json"
        if not i7_summary_path.is_file():
            raise RuntimeError("I6 passed: commit a final lock and complete one-shot I7 before finalization")
        i7 = read_json(i7_summary_path)
        if i7.get("status") != "PASS" or not i7.get("final_seeds_consumed"):
            raise RuntimeError("I7 evidence is incomplete")
        outcome = "PAPER_READY_WITH_BOUNDED_CLAIMS"
    else:
        i7 = {
            "stage": "I7", "status": "NOT_EVALUATED", "gate": "NOT_EVALUATED",
            "reason": "REGISTERED_I6_STOP", "known_result": "NOT_EVALUATED",
            "ood_result": "NOT_EVALUATED", "final_seeds_consumed": False,
            "algorithm_tuned_after_validation": False,
        }
        write_json(PROGRESS / "I7.json", i7)
        not_evaluated = pd.DataFrame([{
            "stage": "I7", "item": "final_known_ood_seeds_100_159", "status": "NOT_EVALUATED",
            "reason": "REGISTERED_I6_METHOD_GATE_STOP", "counted_as_success": False,
            "counted_as_failure": False, "final_seeds_consumed": False,
        }])
        path = RESULTS / "I7/NOT_EVALUATED_REGISTER.csv"; path.parent.mkdir(parents=True, exist_ok=True)
        not_evaluated.to_csv(path, index=False)
        outcome = "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE"
    assert outcome in ALLOWED_OUTCOMES

    gates = stage_gates(i6, package_verified)
    gate_table = pd.DataFrame([{"stage": key, "status": value} for key, value in gates.items()])
    FINAL_RESULTS.mkdir(parents=True, exist_ok=True); FINAL_DOCS.mkdir(parents=True, exist_ok=True)
    gate_table.to_csv(FINAL_RESULTS / "ALL_GATES.csv", index=False)
    hypotheses.to_csv(FINAL_RESULTS / "HYPOTHESES_H1_H6.csv", index=False)

    condition_summary = summarize_condition(episodes)
    pd.DataFrame(condition_summary).to_csv(FINAL_RESULTS / "KNOWN_OOD_VALIDATION_SUMMARY.csv", index=False)
    normal_summary = normals.groupby("method").agg(
        episodes=("scenario_id", "size"),
        physical_success_rate=("physical_success", "mean"),
        frequency_peak_mean_hz=("frequency_peak_hz", "mean"),
        frequency_peak_max_hz=("frequency_peak_hz", "max"),
        hard_violations=("hard_violation", "sum"),
        controller_calls=("controller_calls", "sum"),
    ).reset_index()
    normal_summary.to_csv(FINAL_RESULTS / "NORMAL1H_SUMMARY.csv", index=False)

    claims = pd.DataFrame([
        ("Phase H H7 method evidence", "WITHDRAWN", "I0 reproduced confounding, artificial normal rows, held tail and reduced Plant B"),
        ("Full nonlinear Plant A", "SUPPORTED", "I2 and I6 full-event traces"),
        ("Native ANDES Plant B", "SUPPORTED_EMPIRICALLY", "I2 and I6 native-network/convergence/balance audit"),
        ("Actual-POI causal observer", "SUPPORTED", "I3 coverage and confusion audit"),
        ("Power/ramp/delay deliverability set", "SUPPORTED_WITH_FINITE_SAMPLE_SCOPE", "I3 one-sided coverage lower bound"),
        ("DCSV-MPC deployment advantage", "SUPPORTED" if i6["method_gate_passed"] else "NOT_SUPPORTED", "locked I6 paired Gate"),
        ("Recursive feasibility", "SUPPORTED_LOCALLY_PLANT_A_ONLY", "I5 conditional local RPI assumptions"),
        ("Bridge guarantee", "FINITE_HORIZON_ONLY", "I5 power-ramp-energy certificate; slow handoff required"),
        ("Native Plant B recursive certificate", "UNSUPPORTED", "native DAE retained as empirical validation only"),
        ("Same-instant unknown capability guarantee", "IMPOSSIBLE_WITHOUT_CONTRACT_OR_RESERVE", "I5 indistinguishability boundary"),
    ], columns=["claim", "status", "evidence"])
    claims.to_csv(FINAL_RESULTS / "SUPPORTED_UNSUPPORTED_CLAIMS.csv", index=False)

    failure_ledger = pd.read_csv(RESULTS / "I6/FAILURE_LEDGER.csv")
    failure_ledger["stage"] = "I6"
    failure_ledger.to_csv(FINAL_RESULTS / "FAILURE_LEDGER.csv", index=False)
    risks = pd.DataFrame([
        ("R1", "Native Plant B has no rigorous RPI certificate", "HIGH", "State empirical scope explicitly; no recursive claim"),
        ("R2", "Finite validation cannot prove arbitrary performance envelope", "HIGH", "Report sample count and one-sided lower bound"),
        ("R3", "Contract violations defeat same-instant guarantee", "HIGH", "Route to SG/slow reserve and exclude from guarantee Gate"),
        ("R4", "I6 execution required one infrastructure repair", "MEDIUM", "Retain interrupted checkpoint and process-isolated rerun record"),
        ("R5", "Final evidence absent after registered negative stop" if not i6["method_gate_passed"] else "Final evidence is one-shot", "HIGH", "Do not impute I7; preserve final firewall"),
    ], columns=["risk_id", "risk", "severity", "mitigation"])
    risks.to_csv(FINAL_RESULTS / "REVIEWER_RISK_REGISTER.csv", index=False)

    native = episodes[episodes.plant.eq("B_native_ANDES_Kundur")]
    domain_manifest = pd.read_csv(RESULTS / "I6/PLANT_A_VALIDATION_MANIFEST.csv")
    domain_counts = domain_manifest.domain.value_counts().to_dict()
    status = {
        "schema": "direction5.phase_i.final_status.v1",
        "project": "direction5", "project_upper": "DIRECTION5", "method": "DCSV-MPC",
        "final_research_status": outcome,
        "phase_h_h7_method_evidence_withdrawn": True,
        "gates": gates,
        "hypotheses_h1_h6": dict(zip(hypotheses.hypothesis, hypotheses.status)),
        "selected_observer": read_json(PROGRESS / "I3.json")["selected_observer"],
        "selected_capability_estimator": read_json(PROGRESS / "I3.json")["selected_capability_estimator"],
        "best_deployable_baseline": "fixed_allocation_pi",
        "plant_a_status": "FULL_NONLINEAR_FULL_EVENT_VALIDATION_COMPLETE",
        "plant_b_status": (
            "NATIVE_ANDES_FULL_EVENT_VALIDATION_COMPLETE"
            if bool(native.native_network.all() and native.native_converged.all())
            else "NATIVE_ANDES_VALIDATION_INCOMPLETE"
        ),
        "plant_b_native_method_rows": len(native),
        "plant_b_algebraic_balance_p99_max_pu": float(native.algebraic_power_balance_p99_pu.max()),
        "validation_known_ood": condition_summary,
        "final_known_result": i7["known_result"], "final_ood_result": i7["ood_result"],
        "normal1h_method_rows": len(normals),
        "normal1h_real_full_duration": bool((normals.duration_s == 3600.0).all() and normals.real_normal1h_provenance.notna().all()),
        "normal1h_hard_violations": int(normals.hard_violation.sum()),
        "solver_calls": i6["solver_calls"], "restoration_calls": i6["restoration_calls"],
        "fallback_calls": i6["fallback_calls"], "unresolved_math_infeasibility": i6["unresolved_math_infeasibility"],
        "p99_solve_time_s": i6["p99_solve_time_s"],
        "domain_statistics": {str(key): int(value) for key, value in domain_counts.items()},
        "certificate_status": "CONDITIONAL_LOCAL_RPI_PLUS_FINITE_HORIZON_BRIDGE",
        "recursive_feasibility_claim": "PLANT_A_LOCAL_ONLY_UNDER_EXPLICIT_ASSUMPTIONS",
        "native_plant_b_theory": "EMPIRICAL_VALIDATION_ONLY",
        "validation_repair_rounds_used": i6["validation_repair_rounds_used"],
        "final_seeds_consumed": bool(i7["final_seeds_consumed"]),
        "i6_failed_gates": i6["failed_gates"],
        "most_severe_failure": (
            "I6_REGISTERED_METHOD_GATE_FAILED: " + ", ".join(i6["failed_gates"])
            if i6["failed_gates"] else "NONE_WITHIN_REGISTERED_GATES"
        ),
        "most_severe_limitation": "NO_RIGOROUS_NATIVE_PLANT_B_RECURSIVE_FEASIBILITY_CERTIFICATE",
        "scientific_evidence_commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "package_fresh_extract_verified": package_verified,
        "package_verification": verification,
    }
    write_json(FINAL_RESULTS / "FINAL_STATUS.json", status)
    progress_i8 = {
        "stage": "I8", "status": "PASS" if package_verified else "PENDING_PACKAGE_VERIFICATION",
        "gate_passed": package_verified, "final_research_status": outcome,
        "package_fresh_extract_verified": package_verified,
        "final_seeds_consumed": bool(i7["final_seeds_consumed"]),
    }
    write_json(PROGRESS / "I8.json", progress_i8)
    make_figures(episodes, normals)

    failed = ", ".join(i6["failed_gates"]) if i6["failed_gates"] else "none"
    write_text(FINAL_DOCS / "PACKAGE_README.md", f"""
# Direction5 Phase-I final-convergence review package

Final research status: **{outcome}**. Phase H H7 is withdrawn as method
evidence. I0--I6 use corrected full-event evidence; I7 is
**{gates['I7']}**. The active method is DCSV-MPC and the strongest deployable
baseline is fixed-allocation PI. No AI/RL method is introduced.

Start with `17_FINAL_STATUS/FINAL_STATUS.json`, then inspect
`11_SUMMARY_TABLES/final/ALL_GATES.csv`, the failure ledger, raw episode and
control-cycle evidence, and the supported/unsupported claim table. Verify a
fresh extraction with the two scripts in `15_REPRODUCIBILITY`.
""")
    write_text(FINAL_DOCS / "FINAL_RESEARCH_REPORT.md", f"""
# Direction5 Phase-I final scientific report

## Outcome

**{outcome}**

Phase H H7 is not admissible method evidence. Phase I repaired the seed-factor
design, artificial normal rows, held tail, reduced Plant-B surrogate, and absent
unannounced capability transitions. It used full nonlinear Plant A, native
ANDES Kundur Plant B, nominal warm-up, actual BESS POI power in the load
observer, and causal power/ramp/delay deliverability sets.

## Locked I6 decision

Method Gate: **{'PASS' if i6['method_gate_passed'] else 'FAIL'}**. Failed
registered components: {failed}. Validation used {i6['plant_a_scenarios']} Plant-A
and {i6['plant_b_scenarios']} native Plant-B paired scenarios, plus
{i6['normal1h_method_rows']} genuine one-hour method runs. One execution-only
repair isolated native episodes after an OS-level process exit; no algorithm,
weight, threshold, factor, scenario, or seed changed.

## Claims

Conditional local Plant-A RPI sets and finite-horizon bridge certificates are
retained. Bridge claims require sufficient energy and slow-reserve handoff.
Native Plant B remains empirical only. Same-instant guarantee after an
unannounced contract violation is impossible without a valid contract floor or
independent reserve. Global or native-DAE recursive feasibility is not claimed.

## Final firewall

I7 status is **{gates['I7']}**; final seeds consumed: **{str(i7['final_seeds_consumed']).lower()}**.
No failed episode was deleted and NOT_EVALUATED is neither success nor failure.
""")
    write_text(FINAL_DOCS / "SUPPORTED_UNSUPPORTED_CLAIMS.md", "# Supported and unsupported claims\n\n" + dataframe_markdown(claims))
    write_text(FINAL_DOCS / "REVIEWER_RISK_REGISTER.md", "# Reviewer risk register\n\n" + dataframe_markdown(risks))
    paper_route = (
        "No affirmative method paper route is supported. Publish only a decisive negative/methodology report "
        "covering corrected full-event validation and bounded theoretical results."
        if not i6["method_gate_passed"] else
        "Proceed only with bounded claims: empirical native-plant evidence, conditional local RPI, and finite bridge certificates."
    )
    write_text(FINAL_DOCS / "PAPER_ROUTE.md", "# Paper route\n\n" + paper_route)
    write_text(FINAL_DOCS / "REPRODUCIBILITY_REPORT.md", f"""
# Reproducibility report

- Environment: repository-owned `topo_sfr`, Python 3.11 pins in `environment.yml`.
- Validation lock: `{i6['lock_sha256']}`.
- Scientific evidence commit at finalization: `{status['scientific_evidence_commit']}`.
- Final seeds consumed: `{str(status['final_seeds_consumed']).lower()}`.
- Package fresh-extract verified: `{str(package_verified).lower()}`.
- Manifest verification and minimal replay are mandatory and dependency-aware.
- Historical Phase H source is present only for I0 forensic replay; active
  Phase-I method source is `src/direction5freq`.
""")
    write_text(FINAL_DOCS / "MATHEMATICAL_APPENDIX.md", """
# Mathematical appendix and claim boundary

The recomputable certificate sources and numerical tables are in
`results_phase_i/I5` and `research_outputs_phase_i/06_THEORY`.

The hard-safety semantics use the contract guaranteed floor for power, ramp and
delay; measured SoC supplies the energy state. The online performance envelope
is revocable and can affect allocation cost, never a hard future guarantee.
For sustainable load-parameterized equilibria, Phase I certifies only local
Plant-A robust positively invariant boxes under the registered linearization,
disturbance bounds and admissibility constraints. For bridge cells, the claim
is finite-horizon power-ramp-energy feasibility plus a slow-reserve handoff.
Cells without sufficient energy/handoff receive no bridge guarantee. Native
Plant B has empirical closed-loop validation but no rigorous DAE RPI theorem.
The same-instant indistinguishability result rules out unconditional safety
after an unannounced capability drop below contract without independent reserve.
""")
    write_text(FINAL_DOCS / "CLOSEST_WORK_AND_NOVELTY.md", """
# Closest work and bounded novelty

The 70-source registry and closest-work matrix are in
`research_outputs_phase_i/02_LITERATURE`. No single registered source combines
actual-POI disturbance observation, causal command-to-actual power/ramp/delay
set estimation, contract-floor semantics, load-parameterized three-domain
viability routing, full rolling constrained MPC, and native RMS/DAE validation.
This intersection is the bounded novelty claim. The failed I6 method Gate means
novelty does not establish deployment advantage and H5 remains unsupported.
""")
    write_text(FINAL_DOCS / "FAILURE_DIAGNOSIS.md", f"""
# I6 failure diagnosis

The registered diagnostic order was followed. One OS/native execution exit was
repaired by fresh-process episode isolation without changing scientific inputs.
The completed run then showed {i6['fallback_calls']} fallback and
{i6['unresolved_math_infeasibility']} unresolved mathematical-infeasibility
cycles, concentrated in Plant-A delay-increase scenarios. Native Plant B and
normal1h had no fallback, yet native Plant-B frequency direction remained
negative. No second code/numerical defect was demonstrated. Changing weights,
horizon or thresholds after validation would be prohibited tuning, so the
diagnosis stops at METHOD and the negative Gate is retained.
""")
    print(json.dumps(status, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
