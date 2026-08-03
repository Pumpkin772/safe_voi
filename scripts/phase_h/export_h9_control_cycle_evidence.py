"""Replay the frozen H7 split solely to export package-complete cycle evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.phase_h.run_h7_validation import METHODS, simulate_episode


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normal_equilibrium_traces() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for plant in ("A", "B"):
        for period in (2.0, 4.0):
            for method in METHODS:
                updates = int(3600.0 / period)
                scenario_id = f"H7_{plant}_NORMAL_1H_{period:.0f}s"
                for update in range(updates):
                    rows.append(
                        {
                            "scenario_id": scenario_id,
                            "plant": plant,
                            "seed": -1,
                            "method": method,
                            "mechanism": "normal_net_load",
                            "domain": "SUSTAINABLE",
                            "period_s": period,
                            "update": update,
                            "time_s": update * period,
                            "trace_kind": "CERTIFIED_ZERO_LOAD_EQUILIBRIUM",
                            "controller_active": False,
                            "solver_solved": False,
                            "physical_infeasibility_preclassified": False,
                            "primary_status": "NO_SOLVER_NEEDED_ZERO_EQUILIBRIUM",
                            "restoration_status": "NOT_ATTEMPTED",
                            "restoration_used": False,
                            "fallback_used": False,
                            "load0_pu": 0.0,
                            "load1_pu": 0.0,
                            "frequency0_hz": 0.0,
                            "frequency1_hz": 0.0,
                            "ace0_pu": 0.0,
                            "ace1_pu": 0.0,
                            "tie_line_pu": 0.0,
                            "valve0_pu": 0.0,
                            "valve1_pu": 0.0,
                            "mechanical0_pu": 0.0,
                            "mechanical1_pu": 0.0,
                            "actual_bess0_pu": 0.0,
                            "actual_bess1_pu": 0.0,
                            "issued_sg0_pu": 0.0,
                            "issued_bess0_pu": 0.0,
                            "issued_sg1_pu": 0.0,
                            "issued_bess1_pu": 0.0,
                            "energy0_mwh": 25.0,
                            "energy1_mwh": 25.0,
                            "hard_violation": False,
                        }
                    )
    return rows


def main() -> None:
    result_dir = REPO / "results_phase_h/H9"
    result_dir.mkdir(parents=True, exist_ok=True)
    manifest = pd.read_csv(
        REPO / "results_phase_h/H7/H7_VALIDATION_SCENARIO_MANIFEST.csv"
    )
    official = pd.read_parquet(
        REPO / "results_phase_h/H7/H7_VALIDATION_EPISODES.parquet"
    ).set_index(["scenario_id", "method"])
    traces: list[dict[str, object]] = []
    audits: list[dict[str, object]] = []
    for _, scenario in manifest.iterrows():
        for method in METHODS:
            replay = simulate_episode(scenario, method, trace_sink=traces)
            frozen = official.loc[(scenario.scenario_id, method)]
            for metric in (
                "frequency_iae_hz_s",
                "ace_iae_pu_s",
                "tie_iae_pu_s",
                "failure_aware_cost",
            ):
                left = float(replay[metric])
                right = float(frozen[metric])
                both_nan = np.isnan(left) and np.isnan(right)
                difference = 0.0 if both_nan else abs(left - right)
                audits.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "method": method,
                        "metric": metric,
                        "absolute_difference": difference,
                        "matches_frozen": both_nan or difference <= 1e-9,
                    }
                )
    traces.extend(normal_equilibrium_traces())
    frame = pd.DataFrame(traces)
    for column in frame.select_dtypes(include=["float64"]).columns:
        frame[column] = frame[column].astype("float32")
    all_path = result_dir / "H7_ALL_CONTROL_CYCLE_TRAJECTORIES.parquet"
    frame.to_parquet(all_path, compression="zstd", index=False)
    failed = frame[
        frame.controller_active
        & frame.method.isin(
            [
                "nominal_offset_free_mpc",
                "rls_adaptive_mpc",
                "contract_robust_mpc",
                "true_capability_oracle_mpc",
                "DCSV-MPC",
            ]
        )
        & ~frame.solver_solved
        & ~frame.physical_infeasibility_preclassified
    ]
    failed_path = result_dir / "H7_ALL_FAILED_SOLVER_CYCLE_TRACES.parquet"
    failed.to_parquet(failed_path, compression="zstd", index=False)
    representatives = []
    for mechanism, group in manifest.groupby("mechanism"):
        for scenario_id in group.scenario_id.drop_duplicates().head(3):
            representatives.append(
                {
                    "mechanism": mechanism,
                    "scenario_id": scenario_id,
                    "selection_rule": "first_three_frozen_manifest_rows",
                }
            )
    for scenario_id in manifest.loc[manifest.plant.eq("B"), "scenario_id"].unique():
        representatives.append(
            {
                "mechanism": "plant_b_key_trace",
                "scenario_id": scenario_id,
                "selection_rule": "all_representative_plant_b_rows",
            }
        )
    representative_manifest = pd.DataFrame(representatives).drop_duplicates()
    representative_path = result_dir / "REPRESENTATIVE_TRACE_MANIFEST.csv"
    representative_manifest.to_csv(representative_path, index=False)
    selected = frame[frame.scenario_id.isin(representative_manifest.scenario_id)]
    selected_path = result_dir / "REPRESENTATIVE_CONTROL_CYCLE_TRAJECTORIES.parquet"
    selected.to_parquet(selected_path, compression="zstd", index=False)
    audit = pd.DataFrame(audits)
    audit_path = result_dir / "H7_TRACE_REPLAY_AUDIT.csv"
    audit.to_csv(audit_path, index=False)
    if not audit.matches_frozen.all():
        raise RuntimeError("control-cycle replay does not match frozen H7 metrics")
    summary = {
        "schema": "direction5.phase_h.control_cycle_evidence.v1",
        "frozen_h7_decision_unchanged": True,
        "final_seeds_consumed": False,
        "rows": int(len(frame)),
        "scenarios": int(frame.scenario_id.nunique()),
        "methods": int(frame.method.nunique()),
        "failed_solver_cycle_rows": int(len(failed)),
        "float_precision": "float32 trajectories; float64 frozen statistics and certificates",
        "outputs": {
            path.relative_to(REPO).as_posix(): sha256(path)
            for path in (
                all_path,
                failed_path,
                representative_path,
                selected_path,
                audit_path,
            )
        },
    }
    summary_path = result_dir / "CONTROL_CYCLE_EVIDENCE_SUMMARY.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
