"""Lock branch R and evaluate the selected capability-set robust tube MPC."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from direction1freq.controllers import ACEPIAntiWindup, design_stable_pi
from direction1freq.controllers.proposed_robust_tube_mpc import CapabilitySetRobustTubeMPC
from direction1freq.models.plant_a_v2 import PlantAParametersV2, TwoAreaPlantAV2
from direction1freq.models.plant_b_andes_v2 import AndesKundurPlantBV2
from direction1freq.optimization.tube_propagation import verify_box_tube
from scripts.phase_e.run_e3_materiality import (
    SharedCausalEstimator, capability_at, load_at, paired_bootstrap_improvement,
)


REPO = Path(__file__).resolve().parents[2]
RESULT = REPO / "results_phase_e" / "E6"
METHOD_DOC = REPO / "research_outputs_phase_e" / "06_METHOD"
SUMMARY_DOC = REPO / "research_outputs_phase_e" / "09_SUMMARY"
FIGURE = REPO / "figures_phase_e" / "E6"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def simulate_proposed(row: pd.Series, horizon: int = 5) -> tuple[dict[str, Any], pd.DataFrame]:
    reserve = float(row.sg_reserve_pu); dt_s = 0.05; duration_s = 96.0
    from dataclasses import replace
    base = PlantAParametersV2()
    plant = TwoAreaPlantAV2(replace(
        base, sg_power_lower_pu=(-reserve, -reserve), sg_power_upper_pu=(reserve, reserve),
        valve_lower_pu=(-1.2 * reserve, -1.2 * reserve),
        valve_upper_pu=(1.2 * reserve, 1.2 * reserve),
    ), dt_s)
    state = plant.equilibrium((float(row.initial_soc_1), float(row.initial_soc_2)))
    controller = CapabilitySetRobustTubeMPC(float(row.sfr_period_s), horizon)
    estimator = SharedCausalEstimator(float(row.sfr_period_s))
    command = np.zeros(4); update_steps = int(round(float(row.sfr_period_s) / dt_s))
    maximum_frequency = maximum_rocof = 0.0
    frequency_iae = ace_iae = tie_iae = cost = 0.0
    previous_frequency = np.zeros(2)
    solver_records = []; control_records = []; physical_error = ""
    for step in range(int(round(duration_s / dt_s)) + 1):
        time_s = step * dt_s
        observation = plant.public_observation(time_s, state, command)
        if step % update_steps == 0:
            estimate, load_estimate = estimator.update(observation)
            action, diagnostic = controller.update(observation, estimate, load_estimate, reserve)
            command = action
            solver_records.append({
                "solved": diagnostic.mpc.solved,
                "infeasible": not diagnostic.mpc.solved,
                "used_fallback": diagnostic.used_fallback,
                "terminal_backup_predicted": diagnostic.terminal_backup_predicted,
                "status": diagnostic.solver_status,
                "primal_residual": diagnostic.primal_residual,
                "solve_time_s": diagnostic.solve_time_s,
                "fallback_reason": diagnostic.fallback_reason,
            })
            control_records.append({
                "scenario_id": row.scenario_id, "time_s": time_s,
                "df1_hz": observation.frequency_deviation_hz[0],
                "df2_hz": observation.frequency_deviation_hz[1],
                "ace1_pu": observation.ace_pu[0], "ace2_pu": observation.ace_pu[1],
                "tie_pu": observation.tie_line_pu,
                "cmd_sg1": command[0], "cmd_b1": command[1],
                "cmd_sg2": command[2], "cmd_b2": command[3],
                "used_fallback": diagnostic.used_fallback,
                "solver_status": diagnostic.solver_status,
            })
        frequency = observation.frequency_deviation_hz
        rocof = (frequency - previous_frequency) / dt_s if step else np.zeros(2)
        maximum_frequency = max(maximum_frequency, float(np.max(np.abs(frequency))))
        maximum_rocof = max(maximum_rocof, float(np.max(np.abs(rocof))))
        frequency_iae += float(np.mean(np.abs(frequency))) * dt_s
        ace_iae += float(np.mean(np.abs(observation.ace_pu))) * dt_s
        tie_iae += abs(observation.tie_line_pu) * dt_s
        cost += (
            20.0 * float(np.mean(frequency**2))
            + 50.0 * float(np.mean(observation.ace_pu**2))
            + 20.0 * observation.tie_line_pu**2
        ) * dt_s
        previous_frequency = frequency.copy()
        if step == int(round(duration_s / dt_s)):
            break
        try:
            state, _ = plant.step(state, command, load_at(row, time_s), capability_at(row, time_s))
        except Exception as error:
            physical_error = f"{type(error).__name__}:{error}"; break
    control = pd.DataFrame(control_records)
    tail = control[control.time_s >= max(0.0, control.time_s.max() - 20.0)]
    terminal_frequency = float(tail[["df1_hz", "df2_hz"]].abs().to_numpy().mean())
    terminal_ace = float(tail[["ace1_pu", "ace2_pu"]].abs().to_numpy().mean())
    terminal_tie = float(tail.tie_pu.abs().mean())
    physical_success = bool(
        not physical_error and maximum_frequency <= 0.80 and maximum_rocof <= 1.0
        and terminal_frequency <= 0.05 and terminal_ace <= 0.03 and terminal_tie <= 0.03
    )
    solver = pd.DataFrame(solver_records)
    finite_residual = solver.loc[np.isfinite(solver.primal_residual), "primal_residual"]
    return {
        "scenario_id": row.scenario_id, "mechanism": row.mechanism,
        "sg_tension": row.sg_tension, "sfr_period_s": float(row.sfr_period_s),
        "split": "development" if int(row.load_seed) < 10 else "validation",
        "method": "capability_set_robust_tube_mpc", "physical_success": physical_success,
        "physical_error": physical_error, "max_abs_frequency_hz": maximum_frequency,
        "max_abs_rocof_hz_s": maximum_rocof, "terminal_frequency_mean_hz": terminal_frequency,
        "terminal_ace_mean_pu": terminal_ace, "terminal_tie_mean_pu": terminal_tie,
        "frequency_iae_hz_s": frequency_iae, "ace_iae_pu_s": ace_iae,
        "tie_iae_pu_s": tie_iae, "independent_rollout_objective": cost,
        "solver_success_fraction": float(solver.solved.mean()),
        "solver_infeasibility_fraction": float(solver.infeasible.mean()),
        "fallback_fraction": float(solver.used_fallback.mean()),
        "solver_residual_p99": float(finite_residual.quantile(0.99)) if len(finite_residual) else float("inf"),
        "solver_time_median_s": float(solver.solve_time_s.median()),
        "solver_time_p99_s": float(solver.solve_time_s.quantile(0.99)),
    }, control


def worker(records: list[dict[str, Any]], horizon: int):
    rows = []; traces = []
    for record in records:
        episode, trace = simulate_proposed(pd.Series(record), horizon)
        rows.append(episode); traces.append(trace)
    return rows, pd.concat(traces, ignore_index=True)


def plant_b_check(horizon: int) -> pd.DataFrame:
    rows = []
    for mechanism in ("headroom", "ramp", "delay", "energy", "availability"):
        for seed in range(3):
            for method in ("fixed_allocation_pi", "capability_set_robust_tube_mpc"):
                reserve = 0.05; period = 4.0
                estimator = SharedCausalEstimator(period, nominal_frequency_hz=60.0)
                if method == "fixed_allocation_pi":
                    kp, ki, _ = design_stable_pi(TwoAreaPlantAV2(), period)
                    controller = ACEPIAntiWindup(period, kp, ki, sg_fraction=0.70)
                else:
                    controller = CapabilitySetRobustTubeMPC(period, horizon)

                def policy(observation):
                    if method == "fixed_allocation_pi":
                        action, _ = controller.update(observation)
                        action[[0, 2]] = np.clip(action[[0, 2]], -reserve, reserve)
                        return action
                    state, load = estimator.update(observation)
                    action, _ = controller.update(observation, state, load, reserve)
                    return action

                scenario = {"mechanism": mechanism, "capability_change_time_s": 12.0}
                native = AndesKundurPlantBV2(dt_s=0.05).run_causal_closed_loop(
                    40.0, period,
                    lambda time_s, magnitude=0.045 + 0.005 * seed: np.array([
                        magnitude if time_s >= 16.0 else 0.0, 0.0
                    ]), policy, lambda time_s, item=scenario: capability_at(item, time_s),
                )
                dt = np.diff(native.time_s, prepend=native.time_s[0])
                rows.append({
                    "plant": "B", "mechanism": mechanism, "seed": seed, "method": method,
                    "physical_success": bool(native.converged and np.max(np.abs(native.frequency_deviation_hz)) <= 0.80),
                    "frequency_iae_hz_s": float(np.sum(np.mean(np.abs(native.frequency_deviation_hz), axis=1) * dt)),
                    "ace_iae_pu_s": float(np.sum(np.mean(np.abs(native.ace_pu), axis=1) * dt)),
                    "tie_iae_pu_s": float(np.sum(np.abs(native.tie_line_pu) * dt)),
                    "max_abs_frequency_hz": float(np.max(np.abs(native.frequency_deviation_hz))),
                    "balance_p99_pu": native.algebraic_power_balance_p99_pu,
                })
    return pd.DataFrame(rows)


def paired_summary(proposed: pd.DataFrame, baseline: pd.DataFrame, split: str) -> dict[str, Any]:
    p = proposed[proposed.split == split].set_index("scenario_id")
    b = baseline.loc[p.index]
    both = p.physical_success & b.physical_success
    joined = pd.DataFrame(index=p.index[both])
    metrics = ("frequency_iae_hz_s", "ace_iae_pu_s", "tie_iae_pu_s")
    output: dict[str, Any] = {
        "split": split, "episodes": len(p),
        "proposed_success_rate": float(p.physical_success.mean()),
        "baseline_success_rate": float(b.physical_success.mean()),
        "both_success_episodes": int(both.sum()),
    }
    passing = 0
    for metric in metrics:
        joined[f"b_{metric}"] = b.loc[joined.index, metric]
        joined[f"p_{metric}"] = p.loc[joined.index, metric]
        point, low, high = paired_bootstrap_improvement(joined, f"b_{metric}", f"p_{metric}")
        output[f"{metric}_improvement"] = point
        output[f"{metric}_ci_low"] = low
        output[f"{metric}_ci_high"] = high
        passing += int(point >= 0.08 and low > 0.0)
    output["core_metrics_passing"] = passing
    return output


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--workers", type=int, default=1); args = parser.parse_args()
    suffix = "pilot" if args.pilot else "full"; output = RESULT / suffix
    output.mkdir(parents=True, exist_ok=True); METHOD_DOC.mkdir(parents=True, exist_ok=True)
    SUMMARY_DOC.mkdir(parents=True, exist_ok=True); FIGURE.mkdir(parents=True, exist_ok=True)
    manifest = pd.read_csv(REPO / "results_phase_e" / "E3" / "full" / "E3_EXPERIMENT_MANIFEST.csv")
    if args.pilot:
        pilot_rows = []
        for _, frame in manifest.groupby(["mechanism", "sfr_period_s"]):
            development = frame[frame.load_seed < 10].head(1)
            validation = frame[frame.load_seed >= 10].head(1)
            pilot_rows.extend([development, validation])
        manifest = pd.concat(pilot_rows, ignore_index=True)
    manifest.to_csv(output / "E6_MANIFEST.csv", index=False)
    records = manifest.to_dict(orient="records"); workers = min(args.workers, len(records))
    chunks = [records[index::workers] for index in range(workers)]
    if workers == 1:
        pieces = [worker(chunks[0], 4 if args.pilot else 5)]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            pieces = list(executor.map(worker, chunks, [4 if args.pilot else 5] * workers))
    rows = []; traces = []
    for chunk_rows, chunk_trace in pieces:
        rows.extend(chunk_rows); traces.append(chunk_trace)
    proposed = pd.DataFrame(rows).sort_values("scenario_id").reset_index(drop=True)
    controls = pd.concat(traces, ignore_index=True).sort_values(["scenario_id", "time_s"])
    proposed.to_parquet(output / "E6_PROPOSED_EPISODES.parquet", index=False)
    controls.to_parquet(output / "E6_PROPOSED_CONTROL_TRACES.parquet", index=False)
    e3 = pd.read_parquet(REPO / "results_phase_e" / "E3" / "full" / "E3_MATERIALITY_EPISODES.parquet")
    baseline = e3[e3.method == "fixed_allocation_pi"].set_index("scenario_id")
    summaries = [paired_summary(proposed, baseline, split) for split in ("development", "validation")]
    comparison = pd.DataFrame(summaries); comparison.to_csv(output / "E6_PAIRED_COMPARISON.csv", index=False)
    native = plant_b_check(4 if args.pilot else 5)
    native.to_parquet(output / "E6_PLANT_B_COMPARISON.parquet", index=False)
    validation = summaries[1]
    solver_infeasibility = float(proposed.solver_infeasibility_fraction.mean())
    p99_time = float(proposed.solver_time_p99_s.quantile(0.99))
    native_pivot = native.pivot_table(index=["mechanism", "seed"], columns="method", values="frequency_iae_hz_s")
    native_direction = bool(float((native_pivot.capability_set_robust_tube_mpc <= native_pivot.fixed_allocation_pi).mean()) >= 0.60)
    controller = CapabilitySetRobustTubeMPC(4.0, 5)
    tube_violation = verify_box_tube(controller.tube, controller.optimizer.ad, controller.optimizer.bd)
    # Explicit forced solver failure exercises SG-only fallback.
    plant = TwoAreaPlantAV2(); state = plant.equilibrium(); observation = plant.public_observation(0.0, state, np.zeros(4))
    estimate = plant.state_vector(state)
    fallback_action, fallback_diagnostic = controller.update(
        observation, estimate, np.zeros(2), 0.05, force_solver_failure=True
    )
    gate = {
        "validation_success_not_more_than_2pp_lower": validation["proposed_success_rate"] >= validation["baseline_success_rate"] - 0.02,
        "two_core_metrics_improve_8pct_with_ci": validation["core_metrics_passing"] >= 2,
        "solver_infeasibility_at_most_1pct": solver_infeasibility <= 0.01,
        "p99_solve_time_under_half_period": p99_time < 1.0,
        "tube_numerical_containment": tube_violation <= 1e-12,
        "forced_failure_reaches_sg_backup": fallback_diagnostic.used_fallback and np.allclose(fallback_action[[1, 3]], 0.0),
        "plant_a_b_direction_consistent": native_direction,
    }
    gate_passed = bool(all(gate.values()))
    selected = METHOD_DOC / "SELECTED_BRANCH.json"
    selected.write_text(json.dumps({
        "selected_branch": "R", "method": "Capability-Set Robust Tube MPC",
        "selection_rule": "G3 pass, G4 fail, G5 fail",
        "immutable_after_stage": "E6", "alternate_branches_implemented": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    formulation = METHOD_DOC / "FORMULATION.md"
    formulation.write_text("""# Capability-Set Robust Tube MPC (branch R)

The selected controller solves a receding finite-horizon QP over explicit state/action sequences and ZOH delayed dynamics. It uses the full preregistered external capability set: 0.03 pu effective power, 0.012 pu/s ramp, and 2 s delay. A finite-horizon box tube propagates public model/load-error bounds under an LQR ancillary gain; state and input limits are tightened by the resulting radii. A fixed-allocation PI action is an optimization reference, not the executed policy. The optimizer executes its first action when feasible and its predicted terminal state lies in the SG-only backup box; otherwise a separately stateful SG-only PI backup is used.

The method never identifies or reads a current capability label. Claims are limited to the registered global set and empirical Plant A/B tests unless E7 certificates justify stronger language.
""", encoding="utf-8")
    implementation = METHOD_DOC / "IMPLEMENTATION_MAP.csv"
    pd.DataFrame([
        ("rolling QP", "controllers/proposed_robust_tube_mpc.py", "CapabilitySetRobustTubeMPC.update"),
        ("finite horizon tube", "optimization/tube_propagation.py", "finite_horizon_reachable_tube"),
        ("terminal SG backup", "optimization/terminal_backup.py", "SGTerminalBackupSet"),
        ("forced failure fallback", "controllers/proposed_robust_tube_mpc.py", "force_solver_failure"),
    ], columns=["object", "file", "symbol"]).to_csv(implementation, index=False)
    plt.figure(figsize=(7, 4.5))
    comparison.set_index("split")[[
        "frequency_iae_hz_s_improvement", "ace_iae_pu_s_improvement", "tie_iae_pu_s_improvement"
    ]].T.plot(kind="bar", ax=plt.gca()); plt.axhline(0.08, color="black", linestyle="--")
    plt.ylabel("paired aggregate-mean improvement"); plt.tight_layout()
    plt.savefig(FIGURE / f"e6_method_{suffix}.png", dpi=180); plt.close()
    report = SUMMARY_DOC / "E6_METHOD_REPORT.md"
    report.write_text(f"""# E6 selected-method report

Branch R was selected before method evaluation by the immutable G3/G4/G5 rule. G6 result: **{'PASS' if gate_passed else 'FAIL — METHOD_NOT_SUPPORTED_BY_EVIDENCE'}**. Validation success is {validation['proposed_success_rate']:.2%} versus {validation['baseline_success_rate']:.2%}; {validation['core_metrics_passing']}/3 core metrics exceed 8% with paired bootstrap CI above zero. Solver infeasibility is {solver_infeasibility:.2%}, p99 solve time {p99_time:.4f} s, and Plant A/B direction is {'consistent' if native_direction else 'not consistent'}.
""", encoding="utf-8")
    outputs = [
        output / "E6_MANIFEST.csv", output / "E6_PROPOSED_EPISODES.parquet",
        output / "E6_PROPOSED_CONTROL_TRACES.parquet", output / "E6_PAIRED_COMPARISON.csv",
        output / "E6_PLANT_B_COMPARISON.parquet", selected, formulation, implementation,
        FIGURE / f"e6_method_{suffix}.png", report,
    ]
    progress = {
        "stage": "E6", "run_type": suffix, "status": "PASSED" if gate_passed else "FAILED",
        "goal": "Implement and validate the uniquely selected branch-R controller",
        "gate": "G6_METHOD", "gate_passed": gate_passed, "selected_branch": "R",
        "selected_method": "Capability-Set Robust Tube MPC", "gate_components": gate,
        "tests": {
            "episodes": len(proposed), "validation_comparison": validation,
            "solver_infeasibility": solver_infeasibility, "solver_time_p99_s": p99_time,
            "tube_worst_violation": tube_violation, "plant_b_rows": len(native),
        },
        "failures": [] if gate_passed else [key for key, value in gate.items() if not value],
        "repairs": [],
        "commands": [
            "python -m scripts.phase_e.run_e6_selected_method --pilot --workers 4",
            "python -m scripts.phase_e.run_e6_selected_method --workers 4",
            "python -m pytest tests/phase_e/test_e6_method.py -q",
        ],
        "outputs_sha256": {path.relative_to(REPO).as_posix(): sha256(path) for path in outputs},
        "decision": "CONTINUE_TO_E7" if gate_passed else "METHOD_NOT_SUPPORTED_BY_EVIDENCE",
        "next_stage": "E7" if gate_passed else "E9",
    }
    path = REPO / "progress_phase_e" / f"E6_{suffix}.json"
    path.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(progress, indent=2))
    if not gate_passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
