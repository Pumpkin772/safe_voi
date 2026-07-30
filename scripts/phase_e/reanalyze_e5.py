"""Correct E5 timing denominator using only timing-evaluated frozen episodes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
RESULT = REPO / "results_phase_e" / "E5"
DOC = REPO / "research_outputs_phase_e" / "05_IDENTIFICATION"
SUMMARY_DOC = REPO / "research_outputs_phase_e" / "09_SUMMARY"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    episodes_path = RESULT / "E5_ACTIVE_FEASIBILITY.parquet"
    episode = pd.read_parquet(episodes_path)
    native_path = RESULT / "E5_PLANT_B_ACTIVE.parquet"
    native = pd.read_parquet(native_path)
    summary = episode.groupby(["method", "mechanism"]).agg(
        episodes=("scenario_id", "size"), physical_success_rate=("physical_success", "mean"),
        frequency_iae=("frequency_iae_hz_s", "mean"), ace_iae=("ace_iae_pu_s", "mean"),
        timing_evaluated=("timing_evaluated", "sum"),
        mean_information_gain=("information_gain", "mean"),
        mean_probe_energy_mwh=("probe_energy_mwh", "mean"),
        mean_probe_mileage_pu=("probe_mileage_pu", "mean"),
        backup_feasible_rate=("backup_feasible_rate", "mean"),
        suppression_rate=("probe_suppression_rate", "mean"),
    ).reset_index()
    timing = episode.groupby(["method", "mechanism"]).apply(
        lambda frame: float(frame.loc[frame.timing_evaluated, "update_before_Tcrit"].mean())
        if frame.timing_evaluated.any() else float("nan"), include_groups=False,
    ).rename("p_update_before_tcrit").reset_index()
    summary = summary.merge(timing, on=["method", "mechanism"])
    summary_path = RESULT / "E5_INFORMATION_SAFETY_TRADEOFF.csv"
    summary.to_csv(summary_path, index=False)
    optimized = episode[episode.method == "optimized_probe"].set_index("scenario_id")
    baseline = episode[episode.method == "no_probe"].set_index("scenario_id").loc[optimized.index]
    no_failure_increase = float(optimized.physical_success.mean()) >= float(baseline.physical_success.mean())
    frequency_degradation = float(optimized.frequency_iae_hz_s.mean() / baseline.frequency_iae_hz_s.mean() - 1.0)
    ace_degradation = float(optimized.ace_iae_pu_s.mean() / baseline.ace_iae_pu_s.mean() - 1.0)
    evaluated = optimized[optimized.timing_evaluated]
    timing_by_mechanism = evaluated.groupby("mechanism").update_before_Tcrit.mean()
    information_by_mechanism = optimized.groupby("mechanism").information_gain.mean()
    mechanisms_timing = int((timing_by_mechanism >= 0.80).sum())
    mechanisms_information = int((information_by_mechanism >= 0.15).sum())
    budget = bool(optimized.probe_energy_mwh.max() <= 1.50 and optimized.probe_mileage_pu.max() <= 2.50)
    adequate_backup = float(optimized[optimized.sg_tension == "adequate"].backup_feasible_rate.mean()) >= 0.95
    pivot = native.pivot(index="mechanism", columns="method", values="physical_success")
    native_safe = bool(pivot.optimized_probe.mean() >= pivot.no_probe.mean())
    native_information = int(native[native.method == "optimized_probe"].groupby(
        "mechanism"
    ).update_before_reference_window.mean().ge(0.8).sum())
    direction = (mechanisms_timing >= 3) == (native_information >= 3)
    gate = {
        "no_physical_failure_rate_increase": no_failure_increase,
        "frequency_ace_not_materially_degraded": frequency_degradation <= 0.10 and ace_degradation <= 0.10,
        "at_least_three_mechanisms_timing": mechanisms_timing >= 3,
        "at_least_three_mechanisms_information": mechanisms_information >= 3,
        "probe_energy_and_mileage_budget": budget,
        "adequate_sg_backup_feasible": adequate_backup,
        "plant_b_no_failure_increase": native_safe,
        "plant_a_b_direction_consistent": direction,
    }
    passed = bool(all(gate.values()))
    report = DOC / "ACTIVE_IDENTIFICATION_FEASIBILITY.md"
    report.write_text(f"""# E5 safe active-identification feasibility

The optimized candidate uses a 0.04 pu, zero-mean alternating BESS redistribution with same-area SG compensation. Candidate execution is suppressed whenever public frequency/ACE margin or an explicit SG backup check fails. The information monitor uses high-rate issued command, POI power, and frequency only; capability labels enter only paired evaluation.

G5 result: **{'PASS — ACTIVE_IDENTIFICATION_FEASIBLE' if passed else 'FAIL — ACTIVE_IDENTIFICATION_NOT_SAFE'}**. Timing passes {mechanisms_timing}/5 mechanisms after excluding only explicitly `timing_evaluated=false` rows from the denominator; information contraction passes {mechanisms_information}/5. Frequency IAE change is {frequency_degradation:.2%}; ACE IAE change is {ace_degradation:.2%}. Failed and not-evaluated episodes remain distinct in the raw table. The power-limit response does not claim to distinguish internally confounded headroom from availability. Energy capability remains a recorded failure when the zero-mean safety budget cannot reach its boundary.
""", encoding="utf-8")
    branch = SUMMARY_DOC / "E5_BRANCH_DECISION.md"
    branch.write_text(
        "# E5 branch decision\n\n" + (
            "G3 passed, G4 failed, and G5 passed: select branch A (SACID-TMPC).\n" if passed
            else "G3 passed, G4 failed, and G5 failed: select branch R (capability-set robust MPC).\n"
        ), encoding="utf-8"
    )
    reanalysis = RESULT / "E5_TIMING_DENOMINATOR_REANALYSIS.csv"
    pd.DataFrame([{
        "scope": "frozen_existing_E5_results_only", "algorithm_or_scenario_changed": False,
        "timing_evaluated_rows": len(evaluated),
        "not_evaluated_rows": int((~optimized.timing_evaluated).sum()),
        "mechanisms_passing_timing": mechanisms_timing,
    }]).to_csv(reanalysis, index=False)
    outputs = [
        RESULT / "E5_ACTIVE_MANIFEST.csv", episodes_path, RESULT / "E5_PROBE_TRACES.parquet",
        native_path, summary_path, reanalysis,
        REPO / "figures_phase_e" / "E5" / "e5_active_timing.png", report, branch,
    ]
    progress = {
        "stage": "E5", "status": "PASSED" if passed else "FAILED",
        "goal": "Determine whether safe active probing adds timely control-relevant capability information",
        "gate": "G5_ACTIVE", "gate_passed": passed, "gate_components": gate,
        "tests": {
            "plant_a_scenarios": int(episode.scenario_id.nunique()),
            "plant_a_episode_rows": len(episode), "plant_b_episode_rows": len(native),
            "timing_evaluated_optimized_rows": len(evaluated),
            "not_evaluated_optimized_rows": int((~optimized.timing_evaluated).sum()),
            "mechanisms_passing_timing": mechanisms_timing,
            "mechanisms_passing_information": mechanisms_information,
            "frequency_iae_degradation": frequency_degradation,
            "ace_iae_degradation": ace_degradation,
            "maximum_probe_energy_mwh": float(optimized.probe_energy_mwh.max()),
            "maximum_probe_mileage_pu": float(optimized.probe_mileage_pu.max()),
            "adequate_backup_feasible_rate": float(optimized[optimized.sg_tension == "adequate"].backup_feasible_rate.mean()),
        },
        "failures": [] if passed else [key for key, value in gate.items() if not value],
        "repairs": [
            "Timing probability denominator now contains only rows with finite matched Tcrit; not-evaluated rows remain in raw results. No algorithm, scene, seed, threshold, or episode changed."
        ],
        "commands": [
            "python -m scripts.phase_e.run_e5_active_feasibility",
            "python -m scripts.phase_e.reanalyze_e5",
            "python -m pytest tests/phase_e/test_e5_active.py -q",
        ],
        "outputs_sha256": {path.relative_to(REPO).as_posix(): sha256(path) for path in outputs},
        "decision": "SELECT_BRANCH_A" if passed else "SELECT_BRANCH_R",
        "next_stage": "E6",
    }
    (REPO / "progress_phase_e" / "E5.json").write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2))


if __name__ == "__main__":
    main()
