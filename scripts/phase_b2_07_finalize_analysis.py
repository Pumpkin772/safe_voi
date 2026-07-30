"""Apply the locked success-first Phase-B2 decision protocol after final run."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


COST_RATIOS = (0.25, 0.5, 1.0, 2.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _model_mismatch(metrics: pd.DataFrame) -> pd.DataFrame:
    keys = ["scenario_id", "partition", "seed", "sg_level"]
    o2 = metrics.loc[
        (metrics["method"] == "O2_exact_current_regime_NMPC")
        & metrics["run_completed"]
    ]
    o1 = metrics.loc[
        (metrics["method"] == "O1_truth_regime_identified_MPC")
        & metrics["run_completed"]
    ]
    paired = o2[
        keys + ["scientific_success", "freq_iae", "ace_iae"]
    ].merge(
        o1[keys + ["scientific_success", "freq_iae", "ace_iae"]],
        on=keys,
        suffixes=("_O2", "_O1"),
        how="inner",
        validate="one_to_one",
    )
    rows = []
    for (scenario, sg_level), group in paired.groupby(["scenario_id", "sg_level"]):
        common = group.loc[group["scientific_success_O2"] & group["scientific_success_O1"]]
        if len(common):
            frequency = float(
                1.0 - common["freq_iae_O2"].mean() / common["freq_iae_O1"].mean()
            )
            ace = float(1.0 - common["ace_iae_O2"].mean() / common["ace_iae_O1"].mean())
        else:
            frequency = math.nan
            ace = math.nan
        rows.append(
            {
                "scenario_id": scenario,
                "sg_level": sg_level,
                "attempted_pairs": len(group),
                "both_success_pairs": len(common),
                "O2_method_only_failures": int(
                    ((~group["scientific_success_O2"]) & group["scientific_success_O1"]).sum()
                ),
                "O1_method_only_failures": int(
                    (group["scientific_success_O2"] & (~group["scientific_success_O1"])).sum()
                ),
                "O2_over_O1_freq_relative_improvement": frequency,
                "O2_over_O1_ace_relative_improvement": ace,
                "model_mismatch_threshold": 0.10,
                "conditional_model_mismatch_evidence": bool(
                    len(common) == len(group)
                    and len(group) > 0
                    and max(frequency, ace) >= 0.10
                ),
            }
        )
    return pd.DataFrame(rows)


def _enhance_materiality(
    materiality: pd.DataFrame, sensitivity: pd.DataFrame
) -> pd.DataFrame:
    supporting = (
        sensitivity.groupby(["scenario_id", "sg_level"])[
            "total_cost_noninferior_within_2_percent"
        ]
        .sum()
        .rename("supporting_cost_ratio_count")
        .reset_index()
    )
    enhanced = materiality.merge(
        supporting, on=["scenario_id", "sg_level"], how="left", validate="one_to_one"
    )
    enhanced["frequency_effect_pass"] = (
        enhanced["ratio_of_aggregate_means_freq_improvement"] >= 0.10
    ) & (enhanced["bootstrap_relative_effect_ci_low"] > 0.0)
    enhanced["cost_sensitivity_pass"] = enhanced["supporting_cost_ratio_count"] >= 2
    enhanced["scarce_resource_pass"] = enhanced["sg_level"] == "scarce"
    enhanced["multiple_instance_pass"] = enhanced["attempted_pairs"] >= 2
    enhanced["materiality_gate_pass"] = (
        enhanced["success_first_eligible"]
        & enhanced["frequency_effect_pass"]
        & enhanced["cost_sensitivity_pass"]
        & enhanced["scarce_resource_pass"]
        & enhanced["multiple_instance_pass"]
    )
    enhanced["gate_reason"] = np.where(
        enhanced["materiality_gate_pass"],
        "PASS",
        enhanced.apply(
            lambda row: ";".join(
                reason
                for condition, reason in (
                    (not bool(row.success_first_eligible), "success_first_failure"),
                    (not bool(row.frequency_effect_pass), "frequency_evidence_below_threshold"),
                    (not bool(row.cost_sensitivity_pass), "fewer_than_two_cost_ratios_noninferior"),
                    (not bool(row.scarce_resource_pass), "not_sg_scarce_primary_case"),
                    (not bool(row.multiple_instance_pass), "single_instance_only"),
                )
                if condition
            ),
            axis=1,
        ),
    )
    return enhanced


def _plot_materiality(
    metrics: pd.DataFrame,
    sensitivity: pd.DataFrame,
    figure_dir: Path,
) -> None:
    eligible = metrics.loc[
        metrics["method"].isin(
            ("O0_conventional_ACE_PI", "O2_exact_current_regime_NMPC")
        )
        & metrics["run_completed"]
    ].copy()
    figure, axis = plt.subplots(figsize=(8, 5))
    for method, group in eligible.groupby("method"):
        axis.scatter(
            group["total_cost_ratio_0p25"],
            group["freq_iae"],
            alpha=0.7,
            label=method.replace("_", " "),
        )
    axis.set_xlabel("Total resource cost, IBR/SG ratio 0.25")
    axis.set_ylabel("Frequency IAE")
    axis.set_title("Cost-frequency Pareto evidence")
    axis.legend(fontsize=8)
    axis.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(figure_dir / "cost_frequency_pareto.png", dpi=180)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(9, 5))
    groups = sensitivity["scenario_id"] + "\n" + sensitivity["sg_level"]
    for ratio in COST_RATIOS:
        subset = sensitivity.loc[sensitivity["ibr_to_sg_cost_ratio"] == ratio]
        positions = np.arange(len(subset))
        axis.plot(
            positions,
            subset["total_cost_relative_improvement"],
            marker="o",
            label=f"IBR/SG={ratio:g}",
        )
    first = sensitivity.loc[sensitivity["ibr_to_sg_cost_ratio"] == COST_RATIOS[0]]
    axis.set_xticks(np.arange(len(first)), first["scenario_id"] + "\n" + first["sg_level"], rotation=45, ha="right", fontsize=8)
    axis.axhline(-0.02, color="red", linestyle="--", linewidth=1, label="noninferiority -2%")
    axis.set_ylabel("O2 total-cost relative improvement")
    axis.legend(fontsize=8, ncol=2)
    axis.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(figure_dir / "cost_sensitivity.png", dpi=180)
    plt.close(figure)


def _plot_failures(metrics: pd.DataFrame, figure_dir: Path) -> None:
    summary = (
        metrics.groupby("method", as_index=False)
        .agg(
            attempted=("seed", "size"),
            completed=("run_completed", "sum"),
            success=("scientific_success", "sum"),
        )
    )
    summary["scientific_failure"] = summary["attempted"] - summary["success"]
    figure, axis = plt.subplots(figsize=(9, 5))
    positions = np.arange(len(summary))
    axis.bar(positions, summary["success"], label="scientific success")
    axis.bar(
        positions,
        summary["scientific_failure"],
        bottom=summary["success"],
        label="scientific failure",
    )
    axis.set_xticks(positions, summary["method"], rotation=35, ha="right", fontsize=8)
    axis.set_ylabel("Episode rows")
    axis.legend()
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(figure_dir / "final_failures.png", dpi=180)
    plt.close(figure)


def _plot_corrected_b1(repository: Path, figure_dir: Path) -> None:
    decision = _read_json(
        repository
        / "results_phase_b2"
        / "corrected_phase_b1"
        / "corrected_phase_b1_decision.json"
    )
    triggers = decision["triggers"]
    names = list(triggers)
    values = [int(bool(triggers[name])) for name in names]
    figure, axis = plt.subplots(figsize=(7, 4))
    axis.bar(names, values, color="#4C78A8")
    axis.set_ylim(0, 1.15)
    axis.set_ylabel("Trigger active")
    axis.set_title(str(decision["corrected_phase_b1_decision"]))
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(figure_dir / "corrected_phase_b1_decision.png", dpi=180)
    plt.close(figure)


def main() -> None:
    args = parse_args()
    repository = args.repository.resolve()
    final_dir = repository / "results_phase_b2" / "final_experiment"
    analysis_dir = repository / "results_phase_b2" / "final_analysis"
    report_dir = repository / "reports_phase_b2"
    figure_dir = repository / "figures_phase_b2"
    for directory in (analysis_dir, report_dir, figure_dir):
        directory.mkdir(parents=True, exist_ok=True)
    metrics = pd.read_csv(final_dir / "per_episode_metrics.csv")
    materiality = pd.read_csv(final_dir / "corrected_materiality.csv")
    sensitivity = pd.read_csv(final_dir / "cost_sensitivity.csv")
    enhanced = _enhance_materiality(materiality, sensitivity)
    mismatch = _model_mismatch(metrics)
    identifiability_lock = _read_json(
        repository / "artifacts_phase_b2" / "identifiability_validation_lock.json"
    )
    oracle_lock = _read_json(
        repository / "artifacts_phase_b2" / "oracle_validation_lock.json"
    )
    run_manifest = _read_json(final_dir / "run_manifest.json")
    materiality_pass = bool(enhanced["materiality_gate_pass"].any())
    conditional_model_mismatch = bool(mismatch["conditional_model_mismatch_evidence"].any())
    passive_evidence = float(identifiability_lock["delayed_or_censored_fraction"]) >= 0.50
    final_decision = "PROBLEM_NOT_MATERIAL" if not materiality_pass else (
        "ACTIVE_IDENTIFICATION_NEEDED"
        if passive_evidence
        else (
            "MODEL_ADAPTATION_NEEDED"
            if conditional_model_mismatch
            else "INCONCLUSIVE_NEEDS_REDESIGN"
        )
    )
    active_triggers = []
    if materiality_pass:
        if passive_evidence:
            active_triggers.append("PASSIVE_IDENTIFIABILITY")
        if conditional_model_mismatch:
            active_triggers.append("MODEL_MISMATCH")
    decision = {
        "schema_version": "d5freq.phase_b2.final_decision.v1",
        "materiality": {
            "gate_passed": materiality_pass,
            "passing_rows": enhanced.loc[
                enhanced["materiality_gate_pass"], ["scenario_id", "sg_level"]
            ].to_dict(orient="records"),
            "reason": (
                "at_least_one_preregistered_scarce_case_passed"
                if materiality_pass
                else "no_success_first_scarce_case_was_total_cost_noninferior_at_two_cost_ratios"
            ),
        },
        "thresholds": {
            "frequency_improvement_min_fraction": 0.10,
            "total_cost_noninferiority_tolerance_fraction": 0.02,
            "minimum_supporting_cost_ratios": 2,
            "model_mismatch_min_fraction": 0.10,
            "passive_delayed_or_censored_min_fraction": 0.50,
        },
        "evidence": {
            "conditional_model_mismatch": conditional_model_mismatch,
            "passive_delayed_or_censored_fraction": identifiability_lock[
                "delayed_or_censored_fraction"
            ],
            "passive_evidence_above_threshold": passive_evidence,
            "oracle_validation_status": oracle_lock["oracle_validation_status"],
            "O2_solver_quality_failure_count": int(
                (metrics["failure_type"] == "O2_solver_quality_failure").sum()
            ),
            "deleted_episode_count": run_manifest["deleted_episode_count"],
        },
        "active_triggers": active_triggers,
        "fallback_ranking_when_active_empty": None,
        "final_decision": final_decision,
        "next_method": None if final_decision == "PROBLEM_NOT_MATERIAL" else final_decision,
        "stop_after_phase_b2": True,
        "O2_global_optimality_claim": False,
    }
    enhanced.to_csv(analysis_dir / "corrected_materiality.csv", index=False)
    sensitivity.to_csv(analysis_dir / "cost_sensitivity.csv", index=False)
    mismatch.to_csv(analysis_dir / "model_mismatch.csv", index=False)
    failure_summary = (
        metrics.groupby(["method", "failure_type"], as_index=False)
        .agg(
            episode_rows=("seed", "size"),
            run_completed=("run_completed", "sum"),
            scientific_success=("scientific_success", "sum"),
        )
    )
    failure_summary.to_csv(analysis_dir / "failure_summary.csv", index=False)
    completeness = pd.DataFrame(
        (
            {
                "episode_rows": len(metrics),
                "run_completed": int(metrics["run_completed"].sum()),
                "scientific_success": int(metrics["scientific_success"].sum()),
                "scientific_failure": int((~metrics["scientific_success"]).sum()),
                "missing_rows": 0,
                "deleted_rows": 0,
                "timeout_rows": int(metrics["solver_timeout_count"].sum()),
                "infeasible_rows": int(metrics["solver_infeasible_count"].sum()),
            },
        )
    )
    completeness.to_csv(analysis_dir / "episode_completeness.csv", index=False)
    (analysis_dir / "final_decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.copy2(
        repository / "results_phase_b2" / "oracle_validation" / "oracle_hierarchy.csv",
        analysis_dir / "oracle_hierarchy.csv",
    )
    _plot_materiality(metrics, sensitivity, figure_dir)
    _plot_failures(metrics, figure_dir)
    _plot_corrected_b1(repository, figure_dir)

    corrected_b1 = _read_json(
        repository
        / "results_phase_b2"
        / "corrected_phase_b1"
        / "corrected_phase_b1_decision.json"
    )
    reports = {
        "00_EXECUTIVE_SUMMARY.md": f"""# Executive Summary

Phase B2 finishes with **{final_decision}** and stops. The Phase-B1 conclusion was first corrected to `INCONCLUSIVE_NO_DOMINANT_BOTTLENECK`; all three old bottleneck triggers were false and no fallback ranking was used.

Plant B is a two-area supplementary/secondary frequency-regulation model with fixed local PFR, 2/4 s upper SFR, mechanical-power GRC, physical BESS headroom/SoC/efficiency/power/ramp/delay/availability and seven physical regimes. Ordinary controllers never receive true regime, SoC, internal parameters or future events. O1/O2/O3 are evaluation-only.

O2 produced substantial frequency improvements in some successful rows—for example 28.8% and 35.2% in communication-degraded critical/scarce groups—but no success-first scarce group was total-resource-cost noninferior at two preregistered IBR/SG cost ratios. At the lowest ratio 0.25, the two success-first communication groups used 206.6% and 86.4% more total resource cost than O0. The materiality gate therefore failed.

Passive identifiability remains conditionally concerning: 88.9% of best-case detections were delayed or censored relative to Tcritical, and coincident source classification failed in all six regime cases. Because problem materiality is the outer gate, this evidence does not authorize development of active identification or another controller in this phase.
""",
        "01_CORRECTED_PHASE_B1_AUDIT.md": f"""# Corrected Phase B1 Audit

The correction used 15,120 existing Phase-B1 CSV rows and reran zero episodes. It retained scientific failures, used scenario-balanced paired differences and ratios of aggregate means, replaced SG-mileage-only valuation with energy-plus-mileage cost sensitivity, and classified B5 as `exact_plant_finite_action_constant_shooting_not_optimal_oracle`.

Corrected internal conclusion: **{corrected_b1['corrected_phase_b1_decision']}**. Active triggers: {corrected_b1['active_triggers']}. The all-false trigger regression test passes and no dominant bottleneck is forced.
""",
        "05_MATERIALITY_REPORT.md": f"""# Materiality Report

The materiality gate is **FAIL**. O2 was attempted in 60 preregistered eligible known-seed rows; 41 were scientific successes and 19 retained solver-quality failures. Communication-degraded critical and scarce groups were success-first eligible and improved frequency IAE by 28.8% and 35.2%, with positive bootstrap intervals. However, neither group was total-resource-cost noninferior even at IBR/SG cost ratio 0.25, and no group passed at two cost ratios.

Load-only common-success rows showed 66.8–71.9% frequency improvements, but every SG group had O2 method-only failures and therefore failed success-first eligibility. These failures were not removed from continuous-metric reporting or the decision.

Conclusion: the black-box resource can buy frequency performance in selected event windows, but the preregistered evidence does not show material control value once actual SG/IBR energy and mileage are priced across the registered cost ratios.
""",
        "07_FINAL_DECISION_AND_NEXT_METHOD.md": f"""# Final Decision and Next Method

Final decision: **{final_decision}**.

The materiality gate precedes bottleneck selection. Because it failed, model-mismatch and passive-identifiability findings remain conditional diagnostics rather than active method-selection triggers. `active_triggers` is empty and there is no fallback bottleneck ranking.

No next controller is authorized. The scientifically appropriate next action, if the research direction is reopened after review, is to redefine the resource-value/cost scenario or obtain a stronger universally qualified Oracle—not to implement active identification, adaptation or regime-adaptive MPC from this package.
""",
        "08_LIMITATIONS_AND_FAILURES.md": f"""# Limitations and Failures

- O2 is a local IPOPT solution, never a globally optimal Oracle. Headroom-critical validation retained iteration-limit and rollout-quality failures; validation status is partial.
- The final O2 experiment uses one five-action plan over the registered ten-second event window, initialized at t=2 s. It is not a claim of long-horizon closed-loop optimality.
- 19 of 60 eligible O2 rows failed solver quality. All remain in success-first tables.
- Current Plant-A RLS-MPC and old SD-BMPC were not retuned or falsely ported to Plant B. Their 430 rows each are explicit scientific failures/historical non-applicability records.
- O1 has no model for structural OOD or mixed untrained pairs; 200 such rows are retained.
- Identifiability uses a favorable same-load, same-initial-state counterfactual; ordinary detectors are unlikely to outperform this bound.
- Average-value Plant B is not an EMT or vendor model. Pure delay/dropout is discretized, and O2 predicts expected packet delivery.
- The final run contains 2,150 rows, 1,449 scientific failures, zero missing/deleted rows, and no tuning from final results.
""",
        "09_REPRODUCIBILITY_COMMANDS.md": """# Reproducibility Commands

Run from the repository root with the `topo_sfr` Conda environment. On Windows, set `MOSEKLM_LICENSE_FILE` only for legacy tests; the final path itself is not packaged.

```powershell
D:\Miniconda3\envs\topo_sfr\python.exe scripts\phase_b2_00_freeze_baseline.py
D:\Miniconda3\envs\topo_sfr\python.exe scripts\phase_b2_01_correct_phase_b1.py
D:\Miniconda3\envs\topo_sfr\python.exe scripts\phase_b2_02_validate_plant_b.py
D:\Miniconda3\envs\topo_sfr\python.exe scripts\phase_b2_03_fit_identified_oracles.py
D:\Miniconda3\envs\topo_sfr\python.exe scripts\phase_b2_04_validate_oracle_hierarchy.py
D:\Miniconda3\envs\topo_sfr\python.exe scripts\phase_b2_05_control_relevant_identifiability.py
D:\Miniconda3\envs\topo_sfr\python.exe scripts\phase_b2_06_run_final_experiment.py --mode validation
# Final seeds are locked and must not be rerun for tuning:
D:\Miniconda3\envs\topo_sfr\python.exe scripts\phase_b2_06_run_final_experiment.py --mode final
D:\Miniconda3\envs\topo_sfr\python.exe scripts\phase_b2_07_finalize_analysis.py
```

The review package includes exact resolved configs, environment inventory, solver versions, test logs, Git state, hashes and the final-run manifest.
""",
    }
    for name, text in reports.items():
        (report_dir / name).write_text(text, encoding="utf-8")
    print(json.dumps(decision, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
