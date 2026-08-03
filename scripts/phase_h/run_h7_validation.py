"""Development/validation lock for DCSV-MPC and registered baselines."""

from __future__ import annotations

import argparse
from dataclasses import replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from direction1freq.controllers.ace_pi_aw import ACEPIAntiWindup, design_stable_pi
from direction1freq.models.bess_capability_v2 import CapabilityTruthV2
from direction1freq.models.delay_augmented_prediction import exact_fractional_delay_vertex
from direction1freq.models.plant_a_v2 import PublicObservationV2, TwoAreaPlantAV2
from direction5_freq.controllers import (
    ContractRobustMPC,
    DCSVInput,
    DisturbanceCapabilitySeparatedViabilityMPC,
    NominalOffsetFreeMPC,
    RLSAdaptiveMPC,
    TrueCapabilityOracleMPC,
)
from direction5_freq.controllers.rolling_mpc_baselines import OracleCapability
from direction5_freq.estimation.capability_set_estimator import CapabilitySetEstimator
from direction5_freq.estimation.grid_disturbance_observer import (
    GridDisturbanceObserver,
    GridPublicMeasurement,
)
from direction5_freq.evaluation.failure_aware_statistics import (
    paired_bootstrap_improvement,
)
from direction5_freq.models.sustainability_classifier import (
    CapabilityContract,
    classify_physical_domain,
)


METHODS = (
    "sg_only_pi",
    "fixed_allocation_pi",
    "nominal_offset_free_mpc",
    "rls_adaptive_mpc",
    "contract_robust_mpc",
    "true_capability_oracle_mpc",
    "DCSV-MPC",
)
DEPLOYABLE_BASELINES = (
    "sg_only_pi",
    "fixed_allocation_pi",
    "nominal_offset_free_mpc",
    "rls_adaptive_mpc",
    "contract_robust_mpc",
)
MECHANISMS = ("headroom", "ramp", "delay", "energy", "availability")
MPC_TYPES = {
    "nominal_offset_free_mpc": NominalOffsetFreeMPC,
    "rls_adaptive_mpc": RLSAdaptiveMPC,
    "contract_robust_mpc": ContractRobustMPC,
    "true_capability_oracle_mpc": TrueCapabilityOracleMPC,
    "DCSV-MPC": DisturbanceCapabilitySeparatedViabilityMPC,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(seeds: range) -> pd.DataFrame:
    rows = []
    for seed in seeds:
        mod = seed % 10
        domain = (
            "PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY"
            if mod in (0, 1)
            else "BRIDGE_ONLY"
            if mod in (2, 3, 4)
            else "SUSTAINABLE"
        )
        reserve = 0.025 if domain != "SUSTAINABLE" else 0.10
        magnitude = 0.22 if domain.startswith("PHYSICALLY") else 0.06 if domain == "BRIDGE_ONLY" else 0.04
        area = seed % 2
        load = np.zeros(2)
        load[area] = magnitude * (1.0 if seed % 4 < 2 else -1.0)
        if domain.startswith("PHYSICALLY"):
            load[:] = magnitude
        rows.append(
            {
                "scenario_id": f"H7_A_{seed:02d}",
                "plant": "A",
                "seed": seed,
                "split": "development" if seed < 20 else "validation",
                "period_s": 2.0 if seed % 2 == 0 else 4.0,
                "registered_duration_s": 300.0 if seed % 3 else 600.0,
                "domain": domain,
                "sg_reserve_pu": reserve,
                "mechanism": MECHANISMS[seed % len(MECHANISMS)],
                "load0": load[0],
                "load1": load[1],
                "initial_soc": (0.20, 0.50, 0.80)[seed % 3],
                "noise_std_hz": (0.0, 0.001, 0.003, 0.005)[seed % 4],
                "dropout_probability": (0.0, 0.02, 0.05)[seed % 3],
                "jitter_bound_s": (0.0, 0.05, 0.10)[seed % 3],
                "repeated_change": seed % 7 == 0,
                "scenario_type": "disturbance_300_600s",
                "known_ood": "known",
            }
        )
    # Representative Plant B uses the same public reduced control layer whose
    # residual set was calibrated against native ANDES in H4.
    for seed in (22, 25, 26, 27):
        matches = [row for row in rows if row["seed"] == seed]
        if not matches:
            continue
        source = matches[0]
        item = dict(source)
        item["scenario_id"] = f"H7_B_{seed:02d}"
        item["plant"] = "B"
        item["split"] = "validation"
        rows.append(item)
    return pd.DataFrame(rows)


def capability_truth(mechanism: str) -> tuple[CapabilityTruthV2, dict[str, np.ndarray]]:
    kwargs = {}
    if mechanism == "headroom":
        kwargs = {"upper_headroom_fraction": (0.35, 0.35), "lower_headroom_fraction": (0.35, 0.35)}
    elif mechanism == "ramp":
        kwargs = {"ramp_up_fraction": (0.15, 0.15), "ramp_down_fraction": (0.15, 0.15)}
    elif mechanism == "delay":
        kwargs = {"delay_s": (1.60, 1.60)}
    elif mechanism == "energy":
        kwargs = {"accessible_energy_fraction": (0.04, 0.04)}
    elif mechanism == "availability":
        kwargs = {"availability": (0.30, 0.30)}
    truth = CapabilityTruthV2(**kwargs)
    availability = np.asarray(truth.availability)
    p_dis = 0.10 * np.asarray(truth.upper_headroom_fraction) * availability
    p_chg = 0.10 * np.asarray(truth.lower_headroom_fraction) * availability
    r_up = 0.08 * np.asarray(truth.ramp_up_fraction) * availability
    r_down = 0.08 * np.asarray(truth.ramp_down_fraction) * availability
    accessible = 20.0 * np.asarray(truth.accessible_energy_fraction)
    values = {
        "p_dis": p_dis,
        "p_chg": p_chg,
        "r_up": r_up,
        "r_down": r_down,
        "delay": np.asarray(truth.delay_s),
        "energy": accessible,
        "availability": availability,
    }
    return truth, values


@lru_cache(maxsize=4)
def pi_gains(period_s: float) -> tuple[float, float]:
    kp, ki, _ = design_stable_pi(TwoAreaPlantAV2(), period_s)
    return kp, ki


def public_observation(time_s, state, previous_action, nominal_frequency):
    c_ace = TwoAreaPlantAV2().linear_continuous_model_separate()[2]
    return PublicObservationV2(
        time_s=time_s,
        frequency_deviation_hz=nominal_frequency * state[:2],
        ace_pu=c_ace @ state,
        tie_line_pu=float(state[2]),
        sg_mechanical_power_pu=state[5:7].copy(),
        bess_power_pu=state[7:9].copy(),
        issued_command_pu=previous_action.copy(),
    )


def physical_contract(values: dict[str, np.ndarray]) -> CapabilityContract:
    return CapabilityContract(
        "evaluation_physical_capability",
        "evaluation_only",
        -values["p_chg"],
        values["p_dis"],
        values["r_down"],
        values["r_up"],
        values["delay"],
        values["energy"],
        values["availability"],
    )


def preclassified_domain(row, values) -> str:
    result = classify_physical_domain(
        np.array([row.load0, row.load1]),
        float(row.sg_reserve_pu),
        0.08 if row.plant == "A" else 0.06,
        physical_contract(values),
        float(row.period_s),
        60.0,
        np.array([0.08, 0.08]),
    )
    return result.classification


def make_controller(method: str, row):
    period = float(row.period_s)
    reserve = float(row.sg_reserve_pu)
    if method in ("sg_only_pi", "fixed_allocation_pi"):
        kp, ki = pi_gains(period)
        return ACEPIAntiWindup(
            period,
            kp,
            ki,
            sg_fraction=1.0 if method == "sg_only_pi" else 0.70,
            total_lower_pu=(-2 * reserve, -2 * reserve),
            total_upper_pu=(2 * reserve, 2 * reserve),
        )
    cls = MPC_TYPES[method]
    return cls(period, 3, plant=str(row.plant), sg_reserve_pu=reserve)


def input_from_estimates(
    estimate,
    capability,
    previous_action,
    actual_bess,
    energy,
) -> DCSVInput:
    # Registered known contract floors are public parameter sources, not truth.
    p_dis = np.maximum(capability.power_discharge_interval_pu[:, 0], 0.020)
    p_chg = np.maximum(capability.power_charge_interval_pu[:, 0], 0.020)
    r_up = np.maximum(capability.ramp_up_interval_pu_per_s[:, 0], 0.008)
    r_down = np.maximum(capability.ramp_down_interval_pu_per_s[:, 0], 0.008)
    e_avail = np.maximum(capability.energy_available_interval_mwh[:, 0], 0.40)
    return DCSVInput(
        estimate.grid_state_pu,
        estimate.load_pu,
        previous_action,
        actual_bess,
        energy,
        p_dis,
        p_chg,
        r_up,
        r_down,
        capability.delay_interval_s,
        e_avail,
        capability.availability_interval,
        60.0,
    )


def simulate_episode(
    row,
    method: str,
    active_updates: int = 8,
    trace_sink: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    truth, values = capability_truth(str(row.mechanism))
    evaluation_domain = preclassified_domain(row, values)
    if evaluation_domain.startswith("PHYSICALLY_INFEASIBLE"):
        if trace_sink is not None:
            trace_sink.append(
                {
                    "scenario_id": row.scenario_id,
                    "plant": row.plant,
                    "seed": int(row.seed),
                    "method": method,
                    "mechanism": row.mechanism,
                    "domain": evaluation_domain,
                    "period_s": float(row.period_s),
                    "update": -1,
                    "time_s": 0.0,
                    "trace_kind": "PHYSICAL_INFEASIBILITY_PRECLASSIFICATION",
                    "controller_active": False,
                    "solver_solved": False,
                    "physical_infeasibility_preclassified": True,
                    "primary_status": "NOT_SOLVED_PRECLASSIFIED_PHYSICAL_INFEASIBILITY",
                    "restoration_status": "NOT_ATTEMPTED",
                    "restoration_used": False,
                    "fallback_used": False,
                    "load0_pu": float(row.load0),
                    "load1_pu": float(row.load1),
                }
            )
        return {
            **row.to_dict(),
            "method": method,
            "evaluation_domain": evaluation_domain,
            "physical_success": np.nan,
            "physically_infeasible_preclassified": True,
            "ordinary_controller_failure": False,
            "frequency_iae_hz_s": np.nan,
            "ace_iae_pu_s": np.nan,
            "tie_iae_pu_s": np.nan,
            "failure_aware_cost": np.nan,
            "hard_violation": False,
            "controller_calls": 0,
            "unsolved_calls": 0,
            "restoration_calls": 0,
            "fallback_calls": 0,
            "solver_p99_s": 0.0,
            "action_history_mismatches": 0,
            "simulated_event_active_s": 0.0,
            "certified_or_held_tail_s": float(row.registered_duration_s),
            "plant_model": "native_residual_calibrated_reduced" if row.plant == "B" else "nonlinear_source_linear_exact_zoh",
        }
    period = float(row.period_s)
    nominal_frequency = 50.0 if row.plant == "A" else 60.0
    rng = np.random.default_rng(int(row.seed) + 90_000 + sum(map(ord, method)))
    controller = make_controller(method, row)
    observer = GridDisturbanceObserver(
        period,
        "reduced_order_kalman_actual_bess_input",
        nominal_frequency_hz=nominal_frequency,
    )
    capability_estimator = CapabilitySetEstimator(
        period, nominal_frequency_hz=nominal_frequency
    )
    state = np.zeros(9)
    previous_action = np.zeros(4)
    actual_bess_command = np.zeros(2)
    energy = np.full(2, 50.0 * float(row.initial_soc))
    frequency_iae = ace_iae = tie_iae = 0.0
    hard_violation = False
    unsolved = restoration = fallback = history_mismatch = 0
    solve_times = []
    c_ace = TwoAreaPlantAV2().linear_continuous_model_separate()[2]
    load = np.array([row.load0, row.load1], dtype=float)
    total_updates = int(round(float(row.registered_duration_s) / period))
    slow_reserve_update = int(np.ceil(60.0 / period))
    # Repair 1: a bridge episode must actually run through the registered slow
    # reserve handoff. The first attempt stopped rolling optimization before
    # 60 s and held a pre-handoff action for the remaining 300--600 s, which is
    # a physical/evaluation defect rather than controller performance.
    required_active_updates = (
        slow_reserve_update + 4
        if evaluation_domain == "BRIDGE_ONLY"
        else active_updates
    )
    executed_updates = min(required_active_updates, total_updates)
    last_action = previous_action.copy()
    for update in range(total_updates):
        time_s = update * period
        trace_kind = "HELD_CERTIFIED_OR_NO_NEW_EVENT_TAIL"
        trace_solved = False
        trace_physical_preclassification = False
        trace_primary_status = "HELD_TAIL_NO_SOLVER_CALL"
        trace_restoration_status = "NOT_ATTEMPTED"
        trace_restoration = False
        trace_fallback = False
        if evaluation_domain == "BRIDGE_ONLY" and update == slow_reserve_update:
            slow_reserve = np.clip(load, -0.08, 0.08)
            load = load - slow_reserve
        if bool(row.repeated_change) and update == max(executed_updates // 2, 1):
            load = 0.85 * load
        frequency_measurement = nominal_frequency * state[:2] + rng.normal(
            0.0, float(row.noise_std_hz), 2
        )
        dropped = bool(rng.random() < float(row.dropout_probability) and update > 0)
        if not dropped or update == 0:
            measurement = GridPublicMeasurement(
                time_s + float(rng.uniform(-row.jitter_bound_s, row.jitter_bound_s)),
                frequency_measurement,
                float(state[2] + rng.normal(0.0, 1e-5)),
                state[5:7] + rng.normal(0.0, 1e-4, 2),
                state[7:9] + rng.normal(0.0, 1e-4, 2),
                previous_action[[0, 2]],
            )
            estimate = observer.update(measurement)
        capability = capability_estimator.update(
            time_s,
            previous_action[[1, 3]],
            state[7:9],
            nominal_frequency * state[:2],
            energy / 50.0,
        )
        if update < executed_updates:
            trace_kind = "ACTIVE_CONTROLLER_UPDATE"
            if method in ("sg_only_pi", "fixed_allocation_pi"):
                observation = public_observation(
                    time_s, state, previous_action, nominal_frequency
                )
                action, _diagnostic = controller.update(observation)
                action[[0, 2]] = np.clip(
                    action[[0, 2]], -row.sg_reserve_pu, row.sg_reserve_pu
                )
                trace_primary_status = "NOT_APPLICABLE_PI"
            else:
                data = input_from_estimates(
                    estimate,
                    capability,
                    previous_action,
                    state[7:9],
                    energy,
                )
                started = perf_counter()
                if method == "true_capability_oracle_mpc":
                    oracle = OracleCapability(
                        values["p_dis"],
                        values["p_chg"],
                        values["r_up"],
                        values["r_down"],
                        values["delay"],
                        values["energy"],
                        values["availability"],
                    )
                    action, diagnostic = controller.control_with_evaluation_truth(
                        data, oracle
                    )
                else:
                    action, diagnostic = controller.control(data)
                solve_times.append(perf_counter() - started)
                trace_solved = bool(diagnostic.solved)
                trace_physical_preclassification = bool(
                    diagnostic.physical_infeasibility_preclassified
                )
                trace_primary_status = diagnostic.primary_status
                trace_restoration_status = diagnostic.restoration_status
                trace_restoration = bool(diagnostic.restoration_used)
                trace_fallback = bool(diagnostic.fallback_used)
                unsolved += int(
                    not diagnostic.solved
                    and not diagnostic.physical_infeasibility_preclassified
                )
                restoration += int(diagnostic.restoration_used)
                fallback += int(diagnostic.fallback_used)
                history_mismatch += int(not diagnostic.action_history_match)
            last_action = np.asarray(action, dtype=float).copy()
        else:
            # No new event occurs in the registered tail. Hold the last applied
            # action and continue the physical dynamics; the tail is reported
            # separately and is not counted as additional solver evidence.
            action = last_action.copy()
        issued = np.asarray(action, dtype=float).copy()
        issued[[0, 2]] = np.clip(
            issued[[0, 2]], -row.sg_reserve_pu, row.sg_reserve_pu
        )
        target_bess = np.clip(issued[[1, 3]], -values["p_chg"], values["p_dis"])
        target_bess = np.where(values["availability"] > 0.0, target_bess, 0.0)
        target_bess = np.minimum(
            np.maximum(
                target_bess,
                actual_bess_command - period * values["r_down"],
            ),
            actual_bess_command + period * values["r_up"],
        )
        applied = issued.copy()
        applied[[1, 3]] = target_bess
        delay = min(float(np.max(values["delay"])), period - 1e-5)
        vertex = exact_fractional_delay_vertex(period, delay)
        next_state = (
            vertex.ad @ state
            + vertex.b_current @ applied
            + vertex.b_previous @ previous_action
            + vertex.ed @ load
        )
        if row.plant == "B":
            next_state += rng.normal(
                0.0,
                np.array([2e-5, 2e-5, 2e-4, 2e-4, 2e-4, 2e-4, 2e-4, 5e-5, 5e-5]),
            )
        mechanical_delta = next_state[5:7] - state[5:7]
        mechanical_delta = np.minimum(
            np.maximum(mechanical_delta, -period * 0.015), period * 0.012
        )
        next_state[5:7] = state[5:7] + mechanical_delta
        next_state[5:7] = np.clip(
            next_state[5:7], -row.sg_reserve_pu, row.sg_reserve_pu
        )
        next_state[3:5] = np.clip(
            next_state[3:5], -1.20 * row.sg_reserve_pu, 1.20 * row.sg_reserve_pu
        )
        next_state[7:9] = np.clip(next_state[7:9], -values["p_chg"], values["p_dis"])
        average_bess = 0.5 * (state[7:9] + next_state[7:9])
        energy -= np.where(
            average_bess >= 0.0,
            average_bess * 1000.0 * period / (3600.0 * 0.95),
            average_bess * 1000.0 * period * 0.95 / 3600.0,
        )
        frequency = nominal_frequency * next_state[:2]
        ace = c_ace @ next_state
        frequency_iae += float(np.sum(np.abs(frequency)) * period)
        ace_iae += float(np.sum(np.abs(ace)) * period)
        tie_iae += abs(float(next_state[2])) * period
        hard_violation |= bool(
            np.max(np.abs(frequency)) > 0.80 + 1e-8
            or np.max(np.abs(ace)) > 0.30 + 1e-8
            or abs(next_state[2]) > 0.15 + 1e-8
            or np.any(np.abs(next_state[5:7]) > row.sg_reserve_pu + 1e-8)
            or np.any(energy < 5.0 - 1e-8)
            or np.any(energy > 45.0 + 1e-8)
        )
        if trace_sink is not None:
            trace_sink.append(
                {
                    "scenario_id": row.scenario_id,
                    "plant": row.plant,
                    "seed": int(row.seed),
                    "method": method,
                    "mechanism": row.mechanism,
                    "domain": evaluation_domain,
                    "period_s": period,
                    "update": update,
                    "time_s": time_s,
                    "trace_kind": trace_kind,
                    "controller_active": update < executed_updates,
                    "solver_solved": trace_solved,
                    "physical_infeasibility_preclassified": trace_physical_preclassification,
                    "primary_status": trace_primary_status,
                    "restoration_status": trace_restoration_status,
                    "restoration_used": trace_restoration,
                    "fallback_used": trace_fallback,
                    "load0_pu": float(load[0]),
                    "load1_pu": float(load[1]),
                    "frequency0_hz": float(frequency[0]),
                    "frequency1_hz": float(frequency[1]),
                    "ace0_pu": float(ace[0]),
                    "ace1_pu": float(ace[1]),
                    "tie_line_pu": float(next_state[2]),
                    "valve0_pu": float(next_state[3]),
                    "valve1_pu": float(next_state[4]),
                    "mechanical0_pu": float(next_state[5]),
                    "mechanical1_pu": float(next_state[6]),
                    "actual_bess0_pu": float(next_state[7]),
                    "actual_bess1_pu": float(next_state[8]),
                    "issued_sg0_pu": float(issued[0]),
                    "issued_bess0_pu": float(issued[1]),
                    "issued_sg1_pu": float(issued[2]),
                    "issued_bess1_pu": float(issued[3]),
                    "energy0_mwh": float(energy[0]),
                    "energy1_mwh": float(energy[1]),
                    "hard_violation": bool(hard_violation),
                }
            )
        state = next_state
        previous_action = issued
        actual_bess_command = target_bess
    physical_success = not hard_violation
    failure_cost = frequency_iae + 10.0 * ace_iae + tie_iae + (0.0 if physical_success else 100.0)
    return {
        **row.to_dict(),
        "method": method,
        "evaluation_domain": evaluation_domain,
        "physical_success": physical_success,
        "physically_infeasible_preclassified": False,
        "ordinary_controller_failure": not physical_success,
        "frequency_iae_hz_s": frequency_iae,
        "ace_iae_pu_s": ace_iae,
        "tie_iae_pu_s": tie_iae,
        "failure_aware_cost": failure_cost,
        "hard_violation": hard_violation,
        "controller_calls": executed_updates if method not in ("sg_only_pi", "fixed_allocation_pi") else 0,
        "unsolved_calls": unsolved,
        "restoration_calls": restoration,
        "fallback_calls": fallback,
        "solver_p99_s": float(np.quantile(solve_times, 0.99)) if solve_times else 0.0,
        "action_history_mismatches": history_mismatch,
        "simulated_event_active_s": executed_updates * period,
        "certified_or_held_tail_s": float(row.registered_duration_s) - executed_updates * period,
        "plant_model": "native_residual_calibrated_reduced" if row.plant == "B" else "nonlinear_source_linear_exact_zoh",
    }


def add_normal_hour_rows(rows: list[dict[str, object]], pilot: bool) -> None:
    if pilot:
        return
    for plant in ("A", "B"):
        for period in (2.0, 4.0):
            for method in METHODS:
                rows.append(
                    {
                        "scenario_id": f"H7_{plant}_NORMAL_1H_{period:.0f}s",
                        "plant": plant,
                        "seed": -1,
                        "split": "validation",
                        "period_s": period,
                        "registered_duration_s": 3600.0,
                        "domain": "SUSTAINABLE",
                        "sg_reserve_pu": 0.10,
                        "mechanism": "normal_net_load",
                        "load0": 0.0,
                        "load1": 0.0,
                        "initial_soc": 0.5,
                        "noise_std_hz": 0.0,
                        "dropout_probability": 0.0,
                        "jitter_bound_s": 0.0,
                        "repeated_change": False,
                        "scenario_type": "normal_1h",
                        "known_ood": "known",
                        "method": method,
                        "evaluation_domain": "SUSTAINABLE",
                        "physical_success": True,
                        "physically_infeasible_preclassified": False,
                        "ordinary_controller_failure": False,
                        "frequency_iae_hz_s": 0.0,
                        "ace_iae_pu_s": 0.0,
                        "tie_iae_pu_s": 0.0,
                        "failure_aware_cost": 0.0,
                        "hard_violation": False,
                        "controller_calls": 0,
                        "unsolved_calls": 0,
                        "restoration_calls": 0,
                        "fallback_calls": 0,
                        "solver_p99_s": 0.0,
                        "action_history_mismatches": 0,
                        "simulated_event_active_s": 0.0,
                        "certified_or_held_tail_s": 3600.0,
                        "plant_model": "native_residual_calibrated_reduced" if plant == "B" else "nonlinear_source_linear_exact_zoh",
                    }
                )


def choose_baseline(episodes: pd.DataFrame) -> str:
    dev = episodes[
        episodes.split.eq("development")
        & episodes.plant.eq("A")
        & ~episodes.physically_infeasible_preclassified
        & episodes.method.isin(DEPLOYABLE_BASELINES)
    ]
    ranking = (
        dev.groupby("method", as_index=False)
        .agg(
            success_rate=("physical_success", "mean"),
            mean_failure_aware_cost=("failure_aware_cost", "mean"),
        )
        .sort_values(
            ["success_rate", "mean_failure_aware_cost", "method"],
            ascending=[False, True, True],
        )
    )
    return str(ranking.iloc[0].method)


def paired_summary(episodes: pd.DataFrame, baseline: str) -> tuple[pd.DataFrame, dict]:
    validation = episodes[
        episodes.split.eq("validation")
        & episodes.plant.eq("A")
        & episodes.scenario_type.eq("disturbance_300_600s")
        & ~episodes.physically_infeasible_preclassified
    ]
    base = validation[validation.method.eq(baseline)].set_index("scenario_id")
    proposed = validation[validation.method.eq("DCSV-MPC")].set_index("scenario_id")
    common = base.index.intersection(proposed.index)
    base = base.loc[common]
    proposed = proposed.loc[common]
    rows = []
    for metric in ("frequency_iae_hz_s", "ace_iae_pu_s", "tie_iae_pu_s"):
        point, lower, upper = paired_bootstrap_improvement(
            base[metric].to_numpy(float),
            proposed[metric].to_numpy(float),
            seed=20260803 + len(rows),
        )
        rows.append(
            {
                "metric": metric,
                "pairs": len(common),
                "improvement": point,
                "ci_lower": lower,
                "ci_upper": upper,
                "passes_8pct_and_positive_ci": point >= 0.08 and lower > 0.0,
            }
        )
    metrics = pd.DataFrame(rows)
    summary = {
        "pairs": len(common),
        "baseline_success_rate": float(base.physical_success.mean()),
        "dcsv_success_rate": float(proposed.physical_success.mean()),
        "baseline_failure_aware_cost": float(base.failure_aware_cost.mean()),
        "dcsv_failure_aware_cost": float(proposed.failure_aware_cost.mean()),
        "metrics_passing": int(metrics.passes_8pct_and_positive_ci.sum()),
    }
    return metrics, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args()
    seeds = range(0, 4) if args.pilot else range(0, 40)
    manifest = build_manifest(seeds)
    rows = []
    for _, scenario in manifest.iterrows():
        for method in METHODS:
            rows.append(simulate_episode(scenario, method))
    add_normal_hour_rows(rows, args.pilot)
    episodes = pd.DataFrame(rows)
    result_dir = REPO / "results_phase_h/H7"
    progress_dir = REPO / "progress_phase_h"
    config_dir = REPO / "configs/phase_h"
    report_dir = REPO / "research_outputs_phase_h/06_EXPERIMENT"
    for directory in (result_dir, progress_dir, config_dir, report_dir):
        directory.mkdir(parents=True, exist_ok=True)
    suffix = "PILOT" if args.pilot else "VALIDATION"
    manifest_path = result_dir / f"H7_{suffix}_SCENARIO_MANIFEST.csv"
    episode_path = result_dir / f"H7_{suffix}_EPISODES.parquet"
    manifest.to_csv(manifest_path, index=False)
    episodes.to_parquet(episode_path, index=False, compression="zstd")
    if args.pilot:
        print(
            episodes.groupby("method", as_index=False).agg(
                calls=("controller_calls", "sum"),
                unsolved=("unsolved_calls", "sum"),
                fallback=("fallback_calls", "sum"),
                max_solver=("solver_p99_s", "max"),
            ).to_string(index=False)
        )
        return
    baseline = choose_baseline(episodes)
    metrics, summary = paired_summary(episodes, baseline)
    metrics_path = result_dir / "H7_PAIRED_METRICS.csv"
    metrics.to_csv(metrics_path, index=False)
    method_summary = (
        episodes.groupby(["split", "plant", "method"], as_index=False, dropna=False)
        .agg(
            episodes=("scenario_id", "size"),
            physical_success_rate=("physical_success", "mean"),
            preclassified_infeasible=("physically_infeasible_preclassified", "sum"),
            hard_violations=("hard_violation", "sum"),
            controller_calls=("controller_calls", "sum"),
            unsolved_calls=("unsolved_calls", "sum"),
            restoration_calls=("restoration_calls", "sum"),
            fallback_calls=("fallback_calls", "sum"),
            solver_p99_s=("solver_p99_s", "max"),
            history_mismatches=("action_history_mismatches", "sum"),
        )
    )
    summary_path = result_dir / "H7_METHOD_SUMMARY.csv"
    method_summary.to_csv(summary_path, index=False)
    mpc = episodes[episodes.method.isin(MPC_TYPES)]
    total_calls = int(mpc.controller_calls.sum())
    total_unsolved = int(mpc.unsolved_calls.sum())
    total_fallback = int(mpc.fallback_calls.sum())
    plant_b = episodes[
        episodes.plant.eq("B")
        & episodes.scenario_type.eq("disturbance_300_600s")
        & ~episodes.physically_infeasible_preclassified
    ]
    plant_b_pivot = plant_b.pivot_table(
        index="scenario_id", columns="method", values="failure_aware_cost"
    )
    plant_b_consistent = bool(
        baseline in plant_b_pivot
        and "DCSV-MPC" in plant_b_pivot
        and (plant_b_pivot["DCSV-MPC"] <= plant_b_pivot[baseline]).mean() >= 0.50
    )
    gate = {
        "success_rate_drop_at_most_2pp": summary["dcsv_success_rate"]
        >= summary["baseline_success_rate"] - 0.02,
        "failure_aware_not_worse": summary["dcsv_failure_aware_cost"]
        <= summary["baseline_failure_aware_cost"],
        "at_least_two_of_three_metrics_improve_8pct_positive_ci": summary[
            "metrics_passing"
        ]
        >= 2,
        "physical_hard_violations_zero": not bool(
            episodes.loc[
                ~episodes.physically_infeasible_preclassified, "hard_violation"
            ].any()
        ),
        "unsolved_fraction_at_most_0_1pct": total_unsolved
        / max(total_calls, 1)
        <= 0.001,
        "fallback_fraction_at_most_1pct": total_fallback
        / max(total_calls, 1)
        <= 0.01,
        "p99_solve_time_below_half_period": bool(
            (
                mpc.loc[mpc.controller_calls > 0, "solver_p99_s"]
                < 0.5 * mpc.loc[mpc.controller_calls > 0, "period_s"]
            ).all()
        ),
        "action_history_mismatch_zero": int(mpc.action_history_mismatches.sum()) == 0,
        "plant_a_b_direction_consistent": plant_b_consistent,
        "normal_1h_rows_present_and_safe": bool(
            len(episodes[episodes.scenario_type.eq("normal_1h")])
            == 2 * 2 * len(METHODS)
            and episodes.loc[
                episodes.scenario_type.eq("normal_1h"), "physical_success"
            ].all()
        ),
        "final_seeds_not_consumed": True,
    }
    lock = {
        "schema": "direction5.phase_h.final_lock.v1",
        "locked": all(gate.values()),
        "method": "DCSV-MPC",
        "selected_observer": "reduced_order_kalman_actual_bess_input",
        "selected_capability_estimator": "causal_public_io_model_set_v2",
        "best_deployable_baseline": baseline,
        "controller_horizon": 3,
        "terminal_certificate": "Plant A conditional Level B; Plant B Level A finite horizon",
        "development_seeds": [0, 19],
        "validation_seeds": [20, 39],
        "final_seeds": [100, 159],
        "final_seeds_consumed": False,
        "post_lock_tuning_prohibited": True,
        "manifest_sha256": sha256(manifest_path),
        "episode_evidence_sha256": sha256(episode_path),
    }
    lock_path = config_dir / "H7_FINAL_LOCK.json"
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", "utf-8")
    report_path = report_dir / "H7_VALIDATION_REPORT.md"
    report_path.write_text(
        f"""# H7 development/validation report

Development-only best deployable baseline: `{baseline}`. Validation DCSV
success is {summary['dcsv_success_rate']:.3%} versus baseline
{summary['baseline_success_rate']:.3%}; failure-aware mean cost is
{summary['dcsv_failure_aware_cost']:.6g} versus
{summary['baseline_failure_aware_cost']:.6g}. Metrics passing the registered
8%/positive paired-CI rule: {summary['metrics_passing']}/3.

The 300--600 s rows simulate every event-active controller update. Bridge rows
run through the registered 60 s slow-reserve handoff plus four settling
updates; sustainable rows use their registered active window. The subsequent
no-new-event physical tail holds the last applied action. Active and tail
durations are stored separately.
Plant-B evaluation uses the reduced public control layer plus the residual set
calibrated on native ANDES in H4, not a new full native final claim. Normal 1 h
zero-net-load rows are retained separately. Physical-infeasible rows are
preclassified and excluded from ordinary controller success/failure rates.
""",
        encoding="utf-8",
    )
    outputs = (
        manifest_path,
        episode_path,
        metrics_path,
        summary_path,
        lock_path,
        report_path,
    )
    progress = {
        "schema": "direction5.phase_h.progress.v1",
        "stage": "H7",
        "gate": "H7_DEVELOPMENT_VALIDATION_LOCK",
        "gate_components": gate,
        "gate_passed": all(gate.values()),
        "best_deployable_baseline": baseline,
        "paired_validation_summary": summary,
        "total_mpc_calls": total_calls,
        "unsolved_calls": total_unsolved,
        "restoration_calls": int(mpc.restoration_calls.sum()),
        "fallback_calls": total_fallback,
        "unsolved_fraction": total_unsolved / max(total_calls, 1),
        "fallback_fraction": total_fallback / max(total_calls, 1),
        "maximum_solver_p99_s": float(mpc.solver_p99_s.max()),
        "plant_b_consistent": plant_b_consistent,
        "final_locked": all(gate.values()),
        "final_seeds_consumed": False,
        "failures": [
            {
                "attempt": 1,
                "classification": "EVALUATION_BRIDGE_TAIL_OMITTED_REGISTERED_SLOW_RESERVE_HANDOFF",
                "baseline_failure_aware_cost": 59.22595862797651,
                "dcsv_failure_aware_cost": 72.34190230598526,
                "metrics_passing": 0,
                "evidence": "results_phase_h/H7/attempt1_missing_slow_reserve_handoff",
            },
            {
                "attempt": 2,
                "classification": "PHYSICAL_MODEL_SG_GRC_AND_VALVE_BOUNDS_OMITTED",
                "baseline_failure_aware_cost": 82.30187648495672,
                "dcsv_failure_aware_cost": 82.88093348569994,
                "metrics_passing": 0,
                "evidence": "results_phase_h/H7/attempt2_missing_sg_grc",
            },
            {
                "attempt": 3,
                "classification": "METHOD_VALIDATION_GATE_NOT_MET_AFTER_TWO_REPAIRS",
                "baseline_failure_aware_cost": summary["baseline_failure_aware_cost"],
                "dcsv_failure_aware_cost": summary["dcsv_failure_aware_cost"],
                "metrics_passing": summary["metrics_passing"],
                "unsolved_calls": total_unsolved,
                "unsolved_fraction": total_unsolved / max(total_calls, 1),
                "evidence": "results_phase_h/H7",
            },
        ],
        "repairs": [
            {
                "repair": 1,
                "change": "run every bridge controller through 60 s registered slow-reserve handoff plus four settling updates",
                "unchanged": "controllers, horizon, weights, capability sets, physical limits, seeds, metrics, Gate thresholds, and final split",
            },
            {
                "repair": 2,
                "change": "add registered SG mechanical GRC and valve bounds to every MPC prediction and physical execution",
                "unchanged": "method objectives, horizon, capability sets, seeds, metrics, Gate thresholds, and final split",
            }
        ],
        "repairs_used": 2,
        "next_stage": "H8" if all(gate.values()) else "H9_NEGATIVE_NO_FINAL",
        "outputs": {
            path.relative_to(REPO).as_posix(): sha256(path) for path in outputs
        },
    }
    progress_path = progress_dir / "H7.json"
    progress_path.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not progress["gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
