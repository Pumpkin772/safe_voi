"""Replay frozen development scenarios with transactional action semantics."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from direction1freq.controllers.proposed_robust_tube_mpc import (
    CapabilitySetRobustTubeMPC,
)
from direction1freq.models.plant_a_v2 import PlantAParametersV2, TwoAreaPlantAV2
from scripts.phase_e.run_e3_materiality import (
    SharedCausalEstimator,
    capability_at,
    load_at,
)


REPO = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def simulate_transaction_episode(
    row: dict[str, Any], controller: CapabilitySetRobustTubeMPC
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    series = pd.Series(row)
    reserve = float(series.sg_reserve_pu)
    period = float(series.sfr_period_s)
    dt_s = 0.05
    duration_s = 96.0
    base = PlantAParametersV2()
    plant = TwoAreaPlantAV2(
        replace(
            base,
            sg_power_lower_pu=(-reserve, -reserve),
            sg_power_upper_pu=(reserve, reserve),
            valve_lower_pu=(-1.2 * reserve, -1.2 * reserve),
            valve_upper_pu=(1.2 * reserve, 1.2 * reserve),
        ),
        dt_s,
    )
    controller.reset()
    estimator = SharedCausalEstimator(period)
    state = plant.equilibrium((float(series.initial_soc_1), float(series.initial_soc_2)))
    command = np.zeros(4)
    update_steps = int(round(period / dt_s))
    control_records: list[dict[str, Any]] = []
    finite_actions = True
    hard_violations = 0
    external_history_mismatch = 0
    physical_error = ""
    for step in range(int(round(duration_s / dt_s)) + 1):
        time_s = step * dt_s
        observation = plant.public_observation(time_s, state, command)
        if step % update_steps == 0:
            previous_executed = command.copy()
            estimate, load_estimate = estimator.update(observation)
            command, diagnostic = controller.update(
                observation, estimate, load_estimate, reserve
            )
            finite = bool(np.all(np.isfinite(command)))
            finite_actions &= finite
            external_match = bool(
                np.allclose(
                    diagnostic.mpc.previous_model_action,
                    previous_executed,
                    atol=1e-12,
                )
            )
            external_history_mismatch += int(not external_match)
            hard_violation = bool(
                (not finite)
                or np.max(np.abs(command[[0, 2]])) > reserve + 1e-9
                or np.max(np.abs(command[[1, 3]]))
                > controller.certified_bess_limit + 1e-9
            )
            hard_violations += int(hard_violation)
            control_records.append(
                {
                    "replay_id": str(series.replay_id),
                    "source_scenario_id": str(series.scenario_id),
                    "mechanism": str(series.mechanism),
                    "sfr_period_s": period,
                    "time_s": time_s,
                    "primary_status": diagnostic.mpc.primary_status,
                    "secondary_status": diagnostic.mpc.secondary_status,
                    "primary_primal_residual": diagnostic.mpc.primary_primal_residual,
                    "primary_dual_residual": diagnostic.mpc.primary_dual_residual,
                    "secondary_primal_residual": diagnostic.mpc.secondary_primal_residual,
                    "secondary_dual_residual": diagnostic.mpc.secondary_dual_residual,
                    "mathematical_infeasible": diagnostic.mpc.mathematical_infeasible,
                    "numerical_failure": diagnostic.mpc.numerical_failure,
                    "terminal_reject": diagnostic.mpc.terminal_reject,
                    "restoration_used": diagnostic.mpc.restoration_used,
                    "backup_used": diagnostic.mpc.backup_used,
                    "solver_accepted": diagnostic.mpc.solved,
                    "history_match": diagnostic.mpc.history_match
                    and external_match,
                    "consecutive_backup_count": diagnostic.mpc.consecutive_backup_count,
                    "previous_applied_action": json.dumps(
                        previous_executed.tolist()
                    ),
                    "previous_model_action": json.dumps(
                        diagnostic.mpc.previous_model_action.tolist()
                    ),
                    "applied_action": json.dumps(command.tolist()),
                    "hard_constraint_violation": hard_violation,
                    "solve_time_s": diagnostic.mpc.solve_time_s,
                }
            )
        if step == int(round(duration_s / dt_s)):
            break
        try:
            state, _ = plant.step(
                state, command, load_at(series, time_s), capability_at(series, time_s)
            )
        except Exception as error:
            physical_error = f"{type(error).__name__}:{error}"
            break
    return (
        {
            "replay_id": str(series.replay_id),
            "source_scenario_id": str(series.scenario_id),
            "mechanism": str(series.mechanism),
            "sfr_period_s": period,
            "control_cycles": len(control_records),
            "finite_action_availability": finite_actions,
            "hard_constraint_violations": hard_violations,
            "history_mismatch_cycles": external_history_mismatch,
            "backup_cycles": int(sum(item["backup_used"] for item in control_records)),
            "maximum_consecutive_backup": max(
                (item["consecutive_backup_count"] for item in control_records),
                default=0,
            ),
            "physical_error": physical_error,
        },
        control_records,
    )


def worker(records: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    controllers = {
        2.0: CapabilitySetRobustTubeMPC(2.0, 5),
        4.0: CapabilitySetRobustTubeMPC(4.0, 5),
    }
    episodes: list[dict] = []
    controls: list[dict] = []
    for record in records:
        episode, cycle = simulate_transaction_episode(
            record, controllers[float(record["sfr_period_s"])]
        )
        episodes.append(episode)
        controls.extend(cycle)
    return episodes, controls


def _run_parallel(records: list[dict[str, Any]], workers: int):
    number = max(1, min(workers, len(records)))
    chunks = [records[index::number] for index in range(number)]
    if number == 1:
        pieces = [worker(chunks[0])]
    else:
        with ProcessPoolExecutor(max_workers=number) as executor:
            pieces = list(executor.map(worker, chunks))
    episodes: list[dict] = []
    cycles: list[dict] = []
    for episode_piece, cycle_piece in pieces:
        episodes.extend(episode_piece)
        cycles.extend(cycle_piece)
    return pd.DataFrame(episodes), pd.DataFrame(cycles)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    output = REPO / "results_phase_f" / "F2"
    progress_dir = REPO / "progress_phase_f"
    output.mkdir(parents=True, exist_ok=True)
    progress_dir.mkdir(parents=True, exist_ok=True)
    manifest = pd.read_csv(
        REPO / "results_phase_e" / "E3" / "full" / "E3_EXPERIMENT_MANIFEST.csv"
    )
    development = manifest[manifest.load_seed < 10].copy()
    development["replay_id"] = "development::" + development.scenario_id.astype(str)
    if args.quick:
        development = development.head(12)
    delay_source = manifest[
        (manifest.load_seed < 10) & (manifest.mechanism == "delay")
    ].copy()
    desired_delay = 12 if args.quick else 100
    delay_records = []
    for index in range(desired_delay):
        record = delay_source.iloc[index % len(delay_source)].copy()
        record["replay_id"] = f"delay_stress::{index:03d}::{record.scenario_id}"
        delay_records.append(record)
    delay_stress = pd.DataFrame(delay_records)
    all_records = pd.concat([development, delay_stress], ignore_index=True)
    episodes, cycles = _run_parallel(
        all_records.to_dict(orient="records"), args.workers
    )
    episodes = episodes.sort_values("replay_id").reset_index(drop=True)
    cycles = cycles.sort_values(["replay_id", "time_s"]).reset_index(drop=True)

    taxonomy = (
        cycles.groupby(
            [
                "primary_status",
                "secondary_status",
                "mathematical_infeasible",
                "numerical_failure",
                "terminal_reject",
                "restoration_used",
                "backup_used",
            ],
            dropna=False,
        )
        .size()
        .rename("control_cycles")
        .reset_index()
    )
    episodes_path = output / "TRANSACTION_REPLAY_EPISODES.parquet"
    cycles_path = output / "TRANSACTION_REPLAY_CONTROL_CYCLES.parquet"
    taxonomy_path = output / "SOLVER_FAILURE_ROOT_CAUSE.csv"
    episodes.to_parquet(episodes_path, index=False)
    cycles.to_parquet(cycles_path, index=False)
    taxonomy.to_csv(taxonomy_path, index=False)

    category_count = (
        cycles[[
            "solver_accepted",
            "mathematical_infeasible",
            "numerical_failure",
            "terminal_reject",
            "backup_used",
        ]]
        .astype(bool)
        .any(axis=1)
    )
    development_count = int(episodes.replay_id.str.startswith("development::").sum())
    delay_count = int(episodes.replay_id.str.startswith("delay_stress::").sum())
    mismatch = int((~cycles.history_match).sum())
    availability = float(np.isfinite(cycles.solve_time_s).mean())
    action_availability = float(episodes.finite_action_availability.mean())
    gate = {
        "all_phase_e_development_replayed": development_count
        == (12 if args.quick else 200),
        "at_least_100_delay_stress_episodes": delay_count
        >= (12 if args.quick else 100),
        "actual_model_history_mismatch_zero": mismatch == 0,
        "controller_action_availability_100pct": action_availability == 1.0,
        "failure_taxonomy_complete": bool(category_count.all()),
        "physical_hard_constraint_violations_zero": int(
            episodes.hard_constraint_violations.sum()
        )
        == 0,
        "no_physical_errors": bool((episodes.physical_error == "").all()),
        "solver_time_recorded": availability == 1.0,
    }
    gate_passed = all(gate.values())
    old_fallback_rate = 238 / 12400
    new_backup_rate = float(cycles.backup_used.mean())
    progress = {
        "schema": "direction1.phase_f.progress.v1",
        "stage": "F2",
        "run_type": "quick" if args.quick else "full",
        "gate": "G2_TRANSACTION_AND_SOLVER",
        "gate_passed": gate_passed,
        "gate_components": gate,
        "tests": {
            "development_episodes": development_count,
            "delay_stress_episodes": delay_count,
            "control_cycles": len(cycles),
            "history_mismatch_cycles": mismatch,
            "action_availability": action_availability,
            "hard_constraint_violations": int(
                episodes.hard_constraint_violations.sum()
            ),
            "old_phase_e_fallback_fraction": old_fallback_rate,
            "transactional_replay_backup_fraction": new_backup_rate,
            "maximum_consecutive_backup": int(
                episodes.maximum_consecutive_backup.max()
            ),
        },
        "claim_boundary": (
            "backup-rate change is implementation evidence, not a final method result"
        ),
        "next_stage": "F3" if gate_passed else "F9_NEGATIVE_PACKAGE",
        "outputs_sha256": {
            path.relative_to(REPO).as_posix(): sha256(path)
            for path in (episodes_path, cycles_path, taxonomy_path)
        },
    }
    progress_path = progress_dir / ("F2_quick.json" if args.quick else "F2.json")
    progress_path.write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not gate_passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

