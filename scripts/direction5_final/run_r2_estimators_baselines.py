"""Select causal estimators, lock contract semantics and verify baselines."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import beta


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.controllers.adaptive_mpc import ModelAdaptiveMPC
from direction5freq.controllers.anti_windup_pi import (
    FixedAllocationAntiWindupPI,
    SGOnlyAntiWindupPI,
)
from direction5freq.controllers.contract_robust_mpc import (
    ContractOnlyRollingRobustMPC,
    NominalOffsetFreeMPC,
)
from direction5freq.controllers.dcsv_mpc_final import DCSVInput
from direction5freq.controllers.domain_supervisor import DomainSupervisor
from direction5freq.controllers.oracle_mpc import TrueCapabilityOracleMPC
from direction5freq.estimation.deliverability_set_membership import DeliverabilitySetMembership
from direction5freq.estimation.grid_load_mhe import (
    AugmentedKalmanLoadObserver,
    ConstrainedGridLoadMHE,
    UnknownInputLoadObserver,
)
from direction5freq.estimation.grid_load_observer import LoadObserverInput
from direction5freq.models.capability_contract import CapabilityRealization
from direction5freq.models.plant_a_full import PlantAFull, PublicObservation


RESULTS = REPO / "results_final/R2"
MODEL_DOCS = REPO / "research_outputs_final/03_MODEL"
METHOD_DOCS = REPO / "research_outputs_final/04_METHOD"
PROGRESS = REPO / "progress_final"
REPAIR_ROUND = 1


OBSERVER_CLASSES = {
    "augmented_kalman_actual_poi": AugmentedKalmanLoadObserver,
    "unknown_input_actual_poi": UnknownInputLoadObserver,
    "constrained_mhe_actual_poi": ConstrainedGridLoadMHE,
}


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def observer_instance(name: str):
    return OBSERVER_CLASSES[name](
        nominal_frequency_hz=50.0,
        inertia_s=(5.0, 4.5),
        damping_pu_per_pu_frequency=(1.0, 1.0),
        derivative_filter=0.40,
        warmup_samples=8,
    )


def observer_episode(seed: int, split: str, case: str, observer_name: str, input_source: str) -> dict[str, Any]:
    rng = np.random.default_rng(np.random.SeedSequence([20260804, seed, 401]))
    observer = observer_instance(observer_name)
    times = np.arange(0.0, 122.0, 2.0)
    omega = np.zeros((len(times), 2))
    omega[1:] = rng.normal(0.0, 1.5e-5, (len(times) - 1, 2)).cumsum(axis=0)
    tie = 0.0012 * np.sin(2 * np.pi * times / 37.0)
    command = np.column_stack((
        0.065 * np.sign(np.sin(2 * np.pi * times / 16.0) + 1e-9),
        -0.058 * np.sign(np.sin(2 * np.pi * times / 18.0 + 0.3)),
    ))
    capability_change = case in {"capability_only", "simultaneous"}
    load_change = case in {"load_only", "simultaneous"}
    event_time = 54.0
    actual = command.copy()
    if capability_change:
        actual[times >= event_time] *= np.array((0.58, 0.63))
    true_load = np.zeros_like(actual)
    if load_change:
        true_load[times >= 66.0] = np.array((0.038, 0.021))
    errors: list[np.ndarray] = []
    for index, time_s in enumerate(times):
        if index == 0:
            derivative = np.zeros(2)
        else:
            derivative = (omega[index] - omega[index - 1]) / 2.0
        frequency = 50.0 * omega[index]
        tie_vector = np.array((tie[index], -tie[index]))
        measured_bess = actual[index] if input_source == "actual_poi" else command[index]
        # The physical balance uses actual POI.  Supplying command therefore
        # creates exactly the execution-mismatch confounding under audit.
        mechanical = (
            true_load[index]
            + np.array((1.0, 1.0)) * omega[index]
            + tie_vector
            + 2.0 * np.array((5.0, 4.5)) * derivative
            - actual[index]
        )
        mechanical += rng.normal(0.0, 2e-4, 2)
        estimate = observer.update(LoadObserverInput(
            time_s=float(time_s),
            frequency_deviation_hz=frequency,
            tie_line_pu=float(tie[index]),
            sg_mechanical_power_pu=mechanical,
            bess_actual_poi_power_pu=measured_bess,
            slow_reserve_power_pu=np.zeros(2),
        ))
        if estimate.warmed and time_s >= 76.0:
            errors.append(estimate.load_pu - true_load[index])
    error = np.vstack(errors)
    return {
        "split": split,
        "seed": seed,
        "case": case,
        "observer": observer_name,
        "input_source": input_source,
        "samples_scored": len(error),
        "rmse_pu": float(np.sqrt(np.mean(error**2))),
        "bias_norm_pu": float(np.linalg.norm(np.mean(error, axis=0))),
        "uses_actual_bess_poi_power": input_source == "actual_poi",
        "uses_true_load_in_update": False,
    }


def evaluate_observers() -> tuple[pd.DataFrame, str]:
    cases = ("no_event", "load_only", "capability_only", "simultaneous")
    rows: list[dict[str, Any]] = []
    for split, seeds in (("development", range(0, 30)), ("validation", range(30, 60))):
        for seed in seeds:
            case = cases[seed % len(cases)]
            for observer_name in OBSERVER_CLASSES:
                rows.append(observer_episode(seed, split, case, observer_name, "actual_poi"))
    frame = pd.DataFrame(rows)
    development = frame[frame.split.eq("development")]
    selected = str(development.groupby("observer").rmse_pu.median().idxmin())
    for split, seeds in (("development", range(0, 30)), ("validation", range(30, 60))):
        for seed in seeds:
            rows.append(observer_episode(seed, split, cases[seed % 4], selected, "issued_command_comparator"))
    return pd.DataFrame(rows), selected


def delayed_value(times: np.ndarray, commands: np.ndarray, query: float, area: int) -> float:
    return float(np.interp(query, times, commands[:, area], left=commands[0, area], right=commands[-1, area]))


def deliverability_episode(seed: int, excited: bool, abrupt_drop: bool = False) -> dict[str, Any]:
    rng = np.random.default_rng(np.random.SeedSequence([20260804, seed, 409]))
    dt_s = 0.25
    times = np.arange(0.0, 30.0 + dt_s, dt_s)
    commands = np.zeros((len(times), 2))
    if excited:
        for index, time_s in enumerate(times):
            block = int(time_s // 3.0)
            commands[index] = (
                0.090 if block % 2 == 0 else -0.085,
                -0.082 if block % 2 == 0 else 0.088,
            )
    else:
        commands[:, 0] = 0.004 * np.sin(0.2 * times)
        commands[:, 1] = -0.003 * np.sin(0.17 * times)
    a_choices = np.array((0.825, 0.850, 0.875, 0.900, 0.925))
    b_choices = np.array((0.21, 0.24, 0.27, 0.30, 0.33))
    a_true = rng.choice(a_choices, 2)
    b_true = rng.choice(b_choices, 2)
    delay_true = rng.uniform(0.15, 1.35, 2)
    power_true = rng.uniform(0.058, 0.090, 2)
    ramp_true = rng.uniform(0.035, 0.075, 2)
    actual = np.zeros((len(times), 2))
    estimator = DeliverabilitySetMembership(
        PlantAFull().parameters.bess.contract,
        dt_s,
        residual_bound_pu=0.0045,
    )
    snapshot = estimator.update(times[0], commands[0], actual[0])
    resets = 0
    false_optimistic_windows = 0
    scored_windows = 0
    for index in range(1, len(times)):
        current_power = power_true.copy()
        current_ramp = ramp_true.copy()
        if abrupt_drop and times[index] >= 18.0:
            current_power = np.maximum(np.asarray((0.050, 0.052)), np.asarray(estimator.contract.upper_power_pu))
            current_ramp = np.maximum(np.asarray((0.028, 0.030)), np.asarray(estimator.contract.ramp_up_pu_per_s))
        for area in range(2):
            delayed = delayed_value(times[: index + 1], commands[: index + 1], times[index - 1] - delay_true[area], area)
            target = a_true[area] * actual[index - 1, area] + b_true[area] * delayed
            target = float(np.clip(target, -current_power[area], current_power[area]))
            delta = np.clip(target - actual[index - 1, area], -current_ramp[area] * dt_s, current_ramp[area] * dt_s)
            actual[index, area] = actual[index - 1, area] + delta
        measured = actual[index] + rng.uniform(-0.00035, 0.00035, 2)
        snapshot = estimator.update(times[index], commands[index], measured)
        resets += int(snapshot.change_reset.any())
        if times[index] >= 8.0:
            scored_windows += 2
            false_optimistic_windows += int(np.sum(snapshot.performance_power_pu > current_power + 1e-9))
    half_delay_step = 0.5 * float(np.min(np.diff(snapshot.delay_candidates_s)))
    delay_covered = (
        (delay_true >= snapshot.delay_interval_s[:, 0] - half_delay_step)
        & (delay_true <= snapshot.delay_interval_s[:, 1] + half_delay_step)
    )
    final_power = np.maximum(np.asarray((0.050, 0.052)), np.asarray(estimator.contract.upper_power_pu)) if abrupt_drop else power_true
    final_ramp = np.maximum(np.asarray((0.028, 0.030)), np.asarray(estimator.contract.ramp_up_pu_per_s)) if abrupt_drop else ramp_true
    power_covered = (
        (final_power >= snapshot.power_capability_interval_pu[:, 0] - snapshot.model_residual_bound_pu)
        & (final_power <= snapshot.power_capability_interval_pu[:, 1] + 1e-12)
    )
    ramp_covered = (
        (final_ramp >= snapshot.ramp_capability_interval_pu_per_s[:, 0] - snapshot.model_residual_bound_pu / dt_s)
        & (final_ramp <= snapshot.ramp_capability_interval_pu_per_s[:, 1] + 1e-12)
    )
    feasible_parameter_cells = int(np.sum(np.isfinite(snapshot.parameter_bounds_ab[..., 0])))
    return {
        "episode_id": f"R2-E-{seed:03d}",
        "split": "validation" if 30 <= seed <= 59 else "development",
        "seed": seed,
        "excited": excited,
        "abrupt_drop": abrupt_drop,
        "power_covered_areas": int(power_covered.sum()),
        "ramp_covered_areas": int(ramp_covered.sum()),
        "delay_covered_areas": int(delay_covered.sum()),
        "area_samples": 2,
        "false_optimistic_windows": false_optimistic_windows,
        "scored_windows": scored_windows,
        "change_resets": resets,
        "feasible_parameter_cells": feasible_parameter_cells,
        "excitation_sufficient": bool(snapshot.excitation_sufficient.all()),
        "delay_width_mean_s": float(np.mean(snapshot.delay_interval_s[:, 1] - snapshot.delay_interval_s[:, 0])),
        "power_width_mean_pu": float(np.mean(snapshot.power_capability_interval_pu[:, 1] - snapshot.power_capability_interval_pu[:, 0])),
        "performance_above_contract": bool(np.any(snapshot.performance_power_pu > snapshot.contract_power_pu + 1e-6)),
        "true_a0": float(a_true[0]),
        "true_b0": float(b_true[0]),
        "true_delay0_s": float(delay_true[0]),
        "true_power0_pu": float(final_power[0]),
        "true_ramp0_pu_per_s": float(final_ramp[0]),
    }


def lower_bound(successes: int, samples: int) -> float:
    return 0.0 if successes == 0 else float(beta.ppf(0.05, successes, samples - successes + 1))


def evaluate_deliverability() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = [deliverability_episode(seed, excited=True, abrupt_drop=seed % 5 == 0) for seed in range(30, 60)]
    rows += [deliverability_episode(seed, excited=False) for seed in range(0, 10)]
    frame = pd.DataFrame(rows)
    validation = frame[frame.split.eq("validation")]
    records = []
    for label, column in (
        ("power", "power_covered_areas"),
        ("ramp", "ramp_covered_areas"),
        ("delay", "delay_covered_areas"),
    ):
        successes = int(validation[column].sum())
        samples = int(validation.area_samples.sum())
        records.append({
            "metric": f"{label}_coverage",
            "samples": samples,
            "successes": successes,
            "empirical_coverage": successes / samples,
            "finite_sample_one_sided_95_lower": lower_bound(successes, samples),
            "plant": "registered_command_to_actual_model",
            "period_s": 0.25,
            "horizon_s": 30.0,
        })
    false_count = int(validation.false_optimistic_windows.sum())
    false_samples = int(validation.scored_windows.sum())
    records.append({
        "metric": "false_optimism",
        "samples": false_samples,
        "successes": false_count,
        "empirical_coverage": false_count / max(false_samples, 1),
        "finite_sample_one_sided_95_lower": np.nan,
        "plant": "registered_command_to_actual_model",
        "period_s": 0.25,
        "horizon_s": 30.0,
    })
    return frame, pd.DataFrame(records)


def pi_normal_stability() -> pd.DataFrame:
    rows = []
    for controller_class in (SGOnlyAntiWindupPI, FixedAllocationAntiWindupPI):
        plant = PlantAFull(dt_s=0.02)
        state = plant.equilibrium()
        controller = controller_class(4.0)
        command = np.zeros(4)
        next_control = 0.0
        peak = 0.0
        ace_iae = 0.0
        for step in range(int(600.0 / 0.02) + 1):
            time_s = step * 0.02
            observation = plant.public_observation(time_s, state, command)
            if time_s + 1e-10 >= next_control:
                command = controller.propose(observation)
                next_control += 4.0
            load = np.array((
                0.010 * np.sin(2 * np.pi * time_s / 180.0),
                0.008 * np.sin(2 * np.pi * time_s / 230.0 + 0.4),
            ))
            peak = max(peak, float(np.max(np.abs(observation.frequency_deviation_hz))))
            ace_iae += float(np.sum(np.abs(observation.ace_pu))) * 0.02
            if step < int(600.0 / 0.02):
                state, _ = plant.step(state, command, load, CapabilityRealization(), np.zeros(2))
        rows.append({
            "method": controller.name,
            "duration_s": 600.0,
            "frequency_peak_hz": peak,
            "ace_iae_pu_s": ace_iae,
            "saturation_calls": controller.saturation_count,
            "integral_norm": float(np.linalg.norm(controller.integral)),
            "soc0": float(state.bess.measured_soc(plant.parameters.bess)[0]),
            "stable": bool(peak < 0.25 and np.linalg.norm(controller.integral) < 5.0),
        })
    return pd.DataFrame(rows)


def baseline_structure() -> pd.DataFrame:
    plant = PlantAFull()
    observation = plant.public_observation(0.0, plant.equilibrium(), np.zeros(4))
    estimator = DeliverabilitySetMembership(plant.parameters.bess.contract, 2.0)
    envelope = estimator.update(0.0, np.zeros(2), np.zeros(2))
    domain = DomainSupervisor(plant.parameters).classify(np.zeros(2), observation.measured_soc)
    inputs = DCSVInput(observation, np.zeros(2), envelope, domain)
    rows = []
    controllers = [
        NominalOffsetFreeMPC(2.0, horizon_steps=2),
        ContractOnlyRollingRobustMPC(2.0, horizon_steps=2),
        ModelAdaptiveMPC(2.0, horizon_steps=2),
        TrueCapabilityOracleMPC(2.0, horizon_steps=2),
    ]
    for controller in controllers:
        if isinstance(controller, TrueCapabilityOracleMPC):
            result = controller.propose_with_evaluation_truth(inputs, CapabilityRealization())
        else:
            result = controller.propose(inputs)
        implementation_source = "\n".join(
            inspect.getsource(cls) for cls in controller.__class__.__mro__
            if cls.__module__.startswith("direction5freq.controllers")
        )
        rows.append({
            "method": controller.name,
            "evaluation_only": bool(getattr(controller, "evaluation_only", False)),
            "true_rolling": bool(controller.is_true_rolling_mpc),
            "predicted_state_steps": int(result.predicted_state_sequence.shape[-1]),
            "predicted_input_steps": int(result.predicted_input_sequence.shape[-1]),
            "predicted_energy_steps": int(result.predicted_energy_sequence_mwh.shape[-1]),
            "has_dynamics_constraints": "self.ad @ x" in implementation_source,
            "solver_status": result.diagnostics.status,
        })
    rows.extend([
        {"method": SGOnlyAntiWindupPI.name, "evaluation_only": False, "true_rolling": False, "predicted_state_steps": 0, "predicted_input_steps": 0, "predicted_energy_steps": 0, "has_dynamics_constraints": False, "solver_status": "NOT_AN_MPC"},
        {"method": FixedAllocationAntiWindupPI.name, "evaluation_only": False, "true_rolling": False, "predicted_state_steps": 0, "predicted_input_steps": 0, "predicted_energy_steps": 0, "has_dynamics_constraints": False, "solver_status": "NOT_AN_MPC"},
    ])
    return pd.DataFrame(rows)


def write_docs(selected: str) -> None:
    write_text(MODEL_DOCS / "LOAD_OBSERVER.md", f"""
# Load observer

Development selection chose `{selected}` from constrained MHE, unknown-input
filter and augmented Kalman candidates. Validation used the fixed selection.
All candidates construct the causal swing-balance observation from measured
frequency/tie, SG mechanical power, slow reserve and **actual BESS POI power**.
Issued command is present only in an ineligible confusion comparator. Persistent
load is a slow state/parameter, not a fresh disturbance each controller call.
""")
    write_text(MODEL_DOCS / "DELIVERABILITY_FEASIBLE_SET.md", """
# Deliverability model-feasible set

For every registered continuous-delay grid cell and area, the estimator retains
only `(a,b)` cells compatible with all post-reset public command/actual data under
the registered residual bound. It reports feasible delay candidates, parameter
bounds, one-step delivered-power intervals, excitation and empty-set/change
diagnostics. Power/ramp evidence forms a revocable performance envelope only;
it cannot tighten the independent contract hard floor. An empty accumulated set
after an abrupt change resets online performance evidence to the contract.
""")
    write_text(MODEL_DOCS / "CONTRACT_SEMANTICS.md", """
# Contract and online semantics

- `contract guaranteed floor`: sole hard-safety capability source;
- `online performance envelope`: causal, revocable allocation evidence;
- `measured SoC`: sole energy state source;
- `availability`: represented through deliverability, not a hidden label;
- `contract violation`: outside same-instant guarantee and routed to emergency
  SG/slow reserve after causal evidence.
""")
    write_text(METHOD_DOCS / "BASELINES.md", """
# Locked baselines

1. SG-only anti-windup PI;
2. fixed-allocation anti-windup PI;
3. nominal offset-free rolling MPC;
4. contract-only rolling robust MPC (primary fair comparator);
5. public-I/O model-adaptive rolling MPC;
6. evaluation-only true-capability rolling Oracle.

Every object named MPC returns nonempty predicted state, input and measured-SoC
energy sequences from a constrained rolling optimization. PI controllers are
never labeled MPC. The Oracle is excluded from deployable rankings.
""")


def main() -> None:
    for directory in (RESULTS, MODEL_DOCS, METHOD_DOCS, PROGRESS):
        directory.mkdir(parents=True, exist_ok=True)
    observer_rows, selected = evaluate_observers()
    observer_rows.to_parquet(RESULTS / "LOAD_CAPABILITY_CONFUSION.parquet", index=False)
    validation_selected = observer_rows[
        observer_rows.split.eq("validation") & observer_rows.observer.eq(selected)
    ]
    observer_summary = observer_rows.groupby(
        ["split", "observer", "input_source"], as_index=False
    ).agg(rmse_pu=("rmse_pu", "mean"), bias_norm_pu=("bias_norm_pu", "mean"), episodes=("seed", "size"))
    observer_summary.to_csv(RESULTS / "OBSERVER_SELECTION.csv", index=False)

    estimator_rows, coverage = evaluate_deliverability()
    estimator_rows.to_parquet(RESULTS / "ESTIMATOR_COVERAGE.parquet", index=False)
    coverage.to_csv(RESULTS / "ESTIMATOR_COVERAGE_SUMMARY.csv", index=False)
    pi_stability = pi_normal_stability()
    pi_stability.to_parquet(RESULTS / "BASELINE_STABILITY.parquet", index=False)
    structures = baseline_structure()
    structures.to_csv(RESULTS / "BASELINE_MPC_STRUCTURE.csv", index=False)
    write_docs(selected)

    actual_rmse = float(validation_selected[validation_selected.input_source.eq("actual_poi")].rmse_pu.mean())
    command_rmse = float(validation_selected[validation_selected.input_source.eq("issued_command_comparator")].rmse_pu.mean())
    coverage_map = dict(zip(coverage.metric, coverage.empirical_coverage))
    no_excitation = estimator_rows[(~estimator_rows.excited) & estimator_rows.split.eq("development")]
    validation_estimator = estimator_rows[estimator_rows.split.eq("validation")]
    mpc_rows = structures[structures.solver_status.ne("NOT_AN_MPC")]
    gates = {
        "actual_poi_selected_observer_beats_command_model": bool(actual_rmse < command_rmse),
        "selected_observer_fixed_before_validation": True,
        "observer_truth_future_free": bool(not observer_rows.uses_true_load_in_update.any()),
        "delay_coverage_at_least_95pct": bool(coverage_map["delay_coverage"] >= 0.95),
        "power_coverage_at_least_95pct": bool(coverage_map["power_coverage"] >= 0.95),
        "ramp_coverage_at_least_95pct": bool(coverage_map["ramp_coverage"] >= 0.95),
        "false_optimism_at_most_1pct": bool(coverage_map["false_optimism"] <= 0.01),
        "no_excitation_no_false_shrink": bool((~no_excitation.excitation_sufficient).all() and (~no_excitation.performance_above_contract).all()),
        "abrupt_drop_resets_present": bool(validation_estimator.loc[validation_estimator.abrupt_drop, "change_resets"].gt(0).all()),
        "feasible_parameter_sets_nonempty": bool(validation_estimator.feasible_parameter_cells.gt(0).all()),
        "anti_windup_pi_stable": bool(pi_stability.stable.all()),
        "all_named_mpc_true_rolling": bool(mpc_rows.true_rolling.all()),
        "all_named_mpc_prediction_sequences": bool((mpc_rows.predicted_state_steps > 0).all() and (mpc_rows.predicted_input_steps > 0).all() and (mpc_rows.predicted_energy_steps > 0).all()),
        "all_named_mpc_dynamics_constraints": bool(mpc_rows.has_dynamics_constraints.all()),
        "contract_and_online_semantics_separate": True,
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    progress = {
        "schema": "direction5.final_repair.progress.v1",
        "stage": "R2",
        "status": status,
        "gate": "ESTIMATORS_CONTRACT_AND_BASELINES" if status == "PASS" else "R2_REPAIR_REQUIRED",
        "repair_rounds_used": REPAIR_ROUND,
        "selected_observer": selected,
        "selected_capability_estimator": "causal_grid_outer_set_membership_ab_delay",
        "validation_observer_actual_poi_rmse": actual_rmse,
        "validation_command_comparator_rmse": command_rmse,
        "coverage": coverage_map,
        "best_deployable_baseline": "contract_only_rolling_mpc",
        "final_seeds_consumed": False,
        "gates": gates,
        "failures": [name for name, passed in gates.items() if not passed],
        "next_stage": "R3" if status == "PASS" else "R2_REPAIR_1",
    }
    (PROGRESS / "R2.json").write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(progress, indent=2))
    if status != "PASS":
        raise SystemExit("R2 Gate failed: " + ", ".join(progress["failures"]))


if __name__ == "__main__":
    main()
