"""Summarize independent zero-region boundary and nonlinear confirmation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research_outputs_boundary/B2_VALIDATION_SUMMARY"


def boundary_split(map_name: str, upper_name: str) -> dict[str, object]:
    source = pd.read_csv(ROOT / f"research_outputs_boundary/{map_name}/BOUNDARY_MAP.csv")
    upper = pd.read_csv(ROOT / f"research_outputs_boundary/{upper_name}/UPPER_CONFIRMATION.csv")
    return {
        "points": int(len(source)),
        "direct_zero_points": int(source.perfect_information_value.le(1e-8).sum()),
        "upper_checked_points": int(len(upper)),
        "positive_upper_points": int(upper.maximum_safe_probe_upper_value.gt(1e-8).sum()),
        "maximum_perfect_information_value": float(source.perfect_information_value.max()),
        "maximum_safe_probe_upper_value": float(upper.maximum_safe_probe_upper_value.max()),
        "solver_attempts": int(source.solver_attempts.sum() + upper.solver_attempts.sum()),
        "solver_failures": int(source.solver_failures.sum() + upper.solver_failures.sum()),
    }


def load_episodes() -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = [
        pd.read_csv(ROOT / "research_outputs_boundary/B2_VALIDATION_1_PLANT_A/EPISODES.csv"),
        pd.read_csv(ROOT / "research_outputs_boundary/B2_VALIDATION_2_PLANT_A/EPISODES.csv"),
    ]
    native_path = ROOT / "research_outputs_boundary/B2_NATIVE_PLANT_B/EPISODES.csv"
    if native_path.exists():
        frames.append(pd.read_csv(native_path))
    episodes = pd.concat(frames, ignore_index=True)
    selected = episodes.loc[episodes.method.eq("selective_voi_accr_mpc")].copy()
    return episodes, selected


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    v1 = boundary_split("B2_VALIDATION1_MAP", "B2_VALIDATION1_UPPER")
    v2 = boundary_split("B2_VALIDATION2_MAP", "B2_VALIDATION2_UPPER")
    episodes, selected = load_episodes()
    paired = episodes.pivot(
        index=["scenario_id", "design_cell", "plant", "period_s", "known_ood", "seed"],
        columns="method",
        values=[
            "frequency_peak_hz", "ace_iae_pu_s", "tie_iae_pu_s",
            "sg_mechanical_mileage_pu", "bess_energy_throughput_pu_s",
            "physical_success", "hard_violation", "command_violation",
        ],
    ).reset_index()
    rows: list[dict[str, object]] = []
    for _, source in paired.iterrows():
        record = {name: source[(name, "")] for name in (
            "scenario_id", "design_cell", "plant", "period_s", "known_ood", "seed",
        )}
        for metric in (
            "frequency_peak_hz", "ace_iae_pu_s", "tie_iae_pu_s",
            "sg_mechanical_mileage_pu", "bess_energy_throughput_pu_s",
        ):
            record[f"contract_minus_selective__{metric}"] = float(
                source[(metric, "contract_mpc")] - source[(metric, "selective_voi_accr_mpc")]
            )
        rows.append(record)
    differences = pd.DataFrame(rows)
    differences.to_csv(OUTPUT / "PAIRED_ABSOLUTE_DIFFERENCES.csv", index=False)
    improvement_columns = [name for name in differences if name.startswith("contract_minus_selective")]
    exact_equivalence = bool(
        all(np.max(np.abs(differences[name])) <= 1e-12 for name in improvement_columns)
        and selected.contract_action_max_abs_difference_pu.max() <= 1e-12
    )
    summary = {
        "project": "DIRECTION5", "method": "selective_VOI_ACCR_MPC",
        "boundary_validation_1": v1, "boundary_validation_2": v2,
        "boundary_positive_region_reproduced": False,
        "nonlinear_scenarios": int(len(selected)),
        "plant_a_scenarios": int(selected.plant.eq("A_full_nonlinear").sum()),
        "native_plant_b_scenarios": int(selected.plant.eq("B_native_ANDES_Kundur").sum()),
        "known_scenarios": int(selected.known_ood.astype(str).str.lower().eq("known").sum()),
        "ood_scenarios": int(selected.known_ood.astype(str).str.lower().eq("ood").sum()),
        "physical_successes": int(selected.physical_success.astype(bool).sum()),
        "terminal_recovery_failures": int((~selected.terminal_recovery.astype(bool)).sum()),
        "hard_violations": int(selected.hard_violation.astype(bool).sum()),
        "command_violations": int(selected.command_violation.astype(bool).sum()),
        "probe_triggers": int(selected.probe_triggers.sum()),
        "probe_command_l1_pu_s": float(selected.probe_command_l1_pu_s.sum()),
        "false_optimistic_certificates": 0,
        "optimistic_certificates_issued": 0,
        "false_optimism_interpretation": "VACUOUS_NO_CERTIFICATE_ISSUED",
        "contract_equivalent": exact_equivalence,
        "maximum_contract_action_difference_pu": float(selected.contract_action_max_abs_difference_pu.max()),
        "maximum_core_metric_difference": float(max(
            np.max(np.abs(differences[name])) for name in improvement_columns
        )),
        "executed_optimization_calls": int(selected.attempted_optimization_calls.sum()),
        "solver_failure_calls": int(selected.solver_failure_calls.sum()),
        "fallback_calls": int(selected.fallback_calls.sum()),
        "maximum_solve_time_s": float(selected.maximum_solve_time_s.max()),
        "ordinary_controller_truth_reads": int(selected.ordinary_controller_truth_read.astype(bool).sum()),
        "native_andes_all_converged": bool(
            selected.loc[selected.plant.eq("B_native_ANDES_Kundur"), "native_converged"].astype(bool).all()
        ) if selected.plant.eq("B_native_ANDES_Kundur").any() else None,
        "native_andes_case": "kundur/kundur_vsc.xlsx",
        "selected_probe": "NONE",
        "candidate_set_reduction": 0.0,
        "oracle_value_recovery": None,
        "oracle_value_recovery_reason": "NO_POSITIVE_VALUE_REGION_AND_NO_PROBE",
    }
    (OUTPUT / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
