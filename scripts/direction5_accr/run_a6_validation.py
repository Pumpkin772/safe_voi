"""Locked A6 validation, native Plant B, normal1h, and registered Gate decision."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.validation import (
    ValidationPolicy,
    capability_for,
    plant_parameters,
    simulate_plant_a_episode,
)
from direction5freq.models.plant_b_andes_full import PlantBAndesFull


LOCK_PATH = REPO / "configs/direction5_accr/a6_validation_lock.yaml"
SELECTION_PATH = REPO / "results_accr/A6/development/A6_FROZEN_SELECTION.json"
RESULTS = REPO / "results_accr/A6/validation"
NATIVE_PARTS = RESULTS / "native_parts"
CYCLE_PARTS = RESULTS / "cycle_parts"
PROGRESS = REPO / "progress_accr/A6.json"


def plant_a_manifest(lock: dict) -> pd.DataFrame:
    rows = []
    seed = int(lock["validation_seeds"][0])
    index = 0
    for mechanism in lock["mechanisms"]:
        for tension in lock["sg_tensions"]:
            for period_s in lock["periods_s"]:
                for condition in lock["conditions"]:
                    rng = np.random.default_rng(np.random.SeedSequence([20260810, seed, 61]))
                    capability_time = float(rng.uniform(82.0, 112.0))
                    relation = str(rng.choice(("before", "simultaneous", "after")))
                    offset = -12.0 if relation == "before" else 12.0 if relation == "after" else 0.0
                    area = str(rng.choice(("area0", "area1", "both")))
                    load_sign = int(rng.choice((-1, 1)))
                    load_magnitude = float(rng.uniform(0.052, 0.064))
                    initial_soc = float(rng.choice((0.40, 0.50, 0.60)))
                    design_cell = f"A_full_nonlinear|{mechanism}|{tension}|{float(period_s):g}"
                    rows.append({
                        "scenario_id": f"A6-V-A-{index:03d}", "split": "validation",
                        "seed": seed, "design_cell": design_cell,
                        "plant": "A_full_nonlinear",
                        "mechanism": mechanism, "sg_tension": tension,
                        "capability_mechanism": mechanism,
                        "period_s": float(period_s), "condition": condition,
                        "control_period_s": float(period_s), "known_ood": condition,
                        "duration_s": float(lock["duration_s"]),
                        "capability_change_time_s": capability_time,
                        "load_event_time_s": capability_time + offset,
                        "load_area": area, "load_sign": load_sign,
                        "load_magnitude_pu": load_magnitude,
                        "timing_relation": relation,
                        "initial_soc": initial_soc,
                        "initial_soc_area1": initial_soc, "initial_soc_area2": initial_soc,
                        "frequency_noise_std_hz": 0.0,
                        "control_jitter_s": 0.0,
                        "dropout_probability": 0.0,
                        "noise_std_hz": 0.0, "jitter_s": 0.0,
                        "probe_eligible": True,
                        "contract_violation": False,
                        "contract_status": "WITHIN_CONTRACT",
                        "materiality_positive": mechanism == lock["statistics"]["materiality_positive_mechanism"],
                        "factor_assignment": "explicit_full_factorial_plus_independent_seeded_draws",
                    })
                    seed += 1
                    index += 1
    return pd.DataFrame(rows)


def plant_b_manifest(lock: dict) -> pd.DataFrame:
    rows = []
    designs = (
        (286, "power_drop", "known", 2.0),
        (287, "power_drop", "OOD", 4.0),
        (288, "ramp_drop", "known", 2.0),
        (289, "ramp_drop", "OOD", 4.0),
    )
    for index, (seed, mechanism, condition, period) in enumerate(designs):
        rng = np.random.default_rng(np.random.SeedSequence([20260810, seed, 79]))
        capability_time = float(rng.uniform(84.0, 108.0))
        relation = str(rng.choice(("before", "simultaneous", "after")))
        area = str(rng.choice(("area0", "area1", "both")))
        load_sign = int(rng.choice((-1, 1)))
        load_magnitude = float(rng.uniform(0.035, 0.045))
        offset = -12.0 if relation == "before" else 12.0 if relation == "after" else 0.0
        rows.append({
            "scenario_id": f"A6-V-B-{index:03d}", "split": "validation",
            "seed": seed, "design_cell": f"B_native_ANDES_Kundur|{mechanism}|low|{period:g}",
            "plant": "B_native_ANDES_Kundur",
            "mechanism": mechanism, "sg_tension": "low", "period_s": period,
            "capability_mechanism": mechanism, "control_period_s": period,
            "condition": condition, "duration_s": float(lock["duration_s"]),
            "known_ood": condition,
            "capability_change_time_s": capability_time,
            "load_event_time_s": capability_time + offset,
            "load_area": area, "load_sign": load_sign,
            "load_magnitude_pu": load_magnitude,
            "timing_relation": relation, "initial_soc": 0.50,
            "initial_soc_area1": 0.50, "initial_soc_area2": 0.50,
            "frequency_noise_std_hz": 0.0, "control_jitter_s": 0.0,
            "noise_std_hz": 0.0, "jitter_s": 0.0,
            "dropout_probability": 0.0, "probe_eligible": True,
            "contract_violation": False,
            "contract_status": "WITHIN_CONTRACT",
            "materiality_positive": mechanism == lock["statistics"]["materiality_positive_mechanism"],
            "factor_assignment": "explicit_balanced_native_design_plus_independent_seeded_draws",
        })
    return pd.DataFrame(rows)


def normal_profile(seed: int) -> np.ndarray:
    rng = np.random.default_rng(np.random.SeedSequence([20260810, seed, 211]))
    values = np.zeros((3601, 2))
    innovations = rng.normal(0.0, 0.00040, (3601, 2))
    for index in range(1, len(values)):
        values[index] = 0.988 * values[index - 1] + innovations[index]
    time_s = np.arange(3601)
    values += np.column_stack((
        0.0055 * np.sin(2.0 * np.pi * time_s / 800.0),
        0.0045 * np.sin(2.0 * np.pi * time_s / 970.0 + 0.4),
    ))
    return np.clip(values, -0.018, 0.018)


def normal_manifest() -> pd.DataFrame:
    return pd.DataFrame([{
        "scenario_id": "A6-N-299", "split": "validation", "seed": 299,
        "design_cell": "A_full_nonlinear|normal1h|low|4",
        "plant": "A_full_nonlinear", "mechanism": "power_drop",
        "capability_mechanism": "none",
        "sg_tension": "low", "period_s": 4.0, "condition": "known",
        "control_period_s": 4.0, "known_ood": "known",
        "duration_s": 3600.0, "capability_change_time_s": 5000.0,
        "load_event_time_s": 0.0, "load_area": "both",
        "load_sign": 0, "load_magnitude_pu": np.nan,
        "timing_relation": "normal_profile", "initial_soc": 0.50,
        "initial_soc_area1": 0.50, "initial_soc_area2": 0.50,
        "frequency_noise_std_hz": 0.0, "control_jitter_s": 0.0,
        "noise_std_hz": 0.0, "jitter_s": 0.0,
        "dropout_probability": 0.0, "probe_eligible": True,
        "contract_violation": False,
        "contract_status": "WITHIN_CONTRACT", "materiality_positive": False,
        "factor_assignment": "independent_real_3600s_validation_profile",
    }])


def contract_violation_audit() -> pd.DataFrame:
    return pd.DataFrame([{
        "scenario_id": f"A6-CV-{index:02d}", "seed": 290 + index,
        "true_power_pu": 0.020, "true_ramp_pu_per_s": 0.010,
        "true_delay_s": 2.0, "truth_contains_contract": False,
        "same_instant_guarantee_claimed": False,
        "classification": "CONTRACT_VIOLATION_OUTSIDE_GUARANTEE_DOMAIN",
        "counted_in_primary_method_gate": False,
        "emergency_route": "SG_AND_SLOW_RESERVE_NEXT_CYCLE_RECOURSE",
    } for index in range(4)])


class NativePolicy:
    def __init__(self, method: str, row: pd.Series, lock: dict, weight: float) -> None:
        self.row = row
        self.method = method
        self.policy = ValidationPolicy(
            method, float(row.period_s), plant_parameters("low", 60.0), lock, weight,
            observation_dt_s=float(row.period_s),
        )
        self.cycle_rows: list[dict[str, Any]] = []

    @property
    def reserve_request(self) -> np.ndarray:
        return self.policy.reserve_request

    def __call__(self, observation) -> np.ndarray:
        self.policy.commit(observation.bess_actual_power_pu)
        self.policy.observe(observation)
        truth = capability_for(self.row, observation.time_s) if self.method == "perfect_capability_recourse_oracle" else None
        action = self.policy.propose(observation, truth)
        self.cycle_rows.append({
            "scenario_id": self.row.scenario_id, "method": self.method,
            "plant": self.row.plant, "time_s": observation.time_s,
            "frequency0_hz": observation.frequency_deviation_hz[0],
            "frequency1_hz": observation.frequency_deviation_hz[1],
            "ace0_pu": observation.ace_pu[0], "ace1_pu": observation.ace_pu[1],
            "tie_pu": observation.tie_line_pu,
            "command_sg0_pu": action[0], "command_bess0_pu": action[1],
            "command_sg1_pu": action[2], "command_bess1_pu": action[3],
            "actual_bess0_pu": observation.bess_actual_power_pu[0],
            "actual_bess1_pu": observation.bess_actual_power_pu[1],
            "soc0": observation.measured_soc[0], "soc1": observation.measured_soc[1],
            "certificate_issues_to_date": int(getattr(self.policy.controller, "certificate_issues", 0)),
            **self.policy.cycle_diagnostics(),
        })
        return action


def simulate_native(row_dict: dict[str, Any], method: str, lock: dict, weight: float) -> dict[str, Any]:
    row = pd.Series(row_dict)
    policy = NativePolicy(method, row, lock, weight)
    plant = PlantBAndesFull(dt_s=0.02)
    magnitude = float(row.load_magnitude_pu) * float(row.load_sign)

    def load(time_s: float) -> np.ndarray:
        if time_s < float(row.load_event_time_s):
            return np.zeros(2)
        if row.load_area == "area0":
            return np.array((magnitude, 0.20 * magnitude))
        if row.load_area == "area1":
            return np.array((0.20 * magnitude, magnitude))
        return np.array((magnitude, 0.75 * magnitude))

    trace = plant.run_causal_closed_loop(
        duration_s=float(row.duration_s), control_period_s=float(row.period_s),
        load_profile=load, policy=policy,
        capability_profile=lambda time_s: capability_for(row, time_s),
        slow_reserve_profile=lambda _time, _observation: policy.reserve_request,
        initial_soc=(float(row.initial_soc), float(row.initial_soc)),
    )
    dt = np.diff(trace.time_s, prepend=trace.time_s[0])
    terminal = trace.time_s >= float(row.duration_s) - 30.0
    frequency_peak = float(np.max(np.abs(trace.frequency_deviation_hz)))
    terminal_recovery = bool(
        np.max(np.abs(trace.frequency_deviation_hz[terminal])) <= 0.12
        and np.max(np.abs(trace.ace_pu[terminal])) <= 0.06
    )
    command_violation = bool(
        np.any(trace.issued_command_pu[:, [0, 2]] < np.asarray(plant_parameters("low").valve_lower_pu) - 1e-8)
        or np.any(trace.issued_command_pu[:, [0, 2]] > np.asarray(plant_parameters("low").valve_upper_pu) + 1e-8)
        or np.any(np.abs(trace.issued_command_pu[:, [1, 3]]) > 0.10 + 1e-8)
    )
    hard = bool(
        np.any(trace.measured_soc < 0.10 - 1e-9)
        or np.any(trace.measured_soc > 0.90 + 1e-9)
        or np.any(np.abs(trace.bess_actual_poi_power_pu) > 0.10 + 1e-8)
    )
    summary = dict(row_dict)
    summary.update({
        "method": method,
        "physical_success": bool(trace.converged and terminal_recovery and not hard and frequency_peak <= 1.0),
        "frequency_peak_hz": frequency_peak,
        "ace_iae_pu_s": float(np.sum(np.abs(trace.ace_pu) * dt[:, None])),
        "tie_iae_pu_s": float(np.sum(np.abs(trace.tie_line_pu) * dt)),
        "sg_mechanical_mileage_pu": float(np.sum(np.abs(np.diff(trace.sg_mechanical_increment_pu, axis=0)))),
        "bess_energy_throughput_pu_s": float(np.sum(np.abs(trace.bess_actual_poi_power_pu) * dt[:, None])),
        "terminal_recovery": terminal_recovery,
        "hard_violation": hard, "command_violation": command_violation, "normal1h": False,
        "native_network": trace.native_network, "native_converged": trace.converged,
        "algebraic_power_balance_p99_pu": trace.algebraic_power_balance_p99_pu,
        **policy.policy.diagnostics(),
    })
    CYCLE_PARTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(policy.cycle_rows).to_parquet(
        CYCLE_PARTS / f"{row.scenario_id}__{method}.parquet",
        index=False, compression="zstd",
    )
    return summary


def _native_part(scenario_id: str, method: str) -> Path:
    return NATIVE_PARTS / f"{scenario_id}__{method}.csv"


def native_worker(index: int, method: str) -> None:
    lock = yaml.safe_load(LOCK_PATH.read_text("utf-8"))
    selection = json.loads(SELECTION_PATH.read_text("utf-8"))
    manifest = plant_b_manifest(lock)
    scenario = manifest.iloc[int(index)]
    result = simulate_native(
        scenario.to_dict(), method, lock,
        float(selection["selected_delivered_branch_weight"]),
    )
    NATIVE_PARTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([result]).to_csv(_native_part(str(scenario.scenario_id), method), index=False)


def _run_native_isolated(index: int, method: str) -> None:
    environment = os.environ.copy()
    environment.update({"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--native-worker", str(index), method],
        cwd=REPO, env=environment, check=True,
    )


def _balanced_bootstrap(
    values: pd.DataFrame,
    column: str,
    resamples: int,
    seed: int,
    *,
    family_size: int = 1,
) -> tuple[float, float, float]:
    cells = list(values.design_cell.unique())
    if not cells:
        return np.nan, np.nan, np.nan
    point = float(values.groupby("design_cell")[column].mean().mean())
    rng = np.random.default_rng(seed)
    samples = np.empty(resamples)
    for sample_index in range(resamples):
        selected_cells = rng.choice(cells, len(cells), replace=True)
        cell_means = []
        for cell in selected_cells:
            data = values.loc[values.design_cell.eq(cell), column].to_numpy()
            cell_means.append(float(np.mean(rng.choice(data, len(data), replace=True))))
        samples[sample_index] = np.mean(cell_means)
    tail = 0.05 / (2.0 * int(family_size))
    lower, upper = np.quantile(samples, (tail, 1.0 - tail))
    return point, float(lower), float(upper)


def primary_statistics(episodes: pd.DataFrame, lock: dict) -> tuple[pd.DataFrame, dict]:
    primary = episodes[episodes.method.isin(lock["primary_methods"])].copy()
    keys = ["scenario_id", "plant", "mechanism", "sg_tension", "period_s", "condition"]
    metric_names = (
        "frequency_peak_hz", "ace_iae_pu_s", "tie_iae_pu_s",
        "sg_mechanical_mileage_pu", "physical_success",
    )
    wide = primary.pivot(index=keys, columns="method", values=list(metric_names)).reset_index()
    rows = []
    for _, row in wide.iterrows():
        base = row.xs("contract_only_recourse_mpc", level=1)
        accr = row.xs("accr_mpc", level=1)
        oracle = row.xs("perfect_capability_recourse_oracle", level=1)
        record = {name: row[(name, "")] for name in keys}
        record["design_cell"] = f"{record['plant']}|{record['mechanism']}|{record['sg_tension']}|{record['period_s']}"
        for metric in metric_names[:-1]:
            record[f"absolute_improvement_{metric}"] = float(base[metric] - accr[metric])
            record[f"relative_improvement_{metric}"] = float((base[metric] - accr[metric]) / max(abs(base[metric]), 1e-9))
            denominator = float(base[metric] - oracle[metric])
            record[f"oracle_value_{metric}"] = denominator
            record[f"value_recovery_{metric}"] = float((base[metric] - accr[metric]) / denominator) if denominator > 1e-9 else np.nan
        record["success_difference"] = float(bool(accr["physical_success"])) - float(bool(base["physical_success"]))
        rows.append(record)
    paired = pd.DataFrame(rows)
    material = paired[paired.mechanism.eq(lock["statistics"]["materiality_positive_mechanism"])].copy()
    resamples = int(lock["statistics"]["bootstrap_resamples"])
    stats_rows = []
    for metric in ("ace_iae_pu_s", "tie_iae_pu_s", "sg_mechanical_mileage_pu", "frequency_peak_hz"):
        column = f"relative_improvement_{metric}"
        family_size = 2 if metric in ("ace_iae_pu_s", "tie_iae_pu_s") else 1
        point, lower, upper = _balanced_bootstrap(
            material, column, resamples, 20260810 + len(stats_rows),
            family_size=family_size,
        )
        recovery_values = material.dropna(subset=[f"value_recovery_{metric}"])
        recovery = _balanced_bootstrap(
            recovery_values, f"value_recovery_{metric}", resamples, 20260820 + len(stats_rows),
            family_size=family_size,
        ) if len(recovery_values) else (np.nan, np.nan, np.nan)
        stats_rows.append({
            "metric": metric, "subset": "A1_MATERIALITY_POSITIVE_POWER_CELLS",
            "scenario_count": int(len(material)),
            "scenario_balanced_relative_improvement": point,
            "ci_lower": lower, "ci_upper": upper,
            "value_recovery_scenario_count": int(len(recovery_values)),
            "scenario_balanced_value_recovery": recovery[0],
            "value_recovery_ci_lower": recovery[1],
            "value_recovery_ci_upper": recovery[2],
            "ci_multiplicity": "BONFERRONI_ACE_TIE" if family_size == 2 else "NONE",
        })
    return paired, {"rows": stats_rows, "material": material}


def gate_decision(episodes: pd.DataFrame, normal: pd.DataFrame, lock: dict) -> tuple[pd.DataFrame, dict]:
    paired, statistical = primary_statistics(episodes, lock)
    statistics = pd.DataFrame(statistical["rows"])
    primary = episodes[episodes.method.isin(lock["primary_methods"])]
    contract = primary[primary.method.eq("contract_only_recourse_mpc")]
    accr = primary[primary.method.eq("accr_mpc")]
    success_drop_pp = 100.0 * (contract.physical_success.mean() - accr.physical_success.mean())
    frequency_delta = float(
        paired.groupby("design_cell").absolute_improvement_frequency_peak_hz.mean().mean() * -1.0
    )
    frequency_baseline = float(contract.frequency_peak_hz.mean())
    frequency_margin = max(
        float(lock["gates"]["frequency_noninferiority_absolute_hz"]),
        float(lock["gates"]["frequency_noninferiority_relative"]) * frequency_baseline,
    )
    contract_fallback = contract.fallback_calls.sum() / max(contract.controller_calls.sum(), 1)
    accr_fallback = accr.fallback_calls.sum() / max(accr.controller_calls.sum(), 1)
    performance = statistics[statistics.metric.isin(("ace_iae_pu_s", "tie_iae_pu_s"))]
    qualifying = performance[
        (performance.scenario_balanced_relative_improvement >= float(lock["gates"]["materiality_metric_improvement_min"]))
        & (performance.ci_lower > 0.0)
        & (performance.scenario_balanced_value_recovery >= float(lock["gates"]["value_recovery_min"]))
        & (performance.value_recovery_ci_lower > 0.0)
    ]
    performance_pass = bool(len(qualifying))
    recovery_pass = performance_pass
    mileage = statistics[statistics.metric.eq("sg_mechanical_mileage_pu")].iloc[0]
    plant_direction = []
    material_paired = paired[paired.mechanism.eq(lock["statistics"]["materiality_positive_mechanism"])]
    for plant, group in material_paired.groupby("plant"):
        plant_direction.append({
            "plant": plant,
            "ace_relative_improvement": float(group.relative_improvement_ace_iae_pu_s.mean()),
            "tie_relative_improvement": float(group.relative_improvement_tie_iae_pu_s.mean()),
        })
    directions = pd.DataFrame(plant_direction)
    qualifying_names = set(qualifying.metric)
    cross_plant = bool(
        len(directions) == 2 and (
            ("ace_iae_pu_s" in qualifying_names and (directions.ace_relative_improvement > 0.0).all())
            or ("tie_iae_pu_s" in qualifying_names and (directions.tie_relative_improvement > 0.0).all())
        )
    )
    all_mpc = episodes[episodes.method.isin(lock["primary_methods"] + lock["additional_baselines"]) & ~episodes.method.isin(("sg_only_anti_windup_pi", "fixed_allocation_anti_windup_pi"))]
    gates = {
        "success_drop_at_most_1pp": bool(success_drop_pp <= float(lock["gates"]["success_drop_pp_max"])),
        "frequency_peak_noninferior": bool(frequency_delta <= frequency_margin),
        "hard_violations_zero": bool(
            not primary.hard_violation.any()
            and not primary.command_violation.any()
            and not normal.hard_violation.any()
        ),
        "fallback_not_above_contract_plus_1pp": bool(100.0 * (accr_fallback - contract_fallback) <= float(lock["gates"]["fallback_difference_pp_max"])),
        "ace_or_tie_improves_4pct_positive_ci": performance_pass,
        "value_recovery_at_least_0p40_positive_ci": recovery_pass,
        "sg_mileage_not_worse": bool(mileage.scenario_balanced_relative_improvement >= -float(lock["gates"]["sg_mileage_relative_worsening_max"])),
        "cross_plant_direction_consistent_positive": cross_plant,
        "normal1h_pass": bool(
            len(normal) == 2 and normal.physical_success.all()
            and normal.frequency_peak_hz.max() <= float(lock["gates"]["normal1h_frequency_peak_hz_max"])
        ),
        "all_mpc_true_rolling": bool(all_mpc.full_rolling.all()),
        "p99_real_time": bool((all_mpc.p99_solve_time_s < float(lock["gates"]["p99_solve_fraction_max"]) * all_mpc.period_s).all()),
        "solver_denominator_all_attempted_calls": bool(
            int(all_mpc.attempted_optimization_calls.sum()) >= int(all_mpc.controller_calls.sum())
        ),
        "plant_b_native_andes": bool(
            episodes.loc[episodes.plant.eq("B_native_ANDES_Kundur"), "native_network"].fillna(False).all()
        ),
    }
    statistics.to_csv(RESULTS / "A6_STATISTICAL_ENDPOINTS.csv", index=False)
    paired.to_csv(RESULTS / "A6_PAIRED_ABSOLUTE_DIFFERENCES.csv", index=False)
    directions.to_csv(RESULTS / "A6_CROSS_PLANT_DIRECTION.csv", index=False)
    gate_frame = pd.DataFrame([{"gate": name, "status": "PASS" if passed else "FAIL"} for name, passed in gates.items()])
    summary = {
        "project": "DIRECTION5", "stage": "A6", "status": "PASS" if all(gates.values()) else "FAIL",
        "gates": gates,
        "success_drop_pp": success_drop_pp,
        "frequency_peak_difference_hz_accr_minus_contract": frequency_delta,
        "frequency_noninferiority_margin_hz": frequency_margin,
        "contract_fallback_rate": contract_fallback,
        "accr_fallback_rate": accr_fallback,
        "attempted_optimization_calls": int(all_mpc.attempted_optimization_calls.sum()),
        "solver_failure_calls": int(all_mpc.solver_failure_calls.sum()),
        "solver_failure_rate": float(all_mpc.solver_failure_calls.sum() / max(all_mpc.attempted_optimization_calls.sum(), 1)),
        "restoration_calls": int(all_mpc.restoration_calls.sum()),
        "fallback_calls": int(all_mpc.fallback_calls.sum()),
        "accr_certificate_issues": int(accr.certificate_issues.sum()),
        "accr_nonzero_certified_surplus_episodes": int((accr.certified_surplus_l1_pu_s > 1e-9).sum()),
        "plant_a_scenarios": int(episodes.loc[episodes.plant.eq("A_full_nonlinear"), "scenario_id"].nunique()),
        "plant_b_scenarios": int(episodes.loc[episodes.plant.eq("B_native_ANDES_Kundur"), "scenario_id"].nunique()),
        "normal1h_method_rows": int(len(normal)),
        "final_seeds_consumed": False,
        "next_stage": "A7" if all(gates.values()) else "A8_NEGATIVE_STOP_NO_A7",
    }
    return gate_frame, summary


def main() -> None:
    lock = yaml.safe_load(LOCK_PATH.read_text("utf-8"))
    selection = json.loads(SELECTION_PATH.read_text("utf-8"))
    if selection["status"] != "PASS" or lock["final_seeds_consumed"]:
        raise RuntimeError("A6 validation requires a passing development freeze and unused final seeds")
    weight = float(selection["selected_delivered_branch_weight"])
    RESULTS.mkdir(parents=True, exist_ok=True)
    plant_a = plant_a_manifest(lock)
    plant_b = plant_b_manifest(lock)
    normals = normal_manifest()
    plant_a.to_csv(RESULTS / "A6_PLANT_A_MANIFEST.csv", index=False)
    plant_b.to_csv(RESULTS / "A6_PLANT_B_MANIFEST.csv", index=False)
    normals.to_csv(RESULTS / "A6_NORMAL1H_MANIFEST.csv", index=False)
    contract_violation_audit().to_csv(RESULTS / "A6_CONTRACT_VIOLATION_AUDIT.csv", index=False)
    checkpoint_path = RESULTS / "A6_EPISODES_CHECKPOINT.csv"
    rows = pd.read_csv(checkpoint_path).to_dict("records") if checkpoint_path.is_file() else []
    completed = {(str(row["scenario_id"]), str(row["method"])) for row in rows}
    row_index = {
        (str(row["scenario_id"]), str(row["method"])): index
        for index, row in enumerate(rows)
    }
    representative = set(plant_a.iloc[[0, 5, 10, 15]].scenario_id)
    for _, scenario in plant_a.iterrows():
        methods = list(lock["primary_methods"])
        if scenario.scenario_id in representative:
            methods += list(lock["additional_baselines"])
        for method in methods:
            key = (str(scenario.scenario_id), str(method))
            cycle_path = CYCLE_PARTS / f"{scenario.scenario_id}__{method}.parquet"
            checkpoint_has_current_manifest = bool(
                key in row_index and rows[row_index[key]].get("design_cell")
            )
            if key in completed and cycle_path.is_file() and checkpoint_has_current_manifest:
                continue
            result = simulate_plant_a_episode(
                scenario.to_dict(), method, lock, weight,
                cycle_output_path=cycle_path,
            )
            if key in row_index:
                rows[row_index[key]] = result
            else:
                row_index[key] = len(rows)
                rows.append(result)
            completed.add(key)
            pd.DataFrame(rows).to_csv(checkpoint_path, index=False)
    for native_index, scenario in plant_b.iterrows():
        for method in lock["primary_methods"]:
            key = (str(scenario.scenario_id), str(method))
            cycle_path = CYCLE_PARTS / f"{scenario.scenario_id}__{method}.parquet"
            checkpoint_has_current_manifest = bool(
                key in row_index and rows[row_index[key]].get("design_cell")
            )
            if key in completed and cycle_path.is_file() and checkpoint_has_current_manifest:
                continue
            part = _native_part(str(scenario.scenario_id), str(method))
            if not part.is_file() or not cycle_path.is_file():
                _run_native_isolated(int(native_index), str(method))
            result = pd.read_csv(part).iloc[0].to_dict()
            if key in row_index:
                rows[row_index[key]] = result
            else:
                row_index[key] = len(rows)
                rows.append(result)
            completed.add(key)
            pd.DataFrame(rows).to_csv(checkpoint_path, index=False)
    episodes = pd.DataFrame(rows)
    episodes.to_csv(RESULTS / "A6_ALL_EPISODES.csv", index=False)

    normal_path = RESULTS / "A6_NORMAL1H_EPISODES_CHECKPOINT.csv"
    normal_rows = pd.read_csv(normal_path).to_dict("records") if normal_path.is_file() else []
    normal_completed = {str(row["method"]) for row in normal_rows}
    normal_index = {str(row["method"]): index for index, row in enumerate(normal_rows)}
    profile = normal_profile(299)
    normal_scenario = normals.iloc[0]
    for method in ("contract_only_recourse_mpc", "accr_mpc"):
        cycle_path = CYCLE_PARTS / f"{normal_scenario.scenario_id}__{method}.parquet"
        if method in normal_completed and cycle_path.is_file():
            continue
        result = simulate_plant_a_episode(
            normal_scenario.to_dict(), method, lock, weight, normal_profile=profile,
            cycle_output_path=cycle_path,
        )
        if method in normal_index:
            normal_rows[normal_index[method]] = result
        else:
            normal_index[method] = len(normal_rows)
            normal_rows.append(result)
        pd.DataFrame(normal_rows).to_csv(normal_path, index=False)
    normal = pd.DataFrame(normal_rows)
    normal.to_csv(RESULTS / "A6_NORMAL1H_EPISODES.csv", index=False)
    gates, summary = gate_decision(episodes, normal, lock)
    gates.to_csv(RESULTS / "A6_ALL_GATES.csv", index=False)
    RESULTS.joinpath("A6_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    failure = gates[gates.status.eq("FAIL")].copy()
    failure["deleted"] = False
    failure["standard_changed"] = False
    failure.to_csv(RESULTS / "A6_FAILURE_LEDGER.csv", index=False)
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps({
        "stage": "A6", "status": summary["status"],
        "summary": "results_accr/A6/validation/A6_SUMMARY.json",
        "next_stage": summary["next_stage"],
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-worker", nargs=2, metavar=("INDEX", "METHOD"))
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.native_worker:
        native_worker(int(arguments.native_worker[0]), arguments.native_worker[1])
    else:
        main()
