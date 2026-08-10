"""Independent M2 validation for the M1-locked Direction5 VOI-ACCR-MPC."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from direction5freq.accr.validation import capability_for, simulate_plant_a_episode
from scripts.direction5_accr.run_a6_validation import normal_profile, simulate_native


LOCK_PATH = REPO / "configs/direction5_voi_accr/m2_validation_lock.yaml"
RESULTS = REPO / "results_direction5_voi_accr/M2"
PARTS = RESULTS / "episode_parts"
NATIVE_PARTS = RESULTS / "native_episode_parts"
CYCLE_PARTS = RESULTS / "cycle_parts"
PROGRESS = REPO / "progress_direction5_voi_accr/M2.json"
PRIMARY_METHODS = (
    "contract_only_recourse_mpc",
    "voi_accr_mpc",
    "perfect_capability_recourse_oracle",
)


def _relation(index: int) -> str:
    return ("before", "simultaneous", "after")[index % 3]


def _event_times(index: int, rng: np.random.Generator) -> tuple[float, float, str]:
    capability_time = float(rng.uniform(104.0, 136.0))
    relation = _relation(index)
    offset = -14.0 if relation == "before" else 14.0 if relation == "after" else 0.0
    return capability_time, capability_time + offset, relation


def plant_a_manifest(lock: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    index = 0
    for mechanism_index, mechanism in enumerate(lock["mechanisms"]):
        for tension_index, tension in enumerate(lock["sg_tensions"]):
            for period_index, period_s in enumerate(lock["periods_s"]):
                for condition_index, condition in enumerate(lock["conditions"]):
                    for value_index, value_region in enumerate(lock["value_regions"]):
                        seed = int(lock["validation_seed_range"][0]) + index
                        rng = np.random.default_rng(
                            np.random.SeedSequence([20260811, seed, 201])
                        )
                        capability_time, load_time, relation = _event_times(index, rng)
                        high = 0.0744 if tension == "low" else 0.0558
                        magnitude = (
                            high if value_region == "HIGH_VALUE_CANDIDATE" else 0.020
                        )
                        rows.append({
                            "scenario_id": f"D5-M2-A-{index:03d}",
                            "split": "validation",
                            "seed": seed,
                            "design_cell": f"A_full_nonlinear|{mechanism}|{tension}|{float(period_s):g}",
                            "plant": "A_full_nonlinear",
                            "mechanism": mechanism,
                            "capability_mechanism": mechanism,
                            "sg_tension": tension,
                            "period_s": float(period_s),
                            "control_period_s": float(period_s),
                            "condition": condition,
                            "known_ood": condition,
                            "duration_s": float(
                                lock["durations_s"][index % len(lock["durations_s"])]
                            ),
                            "capability_change_time_s": capability_time,
                            "load_event_time_s": load_time,
                            "load_area": ("area0", "area1", "both")[(index // 2) % 3],
                            "load_sign": 1,
                            "load_magnitude_pu": magnitude,
                            "timing_relation": relation,
                            "initial_soc": (0.42, 0.50, 0.58)[index % 3],
                            "initial_soc_area1": (0.42, 0.50, 0.58)[index % 3],
                            "initial_soc_area2": (0.42, 0.50, 0.58)[index % 3],
                            "value_region": value_region,
                            "probe_worthwhile_preregistered": (
                                value_region == "HIGH_VALUE_CANDIDATE"
                            ),
                            "contract_violation": False,
                            "contract_status": "WITHIN_CONTRACT",
                            "factor_assignment": "M2_LOCKED_CROSSED_VALUE_REGION_INDEPENDENT_SEEDS",
                        })
                        index += 1
    return pd.DataFrame(rows)


def plant_b_manifest(lock: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    base_seed = int(lock["validation_seed_range"][0]) + 70
    index = 0
    for mechanism_index, mechanism in enumerate(lock["mechanisms"]):
        for condition_index, condition in enumerate(lock["conditions"]):
            for value_index, value_region in enumerate(lock["value_regions"]):
                seed = base_seed + index
                rng = np.random.default_rng(np.random.SeedSequence([20260811, seed, 233]))
                capability_time, load_time, relation = _event_times(index + 1, rng)
                period_s = float(lock["periods_s"][(mechanism_index + condition_index) % 2])
                rows.append({
                    "scenario_id": f"D5-M2-B-{index:03d}",
                    "split": "validation",
                    "seed": seed,
                    "design_cell": f"B_native_ANDES_Kundur|{mechanism}|low|{period_s:g}",
                    "plant": "B_native_ANDES_Kundur",
                    "mechanism": mechanism,
                    "capability_mechanism": mechanism,
                    "sg_tension": "low",
                    "period_s": period_s,
                    "control_period_s": period_s,
                    "condition": condition,
                    "known_ood": condition,
                    "duration_s": float(lock["durations_s"][index % len(lock["durations_s"])]),
                    "capability_change_time_s": capability_time,
                    "load_event_time_s": load_time,
                    "load_area": ("area0", "area1", "both")[index % 3],
                    "load_sign": 1,
                    "load_magnitude_pu": 0.044 if value_region == "HIGH_VALUE_CANDIDATE" else 0.014,
                    "timing_relation": relation,
                    "initial_soc": (0.45, 0.55)[index % 2],
                    "initial_soc_area1": (0.45, 0.55)[index % 2],
                    "initial_soc_area2": (0.45, 0.55)[index % 2],
                    "value_region": value_region,
                    "probe_worthwhile_preregistered": value_region == "HIGH_VALUE_CANDIDATE",
                    "contract_violation": False,
                    "contract_status": "WITHIN_CONTRACT",
                    "factor_assignment": "M2_LOCKED_NATIVE_CROSSED_VALUE_REGION_INDEPENDENT_SEEDS",
                })
                index += 1
    return pd.DataFrame(rows)


def normal_manifest() -> pd.DataFrame:
    return pd.DataFrame([{
        "scenario_id": "D5-M2-NORMAL1H-5399",
        "split": "validation",
        "seed": 5399,
        "design_cell": "A_full_nonlinear|normal1h|low|4",
        "plant": "A_full_nonlinear",
        "mechanism": "power_drop",
        "capability_mechanism": "none",
        "sg_tension": "low",
        "period_s": 4.0,
        "control_period_s": 4.0,
        "condition": "known",
        "known_ood": "known",
        "duration_s": 3600.0,
        "capability_change_time_s": 5000.0,
        "load_event_time_s": 0.0,
        "load_area": "both",
        "load_sign": 0,
        "load_magnitude_pu": np.nan,
        "timing_relation": "continuous_normal_profile",
        "initial_soc": 0.50,
        "initial_soc_area1": 0.50,
        "initial_soc_area2": 0.50,
        "value_region": "NORMAL_OPERATION",
        "probe_worthwhile_preregistered": False,
        "contract_violation": False,
        "contract_status": "WITHIN_CONTRACT",
        "factor_assignment": "M2_GENUINE_3600S_SIMULATION",
    }])


def contract_violation_manifest() -> pd.DataFrame:
    rows = []
    for index, mechanism in enumerate(("power_drop", "ramp_drop", "delay_drop", "power_drop")):
        rows.append({
            "scenario_id": f"D5-M2-CV-{index:02d}",
            "split": "contract_violation_audit",
            "seed": 5382 + index,
            "design_cell": f"A_full_nonlinear|contract_violation|{mechanism}|2",
            "plant": "A_full_nonlinear",
            "mechanism": mechanism,
            "capability_mechanism": mechanism,
            "sg_tension": "low",
            "period_s": 2.0,
            "control_period_s": 2.0,
            "condition": "OOD",
            "known_ood": "contract_violation",
            "duration_s": 300.0,
            "capability_change_time_s": 120.0,
            "load_event_time_s": 106.0,
            "load_area": ("area0", "area1", "both", "area0")[index],
            "load_sign": 1,
            "load_magnitude_pu": 0.055,
            "timing_relation": "before",
            "initial_soc": 0.50,
            "initial_soc_area1": 0.50,
            "initial_soc_area2": 0.50,
            "value_region": "OUTSIDE_GUARANTEE_DOMAIN",
            "probe_worthwhile_preregistered": False,
            "contract_violation": True,
            "contract_status": "BELOW_CONTRACT",
            "true_power_override_pu": 0.020,
            "true_ramp_override_pu_per_s": 0.010,
            "true_delay_override_s": 2.0,
            "factor_assignment": "M2_SEPARATE_CONTRACT_VIOLATION_AUDIT",
        })
    return pd.DataFrame(rows)


def _part(path: Path, scenario_id: str, method: str) -> Path:
    return path / f"{scenario_id}__{method}.csv"


def _save_progress(stage: str, completed: int, total: int, latest: str) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps({
        "project": "DIRECTION5",
        "method": "VOI-ACCR-MPC",
        "milestone": "M2",
        "stage": stage,
        "completed_episode_rows": completed,
        "total_planned_episode_rows": total,
        "latest": latest,
    }, indent=2), encoding="utf-8")


def _run_plant_a(
    manifest: pd.DataFrame,
    methods: tuple[str, ...],
    lock: dict[str, Any],
    *,
    normal: np.ndarray | None = None,
    part_root: Path = PARTS,
) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for _, scenario in manifest.iterrows():
        for method in methods:
            target = _part(part_root, str(scenario.scenario_id), method)
            if not target.exists():
                result = simulate_plant_a_episode(
                    scenario.to_dict(), method, lock,
                    float(lock["voi_controller"]["delivered_branch_weight"]),
                    normal_profile=normal,
                    cycle_output_path=CYCLE_PARTS / f"{scenario.scenario_id}__{method}.parquet",
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                pd.DataFrame([result]).to_csv(target, index=False)
            frames.append(pd.read_csv(target))
            _save_progress("PLANT_A_OR_NORMAL", len(frames), len(manifest) * len(methods), target.name)
    return frames


def _run_native_worker(index: int, method: str) -> None:
    environment = os.environ.copy()
    environment.update({
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "DIRECTION5_RESOURCE_GUARDED": "1",
    })
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--native-worker", str(index), method],
        cwd=REPO, env=environment, check=True,
    )


def native_worker(index: int, method: str) -> None:
    lock = yaml.safe_load(LOCK_PATH.read_text("utf-8"))
    scenario = plant_b_manifest(lock).iloc[int(index)]
    result = simulate_native(
        scenario.to_dict(), method, lock,
        float(lock["voi_controller"]["delivered_branch_weight"]),
        cycle_parts=CYCLE_PARTS,
    )
    target = _part(NATIVE_PARTS, str(scenario.scenario_id), method)
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([result]).to_csv(target, index=False)


def _run_native(manifest: pd.DataFrame, methods: tuple[str, ...]) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    total = len(manifest) * len(methods)
    for index, scenario in manifest.reset_index(drop=True).iterrows():
        for method in methods:
            target = _part(NATIVE_PARTS, str(scenario.scenario_id), method)
            if not target.exists():
                _run_native_worker(int(index), method)
            frames.append(pd.read_csv(target))
            _save_progress("NATIVE_PLANT_B", len(frames), total, target.name)
    return frames


def _wide_pairs(episodes: pd.DataFrame) -> pd.DataFrame:
    metrics = (
        "physical_success", "frequency_peak_hz", "ace_iae_pu_s", "tie_iae_pu_s",
        "sg_mechanical_mileage_pu", "hard_violation", "fallback_calls",
        "controller_calls", "probe_command_l1_pu_s", "voi_probe_triggers",
        "candidate_diameter_reduction_max", "p99_solve_time_s",
    )
    identifiers = [
        "scenario_id", "seed", "design_cell", "plant", "mechanism", "sg_tension",
        "period_s", "condition", "timing_relation", "value_region",
        "probe_worthwhile_preregistered",
    ]
    subset = episodes[episodes.method.isin(PRIMARY_METHODS)].copy()
    wide = subset.pivot(index=identifiers, columns="method", values=list(metrics)).reset_index()
    rows: list[dict[str, Any]] = []
    for _, source in wide.iterrows():
        record = {name: source[(name, "")] for name in identifiers}
        for metric in metrics:
            for method in PRIMARY_METHODS:
                record[f"{metric}__{method}"] = source[(metric, method)]
        for metric in ("frequency_peak_hz", "ace_iae_pu_s", "tie_iae_pu_s", "sg_mechanical_mileage_pu"):
            base = float(record[f"{metric}__contract_only_recourse_mpc"])
            voi = float(record[f"{metric}__voi_accr_mpc"])
            oracle = float(record[f"{metric}__perfect_capability_recourse_oracle"])
            record[f"paired_absolute_improvement__{metric}"] = base - voi
            record[f"oracle_absolute_value__{metric}"] = base - oracle
        rows.append(record)
    return pd.DataFrame(rows)


def _balanced_aggregate(frame: pd.DataFrame, numerator: str, denominator: str) -> float:
    if frame.empty:
        return np.nan
    by_cell = frame.groupby("design_cell")[[numerator, denominator]].mean()
    denominator_value = float(by_cell[denominator].mean())
    return float(by_cell[numerator].mean() / denominator_value) if abs(denominator_value) > 1e-12 else np.nan


def _hierarchical_bootstrap_ratio(
    frame: pd.DataFrame,
    numerator: str,
    denominator: str,
    *,
    resamples: int,
    seed: int,
    row_filter: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> tuple[float, float, float, int]:
    data = frame.copy() if row_filter is None else row_filter(frame.copy())
    cells = list(data.design_cell.unique())
    if not cells:
        return np.nan, np.nan, np.nan, 0
    point = _balanced_aggregate(data, numerator, denominator)
    rng = np.random.default_rng(seed)
    samples: list[float] = []
    for _ in range(int(resamples)):
        chosen_cells = rng.choice(cells, len(cells), replace=True)
        cell_num: list[float] = []
        cell_den: list[float] = []
        for cell in chosen_cells:
            rows = data[data.design_cell.eq(cell)]
            chosen = rows.iloc[rng.integers(0, len(rows), len(rows))]
            cell_num.append(float(chosen[numerator].mean()))
            cell_den.append(float(chosen[denominator].mean()))
        denominator_value = float(np.mean(cell_den))
        if abs(denominator_value) > 1e-12:
            samples.append(float(np.mean(cell_num) / denominator_value))
    if not samples:
        return point, np.nan, np.nan, len(data)
    return point, float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975)), len(data)


def _certificate_audit(episodes: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, scenario in manifest.iterrows():
        path = CYCLE_PARTS / f"{scenario.scenario_id}__voi_accr_mpc.parquet"
        if not path.exists():
            continue
        cycles = pd.read_parquet(path).sort_values("time_s")
        previous = 0
        for _, cycle in cycles.iterrows():
            current = int(cycle.get("certificate_issues_to_date", 0))
            if current <= previous:
                continue
            truth = capability_for(scenario, float(cycle.time_s))
            true_power = np.asarray(truth.upper_power_pu)
            true_ramp = np.asarray(truth.ramp_up_pu_per_s)
            true_delay = np.asarray(truth.delay_s)
            certified_power = np.asarray((cycle.certificate_power0_pu, cycle.certificate_power1_pu))
            certified_ramp = np.asarray((cycle.certificate_ramp0_pu_per_s, cycle.certificate_ramp1_pu_per_s))
            certified_delay = np.asarray((cycle.certificate_delay0_s, cycle.certificate_delay1_s))
            false_optimism = bool(
                np.any(certified_power > true_power + 1e-9)
                or np.any(certified_ramp > true_ramp + 1e-9)
                or np.any(certified_delay < true_delay - 1e-9)
            )
            rows.append({
                "scenario_id": scenario.scenario_id,
                "plant": scenario.plant,
                "time_s": float(cycle.time_s),
                "certificate_issue": current,
                "false_optimism": false_optimism,
            })
            previous = current
    return pd.DataFrame(rows)


def gate_decision(
    episodes: pd.DataFrame,
    normal: pd.DataFrame,
    violation: pd.DataFrame,
    manifest: pd.DataFrame,
    lock: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    paired = _wide_pairs(episodes)
    worthwhile = paired[paired.probe_worthwhile_preregistered.astype(bool)].copy()
    not_worthwhile = paired[~paired.probe_worthwhile_preregistered.astype(bool)].copy()
    resamples = int(lock["statistics"]["bootstrap_resamples"])
    statistics_rows: list[dict[str, Any]] = []
    for index, metric in enumerate(("ace_iae_pu_s", "tie_iae_pu_s")):
        improvement = _hierarchical_bootstrap_ratio(
            worthwhile,
            f"paired_absolute_improvement__{metric}",
            f"{metric}__contract_only_recourse_mpc",
            resamples=resamples,
            seed=20260811 + index,
        )
        minimum_fraction = float(lock["statistics"]["minimum_oracle_value_fraction"])
        recovery = _hierarchical_bootstrap_ratio(
            worthwhile,
            f"paired_absolute_improvement__{metric}",
            f"oracle_absolute_value__{metric}",
            resamples=resamples,
            seed=20260821 + index,
            row_filter=lambda frame, metric=metric: frame[
                frame[f"oracle_absolute_value__{metric}"]
                > minimum_fraction * frame[f"{metric}__contract_only_recourse_mpc"]
            ],
        )
        statistics_rows.append({
            "metric": metric,
            "subset": "PROBE_WORTHWHILE_PREREGISTERED",
            "scenario_count": improvement[3],
            "scenario_balanced_aggregate_improvement": improvement[0],
            "ci_lower": improvement[1],
            "ci_upper": improvement[2],
            "value_recovery_count": recovery[3],
            "scenario_balanced_aggregate_value_recovery": recovery[0],
            "value_recovery_ci_lower": recovery[1],
            "value_recovery_ci_upper": recovery[2],
        })
    statistics = pd.DataFrame(statistics_rows)
    certificates = _certificate_audit(episodes, manifest)
    base = episodes[episodes.method.eq("contract_only_recourse_mpc")]
    voi = episodes[episodes.method.eq("voi_accr_mpc")]
    success_drop_pp = 100.0 * (float(base.physical_success.mean()) - float(voi.physical_success.mean()))
    fallback_base = float(base.fallback_calls.sum() / max(base.controller_calls.sum(), 1))
    fallback_voi = float(voi.fallback_calls.sum() / max(voi.controller_calls.sum(), 1))
    frequency_delta_max = float(
        (paired["frequency_peak_hz__voi_accr_mpc"] - paired["frequency_peak_hz__contract_only_recourse_mpc"]).max()
    )
    performance = statistics[
        (statistics.scenario_balanced_aggregate_improvement >= float(lock["gates"]["worthwhile_ace_or_tie_improvement_min"]))
        & (statistics.ci_lower > float(lock["gates"]["worthwhile_improvement_ci_lower_min"]))
    ]
    recovery = statistics[
        (statistics.scenario_balanced_aggregate_value_recovery >= float(lock["gates"]["oracle_value_recovery_min"]))
        & (statistics.value_recovery_ci_lower > float(lock["gates"]["oracle_value_recovery_ci_lower_min"]))
    ]
    sg_improvement = _balanced_aggregate(
        worthwhile,
        "paired_absolute_improvement__sg_mechanical_mileage_pu",
        "sg_mechanical_mileage_pu__contract_only_recourse_mpc",
    )
    notworth_probe_rate = float(
        (not_worthwhile.voi_probe_triggers__voi_accr_mpc > 0).mean()
    ) if len(not_worthwhile) else np.nan
    notworth_changes: list[float] = []
    for metric in ("frequency_peak_hz", "ace_iae_pu_s", "tie_iae_pu_s", "sg_mechanical_mileage_pu"):
        difference = np.abs(not_worthwhile[f"paired_absolute_improvement__{metric}"])
        baseline = np.maximum(np.abs(not_worthwhile[f"{metric}__contract_only_recourse_mpc"]), 1e-9)
        notworth_changes.extend((difference / baseline).tolist())
    notworth_max_change = float(max(notworth_changes, default=0.0))
    probe_incremental_frequency = float(
        (worthwhile.frequency_peak_hz__voi_accr_mpc - worthwhile.frequency_peak_hz__contract_only_recourse_mpc).max()
    )
    diameter = float(worthwhile.candidate_diameter_reduction_max__voi_accr_mpc.mean())
    false_optimism = float(certificates.false_optimism.mean()) if len(certificates) else 0.0
    plant_direction: dict[str, float] = {}
    for plant, frame in worthwhile.groupby("plant"):
        plant_direction[str(plant)] = max(
            _balanced_aggregate(frame, "paired_absolute_improvement__ace_iae_pu_s", "ace_iae_pu_s__contract_only_recourse_mpc"),
            _balanced_aggregate(frame, "paired_absolute_improvement__tie_iae_pu_s", "tie_iae_pu_s__contract_only_recourse_mpc"),
        )
    gates = {
        "success_noninferiority": success_drop_pp <= float(lock["gates"]["success_drop_pp_max"]),
        "zero_physical_hard_violations": int(voi.hard_violation.sum()) <= int(lock["gates"]["hard_violations_max"]),
        "frequency_noninferiority": frequency_delta_max <= float(lock["gates"]["frequency_peak_delta_hz_max"]),
        "fallback_noninferiority": 100.0 * (fallback_voi - fallback_base) <= float(lock["gates"]["fallback_difference_pp_max"]),
        "solver_time": bool((voi.p99_solve_time_s / voi.period_s < float(lock["gates"]["p99_solve_fraction_max"])).all()),
        "worthwhile_performance": len(performance) > 0,
        "oracle_value_recovery": len(recovery) > 0,
        "sg_mileage_nonworse": sg_improvement >= -float(lock["gates"]["sg_mileage_relative_worsening_max"]),
        "candidate_set_contraction": diameter >= float(lock["gates"]["candidate_diameter_reduction_min"]),
        "probe_incremental_frequency": probe_incremental_frequency <= float(lock["gates"]["probe_incremental_frequency_hz_max"]),
        "false_optimism": false_optimism <= float(lock["gates"]["false_optimism_max"]),
        "not_worthwhile_abstention": notworth_probe_rate <= float(lock["gates"]["not_worthwhile_probe_rate_max"]),
        "not_worthwhile_equivalence": notworth_max_change <= float(lock["gates"]["not_worthwhile_metric_change_max"]),
        "cross_plant_direction": len(plant_direction) == 2 and all(value > 0.0 for value in plant_direction.values()),
        "normal1h_genuine_and_safe": bool(
            len(normal) == 2
            and normal.duration_s.eq(3600.0).all()
            and normal.hard_violation.sum() == 0
            and normal.frequency_peak_hz.max() <= float(lock["gates"]["normal1h_frequency_peak_hz_max"])
        ),
        "native_plant_b": bool(
            episodes.loc[episodes.plant.eq("B_native_ANDES_Kundur"), "native_network"].fillna(False).all()
            and episodes.loc[episodes.plant.eq("B_native_ANDES_Kundur"), "native_converged"].fillna(False).all()
        ),
        "ordinary_controller_causal": not bool(
            episodes.loc[~episodes.method.eq("perfect_capability_recourse_oracle"), "ordinary_controller_truth_read"].any()
        ),
        "contract_violation_separate": bool(
            len(violation) == 8 and violation.contract_status.eq("BELOW_CONTRACT").all()
        ),
    }
    decision = {
        "project": "DIRECTION5",
        "method": "VOI-ACCR-MPC",
        "milestone": "M2_INDEPENDENT_VALIDATION",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "m2_pass": bool(all(gates.values())),
        "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
        "scenario_count": int(episodes.scenario_id.nunique()),
        "plant_a_scenarios": int(episodes.loc[episodes.plant.eq("A_full_nonlinear"), "scenario_id"].nunique()),
        "plant_b_scenarios": int(episodes.loc[episodes.plant.eq("B_native_ANDES_Kundur"), "scenario_id"].nunique()),
        "success_drop_pp": success_drop_pp,
        "voi_hard_violations": int(voi.hard_violation.sum()),
        "frequency_peak_delta_max_hz": frequency_delta_max,
        "fallback_rate_contract": fallback_base,
        "fallback_rate_voi": fallback_voi,
        "attempted_optimization_calls": int(voi.attempted_optimization_calls.sum()),
        "solver_failure_calls": int(voi.solver_failure_calls.sum()),
        "restoration_calls": int(voi.restoration_calls.sum()),
        "fallback_calls": int(voi.fallback_calls.sum()),
        "worthwhile_scenarios": int(len(worthwhile)),
        "worthwhile_probed_scenarios": int((worthwhile.voi_probe_triggers__voi_accr_mpc > 0).sum()),
        "not_worthwhile_scenarios": int(len(not_worthwhile)),
        "not_worthwhile_probe_rate": notworth_probe_rate,
        "not_worthwhile_max_relative_metric_change": notworth_max_change,
        "worthwhile_sg_mileage_improvement": sg_improvement,
        "worthwhile_candidate_diameter_reduction": diameter,
        "probe_incremental_frequency_max_hz": probe_incremental_frequency,
        "certificate_issues_audited": int(len(certificates)),
        "false_optimism_rate": false_optimism,
        "plant_best_metric_improvement": plant_direction,
        "normal1h_method_rows": int(len(normal)),
        "contract_violation_rows": int(len(violation)),
        "final_seeds_consumed": False,
        "m1_configuration_modified": False,
    }
    return paired, certificates, decision


def main() -> None:
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit("Refusing unguarded M2 validation")
    lock = yaml.safe_load(LOCK_PATH.read_text("utf-8"))
    RESULTS.mkdir(parents=True, exist_ok=True)
    plant_a = plant_a_manifest(lock)
    plant_b = plant_b_manifest(lock)
    normal_rows = normal_manifest()
    violation_rows = contract_violation_manifest()
    manifest = pd.concat((plant_a, plant_b), ignore_index=True)
    manifest.to_csv(RESULTS / "M2_VALIDATION_MANIFEST.csv", index=False)
    normal_rows.to_csv(RESULTS / "M2_NORMAL1H_MANIFEST.csv", index=False)
    violation_rows.to_csv(RESULTS / "M2_CONTRACT_VIOLATION_MANIFEST.csv", index=False)

    episode_frames = _run_plant_a(plant_a, PRIMARY_METHODS, lock)
    episode_frames.extend(_run_native(plant_b, PRIMARY_METHODS))
    episodes = pd.concat(episode_frames, ignore_index=True)
    episodes.to_csv(RESULTS / "M2_EPISODES.csv", index=False)

    normal_frames = _run_plant_a(
        normal_rows,
        ("contract_only_recourse_mpc", "voi_accr_mpc"),
        lock,
        normal=normal_profile(5399),
        part_root=RESULTS / "normal1h_episode_parts",
    )
    normal_results = pd.concat(normal_frames, ignore_index=True)
    normal_results.to_csv(RESULTS / "M2_NORMAL1H_EPISODES.csv", index=False)

    violation_frames = _run_plant_a(
        violation_rows,
        ("contract_only_recourse_mpc", "voi_accr_mpc"),
        lock,
        part_root=RESULTS / "contract_violation_episode_parts",
    )
    violation_results = pd.concat(violation_frames, ignore_index=True)
    violation_results.to_csv(RESULTS / "M2_CONTRACT_VIOLATION_EPISODES.csv", index=False)

    paired, certificates, decision = gate_decision(
        episodes, normal_results, violation_results, manifest, lock
    )
    paired.to_csv(RESULTS / "M2_PAIRED.csv", index=False)
    certificates.to_csv(RESULTS / "M2_CERTIFICATE_AUDIT.csv", index=False)
    _, statistics = _statistics_from_existing(paired, lock)
    statistics.to_csv(RESULTS / "M2_STATISTICS.csv", index=False)
    (RESULTS / "M2_DECISION.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True), encoding="utf-8"
    )
    _save_progress("COMPLETE", len(episodes) + len(normal_results) + len(violation_results), len(episodes) + len(normal_results) + len(violation_results), decision["status"])
    print(json.dumps(decision, indent=2, sort_keys=True))


def _statistics_from_existing(paired: pd.DataFrame, lock: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    worthwhile = paired[paired.probe_worthwhile_preregistered.astype(bool)].copy()
    rows = []
    for index, metric in enumerate(("ace_iae_pu_s", "tie_iae_pu_s")):
        improvement = _hierarchical_bootstrap_ratio(
            worthwhile, f"paired_absolute_improvement__{metric}",
            f"{metric}__contract_only_recourse_mpc",
            resamples=int(lock["statistics"]["bootstrap_resamples"]), seed=20260811 + index,
        )
        minimum = float(lock["statistics"]["minimum_oracle_value_fraction"])
        recovery = _hierarchical_bootstrap_ratio(
            worthwhile, f"paired_absolute_improvement__{metric}",
            f"oracle_absolute_value__{metric}",
            resamples=int(lock["statistics"]["bootstrap_resamples"]), seed=20260821 + index,
            row_filter=lambda frame, metric=metric: frame[
                frame[f"oracle_absolute_value__{metric}"]
                > minimum * frame[f"{metric}__contract_only_recourse_mpc"]
            ],
        )
        rows.append({
            "metric": metric, "subset": "PROBE_WORTHWHILE_PREREGISTERED",
            "scenario_count": improvement[3],
            "scenario_balanced_aggregate_improvement": improvement[0],
            "ci_lower": improvement[1], "ci_upper": improvement[2],
            "value_recovery_count": recovery[3],
            "scenario_balanced_aggregate_value_recovery": recovery[0],
            "value_recovery_ci_lower": recovery[1],
            "value_recovery_ci_upper": recovery[2],
        })
    return worthwhile, pd.DataFrame(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-worker", nargs=2, metavar=("INDEX", "METHOD"))
    arguments = parser.parse_args()
    if arguments.native_worker:
        native_worker(int(arguments.native_worker[0]), str(arguments.native_worker[1]))
    else:
        main()
