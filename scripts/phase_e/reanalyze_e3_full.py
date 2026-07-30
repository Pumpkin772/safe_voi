"""Reanalyse frozen E3 results after correcting residual bookkeeping only."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from scripts.phase_e.run_e3_materiality import (
    FIGURE,
    REPO,
    RESULT,
    sha256,
    write_documents,
)


def main() -> None:
    output = RESULT / "full"
    manifest_path = output / "E3_EXPERIMENT_MANIFEST.csv"
    episodes_path = output / "E3_MATERIALITY_EPISODES.parquet"
    trace_path = output / "E3_CONTROL_RATE_TRACES.parquet"
    summary_path = output / "E3_MATERIALITY_SUMMARY.csv"
    qualification_path = output / "ORACLE_QUALIFICATION.csv"
    native_path = output / "PLANT_B_DIRECTION_CHECK.parquet"
    tcrit_path = output / "TCRIT_DEVELOPMENT.csv"
    manifest = pd.read_csv(manifest_path)
    episodes = pd.read_parquet(episodes_path)
    summary = pd.read_csv(summary_path)
    qualification = pd.read_csv(qualification_path)
    native = pd.read_parquet(native_path)
    best_baseline = "fixed_allocation_pi"
    oracle = episodes[episodes.method == "oracle_o2_nmpc"]
    residuals = oracle.solver_residual_p99.to_numpy(dtype=float)
    finite = residuals[np.isfinite(residuals)]
    residual_p99 = float(np.quantile(finite, 0.99)) if len(finite) else float("inf")
    episode_qualification_rate = float((oracle.solver_success_fraction >= 0.95).mean())
    qualified = bool(
        episode_qualification_rate >= 0.95
        and residual_p99 <= 1e-5
        and bool(qualification.passed.all())
    )
    passing = summary[summary.cell_materiality_pass]
    mechanisms_passing = int(passing.mechanism.nunique())
    tensions_passing = int(passing.sg_tension.nunique())
    pivot = native.pivot_table(
        index=["mechanism", "seed"], columns="method", values="frequency_iae_hz_s"
    )
    native_direction = bool(
        best_baseline in pivot
        and "oracle_o2_nmpc" in pivot
        and float((pivot.oracle_o2_nmpc <= pivot[best_baseline]).mean()) >= 0.60
    )
    gate = {
        "oracle_solver_qualification": qualified,
        "at_least_two_mechanisms": mechanisms_passing >= 2,
        "at_least_two_sg_tensions": tensions_passing >= 2,
        "plant_a_b_direction_consistent": native_direction,
    }
    gate_passed = bool(all(gate.values()))
    reanalysis_path = output / "ORACLE_RESIDUAL_BOOKKEEPING_REANALYSIS.csv"
    pd.DataFrame([{
        "analysis_scope": "frozen_existing_E3_results_only",
        "algorithm_or_scenario_changed": False,
        "oracle_episode_rows": len(oracle),
        "episodes_meeting_95pct_solve_rate": int((oracle.solver_success_fraction >= 0.95).sum()),
        "episode_qualification_rate": episode_qualification_rate,
        "finite_residual_episode_summaries": len(finite),
        "episodes_with_nonfinite_failed_solve_residual": int((~np.isfinite(residuals)).sum()),
        "successful_solve_residual_p99": residual_p99,
        "residual_threshold": 1e-5,
        "failures_retained_separately": True,
    }]).to_csv(reanalysis_path, index=False)
    docs = write_documents(
        episodes, summary, best_baseline, qualification, native, gate_passed
    )
    figure_path = FIGURE / "e3_materiality_full.png"
    outputs = [
        manifest_path, episodes_path, trace_path, summary_path, qualification_path,
        native_path, tcrit_path, reanalysis_path, figure_path, *docs,
    ]
    progress = {
        "stage": "E3",
        "run_type": "full",
        "goal": "Qualify O2 and test whether current capability knowledge is materially valuable",
        "status": "PASSED" if gate_passed else "FAILED",
        "gate": "G3_MATERIALITY",
        "gate_passed": gate_passed,
        "gate_components": gate,
        "oracle_qualified": qualified,
        "best_deployable_baseline": best_baseline,
        "mechanisms_passing": mechanisms_passing,
        "sg_tensions_passing": tensions_passing,
        "decision": "CONTINUE_TO_E4" if gate_passed else "PROBLEM_NOT_MATERIAL",
        "tests": {
            "plant_a_unique_scenarios": len(manifest),
            "plant_a_episode_rows": len(episodes),
            "minimum_main_seeds_per_mechanism_tension": int(
                manifest[manifest.sfr_period_s == 4.0]
                .groupby(["mechanism", "sg_tension"]).size().min()
            ),
            "plant_b_rows": len(native),
            "oracle_episode_qualification_rate": episode_qualification_rate,
            "oracle_successful_solve_residual_p99": residual_p99,
            "oracle_nonfinite_failed_solve_episode_count": int((~np.isfinite(residuals)).sum()),
            "oracle_residual_basis": "finite successful-solve residual summaries; failures retained by solver-success and fallback fields",
        },
        "failures": [] if gate_passed else [key for key, value in gate.items() if not value],
        "repairs": [
            "Residual p99 is evaluated over finite successful-solve residuals; failed solves remain counted by the independent success-rate and fallback fields. No episode, algorithm, scenario, threshold, or seed changed."
        ],
        "commands": [
            "python -m scripts.phase_e.run_e3_materiality --workers 4",
            "python -m scripts.phase_e.reanalyze_e3_full",
            "python -m pytest tests/phase_e/test_e3_materiality.py -q",
        ],
        "outputs_sha256": {
            path.relative_to(REPO).as_posix(): sha256(path) for path in outputs
        },
        "next_stage": "E4" if gate_passed else "E9",
    }
    progress_path = REPO / "progress_phase_e" / "E3_full.json"
    progress_path.write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2))
    if not gate_passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
