"""Generate the complete auditable Direction5 closure figure set."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
FIG = ROOT / "figures_closure" / "C4"
DATA = ROOT / "research_outputs_closure" / "04_FIGURES" / "SOURCE_DATA"
PROGRESS = ROOT / "progress_closure" / "C4.json"
COLORS = {"contract": "#4472C4", "dcsv": "#C00000", "oracle": "#70AD47", "online": "#ED7D31", "neutral": "#7F7F7F"}


def style(ax: plt.Axes, title: str, ylabel: str = "") -> None:
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.25, linewidth=0.7)
    ax.spines[["top", "right"]].set_visible(False)


def save(fig: plt.Figure, stem: str, source: pd.DataFrame, note: str) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    source.to_csv(DATA / f"{stem}.csv", index=False, lineterminator="\n")
    (DATA / f"{stem}.txt").write_text(note.rstrip() + "\n", encoding="utf-8", newline="\n")
    for suffix in ("svg", "pdf"):
        fig.savefig(FIG / f"{stem}.{suffix}", bbox_inches="tight", facecolor="white")
    fig.savefig(FIG / f"{stem}.png", dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5, "axes.unicode_minus": False})

    # 1: information value relative to contract.
    iv = pd.read_csv(ROOT / "research_outputs_closure/01_MECHANISM/INFORMATION_VALUE_SUMMARY.csv")
    metric_order = ["frequency_peak_hz", "ace_iae_pu_s", "tie_rms_pu"]
    iv = iv.set_index("metric").loc[metric_order].reset_index()
    x = np.arange(3)
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    width = 0.24
    series = [
        ("Perfect capability", "perfect_information_improvement_relative_to_contract", COLORS["oracle"]),
        ("Causal online", "causal_online_improvement_relative_to_contract", COLORS["online"]),
        ("Model adaptive", "model_adaptive_improvement_relative_to_contract", COLORS["neutral"]),
    ]
    for i, (label, col, color) in enumerate(series):
        ax.bar(x + (i - 1) * width, 100 * iv[col], width, label=label, color=color)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x, ["Peak frequency", "ACE IAE", "Tie RMS"])
    style(ax, "Information value relative to contract-only MPC", "Improvement (%)")
    ax.legend(frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.27))
    save(fig, "fig01_information_value", iv, "Positive is lower cost than contract-only MPC; 24 balanced scenarios.")

    # 2: perfect-minus-online value gap.
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    gap = 100 * iv["perfect_minus_online_value_gap_relative_to_contract"]
    ax.bar(["Peak frequency", "ACE IAE", "Tie RMS"], gap, color="#5B9BD5")
    style(ax, "Perfect-information opportunity not realized online", "Perfect minus online gap (% of contract)")
    for i, val in enumerate(gap):
        ax.text(i, val + 1, f"{val:.1f}%", ha="center", fontsize=8)
    save(fig, "fig02_perfect_online_gap", iv, "Gap uses balanced absolute means; larger is a wider information-to-action gap.")

    # 3: estimator excitation and certified envelope.
    est = pd.read_csv(ROOT / "research_outputs_closure/01_MECHANISM/ESTIMATOR_EXCITATION_SUMMARY.csv")
    fig, ax = plt.subplots(figsize=(7.4, 4.1))
    labels = ["Registered excitation\nprotocol", "Natural closed-loop\nproxy"]
    xx = np.arange(2)
    ax.bar(xx - 0.18, 100 * est["excitation_sufficient_fraction"], 0.36, label="Sufficient excitation", color="#5B9BD5")
    ax.bar(xx + 0.18, 100 * est["performance_above_contract_fraction"], 0.36, label="Envelope above contract", color=COLORS["online"])
    ax.set_xticks(xx, labels)
    ax.set_ylim(0, 100)
    style(ax, "Excitation did not yield a useful certified envelope", "Episodes (%)")
    ax.legend(frameon=False)
    save(fig, "fig03_estimator_excitation", est, "R2 has 40 episodes; natural proxy has 156 episodes. Performance-above-contract is a distinct test.")

    # 4: surplus usage.
    surplus = pd.read_csv(ROOT / "research_outputs_closure/01_MECHANISM/SURPLUS_USAGE.csv")
    all_surplus = surplus.loc[surplus["scope"] == "ALL"].copy()
    calls = int(all_surplus.iloc[0]["calls"])
    active = int(all_surplus.iloc[0]["active_calls"])
    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    ax.barh(["Inactive", "Active"], [calls - active, active], color=["#D9E2F3", COLORS["online"]])
    ax.set_xscale("symlog", linthresh=1)
    style(ax, "Certified surplus was almost never activated", "DCSV control calls (symlog)")
    ax.text(active + 0.3, 1, f"{active} calls / 6 s", va="center")
    save(fig, "fig04_surplus_activation", all_surplus, "Active surplus was 2 of 22,392 calls (0.0089%); logarithmic-like horizontal scale.")

    # 5: fallback cause and solver accounting.
    val_summary = json.loads((ROOT / "results_final/R5/R5_SUMMARY.json").read_text(encoding="utf-8"))
    con_summary = json.loads((ROOT / "results_closure/C2/C2_SUMMARY.json").read_text(encoding="utf-8"))
    fb = pd.DataFrame([
        {"stage": "Validation", "mathematical_infeasibility_fallback": val_summary["fallback_calls"], "numerical_failure": val_summary["numerical_failures"]},
        {"stage": "Confirmation", "mathematical_infeasibility_fallback": con_summary["fallback_calls"], "numerical_failure": con_summary["numerical_failures"]},
    ])
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    xx = np.arange(2)
    ax.bar(xx - 0.18, fb["mathematical_infeasibility_fallback"], 0.36, label="Fallback", color=COLORS["dcsv"])
    ax.bar(xx + 0.18, fb["numerical_failure"], 0.36, label="Numerical failure", color=COLORS["neutral"])
    ax.set_xticks(xx, fb["stage"])
    style(ax, "Fallbacks were feasibility failures, not numerical failures", "Calls")
    ax.legend(frameon=False)
    save(fig, "fig05_fallback_root_cause", fb, "Validation cause audit attributes all 1,021 fallbacks to primary/restoration mathematical infeasibility; confirmation had zero numerical failures.")

    # 6: binding proxies.
    binding = pd.read_csv(ROOT / "research_outputs_closure/01_MECHANISM/BINDING_CONSTRAINTS.csv")
    binding = binding.assign(label=binding["constraint"].str.replace("_AREA0", "", regex=False).str.replace("_", " ", regex=False))
    fig, ax = plt.subplots(figsize=(8.0, 4.5))
    order = binding.sort_values("near_binding_fraction")
    ax.barh(order["label"], 100 * order["near_binding_fraction"], color="#8064A2")
    style(ax, "Primal-proximity constraint diagnostics", "Near-binding calls (%)")
    save(fig, "fig06_binding_constraints", binding, "These are primal-proximity diagnostics, not optimizer dual multipliers.")

    # 7: Plant A/B direction.
    plant = pd.read_csv(ROOT / "research_outputs_closure/02_CONFIRMATORY/FINAL_PLANT_DIRECTION.csv")
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    colors = [COLORS["dcsv"] if x < 0 else COLORS["oracle"] for x in plant["paired_frequency_absolute_difference_hz"]]
    ax.bar(["Full nonlinear Plant A", "Native ANDES Plant B"], plant["paired_frequency_absolute_difference_hz"], color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    style(ax, "Positive cross-plant direction did not hold", "Paired frequency absolute difference (Hz)")
    save(fig, "fig07_plant_direction", plant, "Positive means DCSV has lower peak deviation. Plant A is negative; Plant B is slightly positive.")

    # 8: known/OOD success and DCSV fallback burden.
    koo = pd.read_csv(ROOT / "research_outputs_closure/02_CONFIRMATORY/FINAL_KNOWN_OOD.csv")
    pa = koo.loc[koo["plant"] == "A_full_nonlinear"].copy()
    pivot = pa.pivot(index="condition", columns="method", values="success_rate").loc[["known", "OOD"]]
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    xx = np.arange(2)
    ax.bar(xx - 0.18, 100 * pivot["contract_only_rolling_mpc"], 0.36, label="Contract-only", color=COLORS["contract"])
    ax.bar(xx + 0.18, 100 * pivot["dcsv_cr_mpc"], 0.36, label="DCSV-CR", color=COLORS["dcsv"])
    ax.set_xticks(xx, ["Known", "OOD"])
    ax.set_ylim(0, 105)
    style(ax, "Plant-A success by capability condition", "Success rate (%)")
    ax.legend(frameon=False)
    save(fig, "fig08_known_ood_success", pa, "Physically infeasible scenarios are excluded from ordinary success scoring.")

    # 9: genuine normal 1h simulation quality.
    normal = pd.read_csv(ROOT / "research_outputs_closure/02_CONFIRMATORY/FINAL_NORMAL1H.csv").sort_values("frequency_peak_hz")
    fig, ax = plt.subplots(figsize=(8.2, 4.7))
    labels = normal["method"].str.replace("_", " ", regex=False)
    bars = ax.barh(labels, normal["frequency_peak_hz"], color=[COLORS["dcsv"] if m == "dcsv_cr_mpc" else "#8FAADC" for m in normal["method"]])
    ax.axvline(1.0, color="black", linestyle="--", linewidth=0.9, label="1 Hz reference")
    style(ax, "All methods failed the registered normal-profile quality Gate", "Worst peak frequency deviation (Hz)")
    ax.legend(frameon=False)
    save(fig, "fig09_normal1h_quality", normal, "Six full 3600 s synthetic registered profiles per method; all quality_gate values are false.")

    # 10: contract violation detection calls.
    cv = pd.read_csv(ROOT / "research_outputs_closure/02_CONFIRMATORY/FINAL_CONTRACT_VIOLATION.csv")
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    ax.bar(cv["scenario_id"], cv["contract_violation_detection_calls"], color="#A5A5A5")
    style(ax, "Contract violations were detected in all six dedicated episodes", "Detection calls per episode")
    save(fig, "fig10_contract_violation_detection", cv, "All six episodes had terminal recovery, zero fallback, and zero hard violation.")

    # 11: validation vs confirmation primary metrics.
    vm = pd.read_csv(ROOT / "results_final/R5/CORE_METRIC_GATES.csv").query("analysis == 'both_success'")
    cm = pd.read_csv(ROOT / "research_outputs_closure/02_CONFIRMATORY/FINAL_CORE_METRIC_GATES.csv").query("analysis == 'both_success'")
    comp = pd.concat([vm.assign(stage="Validation"), cm.assign(stage="Confirmation")], ignore_index=True)
    comp["metric_label"] = comp["metric"].map({"frequency_peak_hz": "Peak frequency", "ace_iae_pu_s": "ACE IAE", "tie_rms_pu": "Tie RMS"})
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    xx = np.arange(3)
    vvals = 100 * comp.loc[comp.stage == "Validation", "aggregate_mean_relative_improvement"].to_numpy()
    cvals = 100 * comp.loc[comp.stage == "Confirmation", "aggregate_mean_relative_improvement"].to_numpy()
    ax.bar(xx - 0.18, vvals, 0.36, label="Validation", color="#9DC3E6")
    ax.bar(xx + 0.18, cvals, 0.36, label="Confirmation", color="#2F5597")
    ax.axhline(8, color=COLORS["oracle"], linestyle="--", linewidth=0.9, label="Registered 8% target")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(xx, ["Peak frequency", "ACE IAE", "Tie RMS"])
    style(ax, "No core performance Gate passed in either stage", "Aggregate improvement (%)")
    ax.legend(frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.26))
    save(fig, "fig11_validation_confirmation", comp, "Scenario-balanced aggregate improvement; lower confidence bounds also failed all three Gates.")

    # 12: physical domain outcomes.
    domain = pd.read_csv(ROOT / "research_outputs_closure/02_CONFIRMATORY/FINAL_DOMAIN_STATISTICS.csv")
    eval_domain = domain.loc[domain["registered_domain"] != "PHYSICALLY_INFEASIBLE"].copy()
    fig, ax = plt.subplots(figsize=(7.2, 4.1))
    pivot = eval_domain.pivot(index="registered_domain", columns="method", values="successes").loc[["SUSTAINABLE", "BRIDGE"]]
    xx = np.arange(2)
    ax.bar(xx - 0.18, pivot["contract_only_rolling_mpc"], 0.36, label="Contract-only", color=COLORS["contract"])
    ax.bar(xx + 0.18, pivot["dcsv_cr_mpc"], 0.36, label="DCSV-CR", color=COLORS["dcsv"])
    ax.set_xticks(xx, ["Sustainable (84)", "Bridge (23)"])
    style(ax, "Success accounting respects physical domains", "Successful episodes")
    ax.legend(frameon=False)
    save(fig, "fig12_domain_outcomes", domain, "37 physically infeasible pairs were certified and reported separately, not scored as controller failures.")

    # 13: theory/certificate boundaries as an evidence map.
    theory = pd.read_csv(ROOT / "results_final/R4/THEOREM_STATUS.csv")
    status_y = {"PROVED": 5, "CONDITIONAL_FINITE_HORIZON": 4, "CONDITIONAL_ONE_CYCLE": 3, "CONDITIONAL_LOCAL": 2, "FINITE_HORIZON_ONLY": 1, "REGISTERED_PHYSICAL_PRECHECK": 0}
    fig, ax = plt.subplots(figsize=(8.2, 4.5))
    y = [status_y[s] for s in theory["status"]]
    ax.scatter(range(len(theory)), y, s=90, color=[COLORS["dcsv"] if s == "FINITE_HORIZON_ONLY" else "#5B9BD5" for s in theory["status"]])
    ax.set_xticks(range(len(theory)), theory["subject"].str.replace("_", " ", regex=False), rotation=25, ha="right")
    ax.set_yticks(list(status_y.values()), [x.replace("_", " ").title() for x in status_y])
    style(ax, "Theory and certificate boundaries", "Status")
    save(fig, "fig13_theory_boundaries", theory, "Only the same-instant impossibility theorem is unconditionally proved; controller certificates are conditional or finite-horizon.")

    index_rows = []
    for png in sorted(FIG.glob("*.png")):
        stem = png.stem
        index_rows.append({"figure": stem, "png": png.name, "svg": f"{stem}.svg", "pdf": f"{stem}.pdf", "source_csv": f"{stem}.csv"})
    pd.DataFrame(index_rows).to_csv(ROOT / "research_outputs_closure/04_FIGURES/FIGURE_INDEX.csv", index=False, lineterminator="\n")
    progress = {
        "schema": "direction5.closure.progress.v1",
        "stage": "C4",
        "status": "PASS",
        "figures": len(index_rows),
        "formats_per_figure": ["PNG_600_DPI", "SVG", "PDF"],
        "source_data_per_figure": True,
        "post_result_tuning": False,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "next_stage": "C5",
    }
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(progress, indent=2))


if __name__ == "__main__":
    main()
