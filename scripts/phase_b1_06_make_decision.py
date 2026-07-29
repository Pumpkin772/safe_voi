"""Aggregate final evidence, render twelve figures, and issue the Phase-B1 decision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from d5freq.evaluation.phase_b1_analysis import (
    collect_final_evidence,
    write_evidence_tables,
)
from d5freq.evaluation.phase_b1_experiments import (
    build_final_control_plan,
    build_final_core_plan,
)
from d5freq.evaluation.phase_b1_protocol import PhaseB1Paths, protocol_lock_sha256
from d5freq.utils.hashing import sha256_file


FIGURE_FILES = (
    "01_core_methods_across_sg.png",
    "02_exact_vs_arx_prediction_errors.png",
    "03_b4_b5_oracle_gap.png",
    "04_gramian_information_over_time.png",
    "05_pairwise_likelihood_separation.png",
    "06_load_vs_mode_confusion.png",
    "07_detection_vs_critical_window.png",
    "08_worst_cost_conservatism.png",
    "09_binary_vs_gradual_authority.png",
    "10_bottleneck_decision_summary.png",
    "11_solver_timing.png",
    "12_worst_retained_failures.png",
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", type=Path, default=Path.cwd())
    return result


def _save(figure: plt.Figure, path: Path) -> None:
    figure.tight_layout()
    figure.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(figure)


def _bar_core(episodes: pd.DataFrame, path: Path) -> None:
    selected = episodes.loc[episodes["method"].isin(("B0", "B4", "B5"))].copy()
    selected["freq_iae"] = pd.to_numeric(selected["freq_iae"], errors="coerce")
    pivot = selected.groupby(["sg_level", "method"])["freq_iae"].mean().unstack()
    figure, axis = plt.subplots(figsize=(7.2, 4.2))
    pivot.reindex(index=["A", "B", "C"], columns=["B0", "B4", "B5"]).plot.bar(ax=axis)
    axis.set_ylabel("Mean frequency IAE (Hz s)")
    axis.set_title("B0 / B4 / B5 across preregistered SG capabilities")
    axis.grid(axis="y", alpha=0.25)
    _save(figure, path)


def _prediction(audit: pd.DataFrame, path: Path) -> None:
    frame = audit.loc[audit["constraint_regime"] == "all"].copy()
    frame["rmse"] = pd.to_numeric(frame["rmse"], errors="coerce")
    grouped = frame.groupby(["horizon_steps", "metric"])["rmse"].mean().unstack()
    figure, axis = plt.subplots(figsize=(7.2, 4.2))
    for metric in grouped.columns:
        axis.plot(grouped.index, grouped[metric], marker="o", label=metric)
    axis.set_xlabel("Prediction horizon (control steps)")
    axis.set_ylabel("Mean rolling-origin RMSE")
    axis.set_yscale("log")
    axis.set_title("Simulator-exact plant versus supervised ARX")
    axis.legend()
    axis.grid(alpha=0.25)
    _save(figure, path)


def _oracle_gap(gap: pd.DataFrame, path: Path) -> None:
    frame = gap.loc[
        (gap["scope"] == "overall")
        & gap["sg_level"].isin(("A", "B", "C"))
        & (gap["metric"] == "freq_iae")
    ]
    figure, axis = plt.subplots(figsize=(6.5, 4.0))
    axis.bar(frame["sg_level"], 100.0 * frame["mean_relative_difference"].astype(float))
    axis.axhline(10.0, color="tab:red", linestyle="--", label="10% preregistered threshold")
    axis.set_ylabel("B4 worse than B5 (%)")
    axis.set_title("Truth-routed ARX versus exact nonlinear Oracle")
    axis.legend()
    axis.grid(axis="y", alpha=0.25)
    _save(figure, path)


def _gramian(frame: pd.DataFrame, path: Path) -> None:
    grouped = frame.groupby(["time_bin_start_s", "window_s"])[
        "min_eigenvalue_median"
    ].median().unstack()
    figure, axis = plt.subplots(figsize=(7.6, 4.2))
    for window in grouped.columns:
        axis.plot(grouped.index, grouped[window], label=f"{window:g} s window")
    axis.set_yscale("symlog", linthresh=1.0e-12)
    axis.set_xlabel("Episode time (s)")
    axis.set_ylabel("Median minimum Gramian eigenvalue")
    axis.set_title("Passive closed-loop information over time")
    axis.legend(ncol=2)
    axis.grid(alpha=0.25)
    _save(figure, path)


def _likelihood(frame: pd.DataFrame, path: Path) -> None:
    grouped = frame.groupby("window_s")[[
        "predictive_log_likelihood_margin",
        "mean_pairwise_jsd",
    ]].median()
    figure, left = plt.subplots(figsize=(7.2, 4.2))
    right = left.twinx()
    left.plot(grouped.index, grouped["predictive_log_likelihood_margin"], marker="o")
    right.plot(grouped.index, grouped["mean_pairwise_jsd"], marker="s", color="tab:orange")
    left.axhline(2.0, linestyle="--", color="tab:red")
    left.set_xlabel("Post-switch window (s)")
    left.set_ylabel("Median log-likelihood margin")
    right.set_ylabel("Median Jensen-Shannon divergence")
    left.set_title("Correct-candidate pairwise separation")
    left.grid(alpha=0.25)
    _save(figure, path)


def _confusion(frame: pd.DataFrame, path: Path) -> None:
    grouped = frame.groupby(["classifier", "true_source"])[[
        "false_mode_alarm_under_load",
        "missed_mode_change",
    ]].mean()
    grouped.columns = ["false alarm", "missed change"]
    figure, axis = plt.subplots(figsize=(8.4, 4.5))
    grouped.plot.bar(ax=axis)
    axis.set_ylabel("Fraction")
    axis.set_ylim(0.0, 1.0)
    axis.set_title("Load disturbance versus device-mode source confusion")
    axis.grid(axis="y", alpha=0.25)
    _save(figure, path)


def _detection(frame: pd.DataFrame, path: Path) -> None:
    figure, axis = plt.subplots(figsize=(7.4, 4.2))
    labels: list[str] = []
    values: list[np.ndarray] = []
    for classifier, subset in frame.groupby("classifier"):
        finite = pd.to_numeric(subset["detection_delay_s"], errors="coerce").dropna().to_numpy()
        if finite.size:
            labels.append(str(classifier).replace("_", "\n"))
            values.append(finite)
    axis.boxplot(values, tick_labels=labels, showfliers=False)
    axis.axhspan(0.0, 5.0, color="tab:green", alpha=0.12, label="0–5 s critical window")
    axis.axhline(10.0, color="tab:red", linestyle="--", label="10 s outer window")
    axis.set_ylabel("Detection delay (s), uncensored only")
    axis.set_title("Detection lower bound versus frequency-critical time")
    axis.legend()
    axis.grid(axis="y", alpha=0.25)
    _save(figure, path)


def _factor(control: pd.DataFrame, factor: str, title: str, path: Path) -> None:
    frame = control.loc[
        (control["factor"] == factor)
        & (control["scope"] == "overall")
        & control["sg_level"].isin(("A", "B", "C"))
        & (control["metric"] == "freq_iae")
    ]
    figure, axis = plt.subplots(figsize=(6.8, 4.0))
    axis.bar(frame["sg_level"], 100.0 * frame["mean_relative_difference"].astype(float))
    axis.axhline(0.0, color="black", linewidth=0.8)
    axis.set_ylabel("Counterfactual minus reference IAE (%)")
    axis.set_title(title)
    axis.grid(axis="y", alpha=0.25)
    _save(figure, path)


def _decision(decision: dict[str, Any], path: Path) -> None:
    scores = decision["normalized_evidence_scores"]
    labels = ["Model mismatch", "Identifiability", "Control design"]
    values = [
        scores["MODEL_MISMATCH_DOMINANT"],
        scores["IDENTIFIABILITY_DOMINANT"],
        scores["CONTROL_DESIGN_DOMINANT"],
    ]
    figure, axis = plt.subplots(figsize=(7.4, 4.1))
    axis.bar(labels, values, color=("tab:blue", "tab:orange", "tab:green"))
    axis.axhline(1.0, color="tab:red", linestyle="--", label="preregistered trigger")
    axis.set_ylabel("Normalized evidence / threshold")
    axis.set_title(decision["decision"])
    axis.legend()
    axis.grid(axis="y", alpha=0.25)
    _save(figure, path)


def _solver(solver: pd.DataFrame, path: Path) -> None:
    grouped = solver.groupby("method")["solve_time_p95_s"].median().sort_values()
    figure, axis = plt.subplots(figsize=(8.6, 4.5))
    axis.bar(grouped.index, grouped.values)
    axis.set_yscale("log")
    axis.tick_params(axis="x", rotation=45)
    axis.set_ylabel("Median episode p95 solve time (s, log scale)")
    axis.set_title("Solver timing by method")
    axis.grid(axis="y", alpha=0.25)
    _save(figure, path)


def _failures(episodes: pd.DataFrame, path: Path) -> None:
    frame = episodes.copy()
    frame["freq_iae"] = pd.to_numeric(frame["freq_iae"], errors="coerce")
    frame["label"] = frame["method"] + " | " + frame["scenario_id"] + " | " + frame["sg_level"]
    failed = frame.loc[~frame["scientific_success"].fillna(False).astype(bool)]
    selected = (
        failed.sort_values("freq_iae", ascending=False).head(12)
        if not failed.empty
        else frame.sort_values("freq_iae", ascending=False).head(12)
    )
    values = selected["freq_iae"].fillna(0.0).to_numpy()
    figure, axis = plt.subplots(figsize=(9.0, 5.0))
    axis.barh(np.arange(len(selected)), values)
    axis.set_yticks(np.arange(len(selected)), selected["label"])
    axis.invert_yaxis()
    axis.set_xlabel("Frequency IAE (missing retained failures shown at zero)")
    axis.set_title("Worst retained failures / negative outcomes")
    axis.grid(axis="x", alpha=0.25)
    _save(figure, path)


def make_figures(
    paths: PhaseB1Paths,
    tables: dict[str, pd.DataFrame],
    decision: dict[str, Any],
) -> pd.DataFrame:
    destination = paths.figures_root
    destination.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False})
    calls = (
        (_bar_core, (tables["per_episode_metrics"],), FIGURE_FILES[0], "core methods across SG levels"),
        (_prediction, (tables["closed_loop_prediction_error"],), FIGURE_FILES[1], "exact-vs-ARX errors"),
        (_oracle_gap, (tables["oracle_gap"],), FIGURE_FILES[2], "B4-B5 gap"),
        (_gramian, (tables["information_gramian"],), FIGURE_FILES[3], "Gramian over time"),
        (_likelihood, (tables["pairwise_separation"],), FIGURE_FILES[4], "pairwise separation"),
        (_confusion, (tables["source_confusion"],), FIGURE_FILES[5], "load-mode confusion"),
        (_detection, (tables["identifiability_delay"],), FIGURE_FILES[6], "detection critical window"),
        (_factor, (tables["control_design_decomposition"], "worst_mode_cost_penalty", "Worst-mode cost conservatism"), FIGURE_FILES[7], "worst-cost conservatism"),
        (_factor, (tables["control_design_decomposition"], "replace_binary_fallback", "Binary fallback versus gradual IBR authority"), FIGURE_FILES[8], "binary fallback versus gradual"),
        (_decision, (decision,), FIGURE_FILES[9], "decision summary"),
        (_solver, (tables["solver_metrics"],), FIGURE_FILES[10], "solver timing"),
        (_failures, (tables["per_episode_metrics"],), FIGURE_FILES[11], "retained failures"),
    )
    rows: list[dict[str, Any]] = []
    for function, arguments, filename, category in calls:
        path = destination / filename
        function(*arguments, path)
        rows.append(
            {
                "category": category,
                "file": filename,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = pd.DataFrame.from_records(rows)
    manifest.to_csv(destination / "figure_manifest.csv", index=False, lineterminator="\n")
    return manifest


def _format_percent(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "NA"
    return "NA" if not np.isfinite(number) else f"{100.0 * number:.2f}%"


def write_reports(
    paths: PhaseB1Paths,
    tables: dict[str, pd.DataFrame],
    decision: dict[str, Any],
) -> None:
    destination = paths.progress_root / "review_reports"
    destination.mkdir(parents=True, exist_ok=True)
    episodes = tables["per_episode_metrics"]
    material = tables["problem_materiality"]
    levels = material.loc[
        (material["scope"] == "overall") & material["sg_level"].isin(("A", "B", "C"))
    ]
    level_lines = "\n".join(
        f"- Level {row.sg_level}: B5 IAE improvement {_format_percent(row.frequency_iae_improvement_fraction)}, "
        f"max-frequency change {_format_percent(row.max_frequency_worsening_fraction)}, "
        f"SG-mileage improvement {_format_percent(row.sg_mileage_improvement_fraction)}, "
        f"gate={'PASS' if row.materiality_gate_passed else 'FAIL'}"
        for row in levels.itertuples()
    )
    failures = episodes.loc[~episodes["scientific_success"].fillna(False).astype(bool)]
    audit_failure_path = paths.results_root / "tables" / "compact_audit_failures.csv"
    audit_failures = (
        0 if not audit_failure_path.is_file() else len(pd.read_csv(audit_failure_path))
    )
    model_gap = _format_percent(decision["model_gap_b4_vs_b5_fraction"])
    ident = _format_percent(decision["bayes_delayed_or_censored_switch_fraction"])
    control = _format_percent(decision["best_isolated_control_gain_fraction"])
    common = (
        f"Final decision: `{decision['decision']}`.\n\n"
        f"Canonical/retained planned episodes: {len(episodes)}; scientific or pre-publication failures: "
        f"{len(failures)}; compact audit-computation failures: {audit_failures}.\n\n"
        f"B4-vs-B5 mean IAE gap: {model_gap}; correct-candidate Bayes delayed/censored "
        f"switch fraction: {ident}; best isolated control-factor gain: {control}.\n"
    )
    reports = {
        "00_EXECUTIVE_SUMMARY.md": "# Executive Summary\n\n" + common + "\n" + level_lines + "\n\nThe audit stops here; no next method is implemented.\n",
        "01_BASELINE_AND_INTEGRITY.md": "# Baseline and Integrity\n\nBaseline commit: `f8038467bc7a99b519f6bec692a9ad9c06f8cd19`. Frozen Phase-6 parent: `20f652f5f8b180a2518798d0ed85aa3f48212908`. Tag: `phase-a-final-reviewed-v2`. Review ZIP SHA256: `2e1c3bfc380c57172a5d96663a6ab90cf95b79511f60cefce73ce4c38e2f04a9`.\n\nThe immutable baseline manifest and 609-test JUnit/text logs are included. Phase-B1 commit is recorded in the package Git metadata. Protocol lock SHA256: `" + protocol_lock_sha256(paths) + "`. Old `artifacts/` and `results/` were not overwritten.\n",
        "02_PROBLEM_MATERIALITY.md": "# Problem Materiality\n\n" + level_lines + "\n\nThe preregistered gate is evaluated per physically feasible SG level from paired final episodes, with all failures retained in adjacent counts.\n",
        "03_MODEL_ADEQUACY.md": "# Model Adequacy\n\n" + common + "\nExact-vs-ARX rolling-origin errors are reported at 1/5/10/20 steps by true mode, alongside deadband, delay, saturation, and rate-limit activation. B4 is truth-routed *identified ARX*, not the exact Oracle.\n",
        "04_IDENTIFIABILITY.md": "# Passive Identifiability\n\n" + common + "\nThe tables separate the current native diagnostic from an evaluation-only Bayes upper bound using the correct labeled candidate set. Gramian evidence is binned over time at 5 s resolution; censored switches remain explicit.\n",
        "05_CONTROL_DESIGN_DECOMPOSITION.md": "# Control Design Decomposition\n\n" + common + "\nC0–C5 share frozen MPC weights, horizon, solver priority, SG/IBR bounds, and final seeds. Each adjacent/paired comparison changes only the registered factor: worst-mode cost, tightening, binary fallback, or sticky prior.\n",
        "06_BOTTLENECK_DECISION.md": "# Bottleneck Decision\n\n" + common + "\nEvidence scores are divided by thresholds frozen before final execution. A COMBINED result lists primary then secondary. The machine-readable decision and all paired tests are included under `results/tables/`.\n",
        "07_LIMITATIONS_AND_FAILURES.md": "# Limitations and Failures\n\n" + common + "\nB5 is a simulator-exact nonlinear *plant* benchmark with finite-horizon, finite candidate-grid shooting; it is not a proof of the globally optimal nonlinear policy. It observes current true mode/IBR parameters only and never future load or mode. Solver failures are not replaced by B0. No failed, timed-out, infeasible, censored, or pre-publication attempt is deleted. Representative trajectories were preregistered; all high-frequency raw traces are excluded from the package.\n",
        "08_REPRODUCIBILITY_COMMANDS.md": "# Reproducibility Commands\n\nRun from the repository root with `MOSEKLM_LICENSE_FILE=D:\\Backup\\Downloads\\mosek.lic` and `GRB_LICENSE_FILE=D:\\Backup\\Downloads\\gurobi.lic`.\n\n```powershell\nD:\\Miniconda3\\condabin\\conda.bat run -n topo_sfr python scripts/phase_b1_01_validate_oracle.py\nD:\\Miniconda3\\condabin\\conda.bat run -n topo_sfr python scripts/phase_b1_02_run_materiality_audit.py\nD:\\Miniconda3\\condabin\\conda.bat run -n topo_sfr python scripts/phase_b1_03_run_model_audit.py\nD:\\Miniconda3\\condabin\\conda.bat run -n topo_sfr python scripts/phase_b1_04_run_identifiability_audit.py\nD:\\Miniconda3\\condabin\\conda.bat run -n topo_sfr python scripts/phase_b1_05_run_control_design_audit.py\nD:\\Miniconda3\\condabin\\conda.bat run -n topo_sfr python scripts/phase_b1_06_make_decision.py\nD:\\Miniconda3\\condabin\\conda.bat run -n topo_sfr python -m pytest\nD:\\Miniconda3\\condabin\\conda.bat run -n topo_sfr python -m pytest tests_phase_b1\n```\n",
    }
    for filename, content in reports.items():
        (destination / filename).write_text(content, encoding="utf-8", newline="\n")
    (paths.progress_root / "BOTTLENECK_DECISION.md").write_text(
        reports["06_BOTTLENECK_DECISION.md"], encoding="utf-8", newline="\n"
    )


def main() -> int:
    arguments = parser().parse_args()
    paths = PhaseB1Paths.from_repo(arguments.repo_root)
    episodes, audits, solver, audit_failures = collect_final_evidence(
        paths, (build_final_core_plan(paths), build_final_control_plan(paths))
    )
    tables, decision = write_evidence_tables(
        paths, episodes=episodes, audits=audits, solver=solver
    )
    audit_failures.to_csv(
        paths.results_root / "tables" / "compact_audit_failures.csv",
        index=False,
        lineterminator="\n",
    )
    make_figures(paths, tables, decision)
    write_reports(paths, tables, decision)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
