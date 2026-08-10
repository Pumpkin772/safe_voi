"""Select and validate the registered A3 safe active probe."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.probing import (
    candidate_models, identification_result, load_probe_library,
    safety_pass, safety_result,
)


def main() -> None:
    lock = yaml.safe_load((REPO / "configs/direction5_accr/a3_probe_lock.yaml").read_text("utf-8"))
    models = candidate_models(lock)
    probes = load_probe_library(
        REPO / "research/direction5_accr_mpc_one_goal/reference/probe_library.csv",
        lock["amplitude_candidates_pu"],
    )
    extreme_models = [
        model for model in models
        if model.power_pu in (min(lock["power_candidates_pu"]), max(lock["power_candidates_pu"]))
        and model.ramp_pu_per_s in (min(lock["ramp_candidates_pu_per_s"]), max(lock["ramp_candidates_pu_per_s"]))
        and model.delay_s in (min(lock["delay_candidates_s"]), max(lock["delay_candidates_s"]))
    ]
    development = []
    for probe in probes:
        safety = [safety_result(probe, hypothesis, lock) for hypothesis in extreme_models]
        reductions = [identification_result(truth, probe, models, lock)["diameter_reduction"] for truth in models]
        development.append({
            "probe_id": probe.probe_id, "amplitude_pu": probe.amplitude_pu,
            "sequence": json.dumps(probe.normalized_sequence.tolist()),
            "zero_sum": bool(abs(float(probe.sequence_pu.sum())) <= 1e-12),
            "all_extreme_branches_safe": bool(all(safety_pass(row, lock) for row in safety)),
            "worst_incremental_frequency_hz": max(row["incremental_frequency_peak_hz"] for row in safety),
            "worst_incremental_ace_fraction": max(row["incremental_ace_fraction"] for row in safety),
            "worst_incremental_tie_fraction": max(row["incremental_tie_fraction"] for row in safety),
            "median_predicted_diameter_reduction": float(np.median(reductions)),
            "minimum_predicted_diameter_reduction": float(np.min(reductions)),
        })
    development_frame = pd.DataFrame(development)
    eligible = development_frame[
        development_frame.all_extreme_branches_safe
        & development_frame.median_predicted_diameter_reduction.ge(lock["gates"]["eligible_reduction_target"])
    ].sort_values(
        ["median_predicted_diameter_reduction", "amplitude_pu", "worst_incremental_frequency_hz"],
        ascending=[False, True, True],
    )
    if eligible.empty:
        selected = None
    else:
        row = eligible.iloc[0]
        selected = next(
            probe for probe in probes
            if probe.probe_id == row.probe_id and probe.amplitude_pu == row.amplitude_pu
        )

    output = REPO / "results_accr/A3"
    output.mkdir(parents=True, exist_ok=True)
    development_frame.to_csv(output / "A3_PROBE_LIBRARY_SCREEN.csv", index=False)
    if selected is None:
        summary = {
            "schema": "direction5.accr.a3.v1", "stage": "A3", "status": "FAIL",
            "stop_reason": "SAFE_ACTIVE_IDENTIFICATION_NOT_MATERIAL",
            "selected_probe_policy": None, "final_seeds_consumed": False,
        }
        (output / "A3_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
        print(json.dumps(summary, indent=2)); raise SystemExit(2)

    branch_rows = []
    for truth in models:
        result = safety_result(selected, truth, lock)
        branch_rows.append({
            "power_pu": truth.power_pu, "ramp_pu_per_s": truth.ramp_pu_per_s,
            "delay_s": truth.delay_s, **result, "safe": safety_pass(result, lock),
        })
    branches = pd.DataFrame(branch_rows)
    branches.to_csv(output / "A3_ALL_CANDIDATE_SAFETY.csv", index=False)

    validation_rows = []
    seed_values = list(range(lock["validation_seeds"][0], lock["validation_seeds"][1] + 1))
    rng_order = np.random.default_rng(202608103).permutation(len(models))
    for index, seed in enumerate(seed_values):
        truth = models[int(rng_order[index % len(models)])]
        rng = np.random.default_rng(np.random.SeedSequence([20260810, 303, seed]))
        result = identification_result(truth, selected, models, lock, rng)
        validation_rows.append({
            "episode_id": f"A3-V-{seed}", "seed": seed,
            "materiality_cell": ("power_drop/low", "power_drop/high", "ramp_drop/low")[index % 3],
            "probe_eligible": True, "truth_power_pu": truth.power_pu,
            "truth_ramp_pu_per_s": truth.ramp_pu_per_s, "truth_delay_s": truth.delay_s,
            **result,
            "certificate_validity_s": lock["certificate_validity_s"],
        })
    validation = pd.DataFrame(validation_rows)
    validation.to_csv(output / "A3_VALIDATION_EPISODES.csv", index=False)
    success_fraction = float(validation.diameter_reduction.ge(lock["gates"]["eligible_reduction_target"]).mean())
    false_optimism = float(validation.false_optimism.mean())
    gates = {
        "selected_probe_exists": True,
        "command_level_zero_sum": bool(abs(float(selected.sequence_pu.sum())) <= 1e-12),
        "all_candidate_and_no_surplus_branches_safe": bool(branches.safe.all()),
        "hard_violations_zero": bool(not branches.hard_violation.any()),
        "incremental_frequency_within_limit": bool(branches.incremental_frequency_peak_hz.max() <= lock["gates"]["incremental_frequency_hz_max"]),
        "incremental_ace_within_limit": bool(branches.incremental_ace_fraction.max() <= lock["gates"]["incremental_ace_fraction_max"]),
        "incremental_tie_within_limit": bool(branches.incremental_tie_fraction.max() <= lock["gates"]["incremental_tie_fraction_max"]),
        "at_least_half_eligible_reduce_diameter_40_percent": bool(success_fraction >= lock["gates"]["eligible_fraction_target"]),
        "false_optimism_at_most_1_percent": bool(false_optimism <= lock["gates"]["false_optimism_max"]),
        "truth_containment_complete": bool(validation.truth_contained.all()),
    }
    summary = {
        "schema": "direction5.accr.a3.v1", "stage": "A3",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "selected_probe_policy": {
            "probe_id": selected.probe_id, "amplitude_pu": selected.amplitude_pu,
            "normalized_sequence": selected.normalized_sequence.tolist(),
            "period_s": lock["period_s"], "event_triggered": True,
            "command_neutral_not_actual_power_neutral": True,
        },
        "candidate_branches": len(branches), "validation_episodes": len(validation),
        "eligible_reduction_success_fraction": success_fraction,
        "false_optimism": false_optimism,
        "worst_incremental_frequency_hz": float(branches.incremental_frequency_peak_hz.max()),
        "worst_incremental_ace_fraction": float(branches.incremental_ace_fraction.max()),
        "worst_incremental_tie_fraction": float(branches.incremental_tie_fraction.max()),
        "gates": gates, "repairs_used": 0, "final_seeds_consumed": False,
        "next_stage": "A4" if all(gates.values()) else "A3_REPAIR_1",
    }
    (output / "A3_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if summary["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()

