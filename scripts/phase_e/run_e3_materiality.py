"""Run E3 fair rolling baselines and current-capability Oracle materiality."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
from dataclasses import replace
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from direction1freq.controllers import ACEPIAntiWindup, design_stable_pi
from direction1freq.controllers.nominal_mpc import MPCDiagnostics, NominalModelMPC
from direction1freq.evaluation.oracles.current_capability_nmpc import (
    CurrentCapabilityNMPCOracle, OracleNMPCDiagnostics,
)
from direction1freq.controllers.rls_adaptive_mpc import RLSAdaptiveMPC
from direction1freq.controllers.robust_capability_mpc import RobustCapabilityMPC
from direction1freq.models.bess_capability_v2 import (
    BESSStateV2, CapabilityTruthV2,
)
from direction1freq.models.plant_a_v2 import (
    PlantAParametersV2, PlantAStateV2, PublicObservationV2, TwoAreaPlantAV2,
)
from direction1freq.models.plant_b_andes_v2 import AndesKundurPlantBV2


REPO = Path(__file__).resolve().parents[2]
RESULT = REPO / "results_phase_e" / "E3"
ORACLE_DOC = REPO / "research_outputs_phase_e" / "04_ORACLE"
SUMMARY_DOC = REPO / "research_outputs_phase_e" / "09_SUMMARY"
FIGURE = REPO / "figures_phase_e" / "E3"
METHODS = (
    "sg_only_pi", "fixed_allocation_pi", "nominal_mpc",
    "rls_adaptive_mpc", "robust_capability_mpc", "oracle_o2_nmpc",
)
MECHANISMS = ("headroom", "ramp", "delay", "energy", "availability")
TENSIONS = {"adequate": 0.10, "scarce": 0.05, "critical": 0.025}
LOAD_TIMINGS = ("no_load", "simultaneous", "before", "after", "continuous")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SharedCausalEstimator:
    """Identical causal state/load estimate supplied to every deployable method."""

    def __init__(self, period_s: float, nominal_frequency_hz: float = 50.0) -> None:
        self.period_s = float(period_s)
        self.nominal_frequency_hz = float(nominal_frequency_hz)
        self.previous_omega: np.ndarray | None = None
        self.load_estimate = np.zeros(2)

    def update(self, observation: PublicObservationV2) -> tuple[np.ndarray, np.ndarray]:
        omega = np.asarray(observation.frequency_deviation_hz) / self.nominal_frequency_hz
        derivative = np.zeros(2) if self.previous_omega is None else (
            omega - self.previous_omega
        ) / self.period_s
        inertia = np.array([5.0, 4.5])
        damping = np.ones(2)
        signed_tie = np.array([observation.tie_line_pu, -observation.tie_line_pu])
        raw_load = (
            np.asarray(observation.sg_mechanical_power_pu)
            + np.asarray(observation.bess_power_pu)
            - damping * omega - signed_tie - 2.0 * inertia * derivative
        )
        self.load_estimate = 0.65 * self.load_estimate + 0.35 * raw_load
        self.load_estimate = np.clip(self.load_estimate, -0.12, 0.12)
        self.previous_omega = omega.copy()
        mechanical = np.asarray(observation.sg_mechanical_power_pu)
        state = np.r_[
            omega, observation.tie_line_pu, mechanical, mechanical,
            np.asarray(observation.bess_power_pu),
        ]
        return state, self.load_estimate.copy()


class ControllerBank:
    def __init__(self, period_s: float, horizon: int = 4) -> None:
        proportional, integral, _ = design_stable_pi(TwoAreaPlantAV2(), period_s)
        self.sg_only = ACEPIAntiWindup(period_s, proportional, integral, sg_fraction=1.0)
        self.fixed = ACEPIAntiWindup(period_s, proportional, integral, sg_fraction=0.70)
        self.nominal = NominalModelMPC(period_s, horizon)
        self.rls = RLSAdaptiveMPC(period_s, horizon)
        self.robust = RobustCapabilityMPC(period_s, horizon)
        self.oracle = CurrentCapabilityNMPCOracle(period_s, horizon)
        self.fallback = ACEPIAntiWindup(period_s, proportional, integral, sg_fraction=1.0)

    def reset(self) -> None:
        for controller in (
            self.sg_only, self.fixed, self.nominal, self.rls,
            self.robust, self.oracle, self.fallback,
        ):
            controller.reset()


def build_manifest(pilot: bool) -> pd.DataFrame:
    rng = np.random.default_rng(20260731)
    rows: list[dict[str, Any]] = []
    mechanisms = MECHANISMS[:2] if pilot else MECHANISMS
    tensions = tuple(TENSIONS)[:2] if pilot else tuple(TENSIONS)
    seeds = list(range(5)) if pilot else list(range(20))
    for mechanism in mechanisms:
        for tension in tensions:
            count = len(seeds)
            timings = (
                np.asarray(["simultaneous"] * count, dtype=object)
                if pilot else np.resize(np.asarray(LOAD_TIMINGS, dtype=object), count)
            )
            areas = np.resize(np.array([0, 1]), count)
            signs = np.resize(np.array([1.0, -1.0]), count)
            magnitudes = np.resize(np.array([0.05, 0.06, 0.07, 0.08]), count)
            rng.shuffle(timings); rng.shuffle(areas); rng.shuffle(signs); rng.shuffle(magnitudes)
            phases = rng.uniform(0.0, 2.0 * np.pi, size=(count, 4))
            for index, seed in enumerate(seeds):
                rows.append({
                    "scenario_id": f"A_{mechanism}_{tension}_{seed:02d}",
                    "plant": "A", "load_seed": seed, "solver_seed": 10_000 + seed,
                    "mechanism": mechanism, "sg_tension": tension,
                    "sg_reserve_pu": TENSIONS[tension], "sfr_period_s": 4.0,
                    "load_timing": str(timings[index]), "disturbance_area": int(areas[index]),
                    "disturbance_sign": float(signs[index]), "disturbance_magnitude_pu": float(magnitudes[index]),
                    "capability_change_time_s": 20.0, "measurement_noise_std_hz": 0.0,
                    "communication_jitter_s": 0.0, "dropout_probability": 0.0,
                    "initial_soc_1": 0.5, "initial_soc_2": 0.5, "known_ood": "development_known",
                    **{f"phase_{j}": float(phases[index, j]) for j in range(4)},
                })
    if not pilot:
        # 2 s sensitivity: 20 explicitly balanced seeds per mechanism, with SG
        # tension independently shuffled across the same seed set.
        for mechanism in MECHANISMS:
            count = 20
            timings = np.resize(np.asarray(LOAD_TIMINGS, dtype=object), count)
            tensions_array = np.resize(np.asarray(tuple(TENSIONS), dtype=object), count)
            areas = np.resize(np.array([0, 1]), count)
            signs = np.resize(np.array([1.0, -1.0]), count)
            magnitudes = np.resize(np.array([0.05, 0.06, 0.07, 0.08]), count)
            for values in (timings, tensions_array, areas, signs, magnitudes):
                rng.shuffle(values)
            phases = rng.uniform(0.0, 2.0 * np.pi, size=(count, 4))
            for index, seed in enumerate(range(20)):
                tension = str(tensions_array[index])
                rows.append({
                    "scenario_id": f"A2_{mechanism}_{tension}_{seed:02d}",
                    "plant": "A", "load_seed": seed, "solver_seed": 20_000 + seed,
                    "mechanism": mechanism, "sg_tension": tension,
                    "sg_reserve_pu": TENSIONS[tension], "sfr_period_s": 2.0,
                    "load_timing": str(timings[index]), "disturbance_area": int(areas[index]),
                    "disturbance_sign": float(signs[index]), "disturbance_magnitude_pu": float(magnitudes[index]),
                    "capability_change_time_s": 20.0, "measurement_noise_std_hz": 0.0,
                    "communication_jitter_s": 0.0, "dropout_probability": 0.0,
                    "initial_soc_1": 0.5, "initial_soc_2": 0.5, "known_ood": "development_known_2s_sensitivity",
                    **{f"phase_{j}": float(phases[index, j]) for j in range(4)},
                })
    return pd.DataFrame(rows)


def capability_at(row: pd.Series | dict, time_s: float) -> CapabilityTruthV2:
    if time_s < float(row["capability_change_time_s"]):
        return CapabilityTruthV2()
    mechanism = str(row["mechanism"])
    if mechanism == "headroom":
        return CapabilityTruthV2(
            upper_headroom_fraction=(0.35, 0.35), lower_headroom_fraction=(0.35, 0.35)
        )
    if mechanism == "ramp":
        return CapabilityTruthV2(ramp_up_fraction=(0.15, 0.15), ramp_down_fraction=(0.15, 0.15))
    if mechanism == "delay":
        return CapabilityTruthV2(delay_s=(1.6, 1.6))
    if mechanism == "energy":
        return CapabilityTruthV2(accessible_energy_fraction=(0.04, 0.04))
    if mechanism == "availability":
        return CapabilityTruthV2(availability=(0.30, 0.30))
    raise ValueError(mechanism)


def load_at(row: pd.Series | dict, time_s: float) -> np.ndarray:
    timing = str(row["load_timing"])
    if timing == "no_load":
        return np.zeros(2)
    phases = np.array([row[f"phase_{j}"] for j in range(4)], dtype=float)
    continuous = 0.0015 * np.array([
        0.6 * np.sin(0.17 * time_s + phases[0]) + 0.4 * np.sin(0.043 * time_s + phases[1]),
        0.6 * np.sin(0.13 * time_s + phases[2]) + 0.4 * np.sin(0.037 * time_s + phases[3]),
    ])
    if timing == "continuous":
        return 2.5 * continuous
    load_time = {
        "simultaneous": float(row["capability_change_time_s"]),
        "before": float(row["capability_change_time_s"]) - 8.0,
        "after": float(row["capability_change_time_s"]) + 8.0,
    }[timing]
    step = np.zeros(2)
    if time_s >= load_time:
        step[int(row["disturbance_area"])] = (
            float(row["disturbance_sign"]) * float(row["disturbance_magnitude_pu"])
        )
    return step + 0.25 * continuous


def noisy_public_observation(observation: PublicObservationV2, noise_hz: np.ndarray) -> PublicObservationV2:
    frequency = observation.frequency_deviation_hz + noise_hz
    omega = frequency / 50.0
    bias = np.array([21.0, 21.0])
    ace = np.array([
        bias[0] * omega[0] + observation.tie_line_pu,
        bias[1] * omega[1] - observation.tie_line_pu,
    ])
    return replace(observation, frequency_deviation_hz=frequency, ace_pu=ace)


def _pi_diagnostic(action: np.ndarray) -> dict[str, Any]:
    return {
        "solved": True, "solver_status": "not_applicable_pi", "primal_residual": 0.0,
        "dual_residual": 0.0, "solve_time_s": 0.0, "iterations": 0,
        "fallback_reason": "", "first_action_pu": action,
    }


def simulate_plant_a_episode(
    row: pd.Series,
    method: str,
    bank: ControllerBank,
    duration_s: float = 96.0,
    dt_s: float = 0.05,
) -> tuple[dict[str, Any], pd.DataFrame]:
    reserve = float(row["sg_reserve_pu"])
    base_parameters = PlantAParametersV2()
    parameters = replace(
        base_parameters,
        sg_power_lower_pu=(-reserve, -reserve), sg_power_upper_pu=(reserve, reserve),
        valve_lower_pu=(-1.2 * reserve, -1.2 * reserve),
        valve_upper_pu=(1.2 * reserve, 1.2 * reserve),
    )
    plant = TwoAreaPlantAV2(parameters, dt_s)
    state = plant.equilibrium((float(row["initial_soc_1"]), float(row["initial_soc_2"])))
    bank.reset()
    estimator = SharedCausalEstimator(float(row["sfr_period_s"]))
    command = np.zeros(4)
    update_steps = int(round(float(row["sfr_period_s"]) / dt_s))
    rng = np.random.default_rng(int(row["load_seed"]) + 500_000)
    noise_at_update = rng.normal(0.0, float(row["measurement_noise_std_hz"]), size=(1000, 2))
    solver_records: list[dict[str, Any]] = []
    control_trace: list[dict[str, Any]] = []
    frequency_iae = ace_iae = tie_iae = 0.0
    frequency_square = 0.0
    sg_mileage = bess_mileage = 0.0
    previous_pm = state.mechanical_power_pu.copy()
    previous_pb = state.bess.power_pu.copy()
    maximum_frequency = maximum_rocof = 0.0
    previous_frequency = plant.parameters.nominal_frequency_hz * state.omega_pu
    cumulative_cost = 0.0
    code_failure = ""
    steps = int(round(duration_s / dt_s))
    update_index = 0
    for step in range(steps + 1):
        time_s = step * dt_s
        observation = plant.public_observation(time_s, state, command)
        if step % update_steps == 0:
            public = noisy_public_observation(observation, noise_at_update[update_index])
            estimate, load_estimate = estimator.update(public)
            diagnostic: Any
            if method == "sg_only_pi":
                action, _ = bank.sg_only.update(public)
                action[[0, 2]] = np.clip(action[[0, 2]], -reserve, reserve)
                action[[1, 3]] = 0.0
                diagnostic = _pi_diagnostic(action)
            elif method == "fixed_allocation_pi":
                action, _ = bank.fixed.update(public)
                action[[0, 2]] = np.clip(action[[0, 2]], -reserve, reserve)
                diagnostic = _pi_diagnostic(action)
            elif method == "nominal_mpc":
                action, diagnostic = bank.nominal.update(public, estimate, load_estimate, reserve)
            elif method == "rls_adaptive_mpc":
                action, diagnostic = bank.rls.update(public, estimate, load_estimate, reserve)
            elif method == "robust_capability_mpc":
                action, diagnostic = bank.robust.update(public, estimate, load_estimate, reserve)
            elif method == "oracle_o2_nmpc":
                action, diagnostic = bank.oracle.solve_evaluation_only(
                    state, capability_at(row, time_s), load_estimate, reserve
                )
            else:
                raise ValueError(method)
            solved = bool(diagnostic["solved"] if isinstance(diagnostic, dict) else diagnostic.solved)
            fallback_reason = str(
                diagnostic["fallback_reason"] if isinstance(diagnostic, dict) else diagnostic.fallback_reason
            )
            if not solved:
                fallback_action, _ = bank.fallback.update(public)
                fallback_action[[0, 2]] = np.clip(fallback_action[[0, 2]], -reserve, reserve)
                fallback_action[[1, 3]] = 0.0
                action = fallback_action
                fallback_reason = fallback_reason or "safe_sg_pi_fallback"
            command = np.asarray(action, dtype=float)
            if isinstance(diagnostic, dict):
                dual_or_first_order = diagnostic["dual_residual"]
            elif isinstance(diagnostic, OracleNMPCDiagnostics):
                dual_or_first_order = diagnostic.first_order_proxy
            else:
                dual_or_first_order = diagnostic.dual_residual
            solver_records.append({
                "time_s": time_s,
                "solved": solved,
                "status": diagnostic["solver_status"] if isinstance(diagnostic, dict) else diagnostic.solver_status,
                "primal_residual": diagnostic["primal_residual"] if isinstance(diagnostic, dict) else diagnostic.primal_residual,
                "dual_or_first_order": dual_or_first_order,
                "solve_time_s": diagnostic["solve_time_s"] if isinstance(diagnostic, dict) else diagnostic.solve_time_s,
                "iterations": diagnostic["iterations"] if isinstance(diagnostic, dict) else diagnostic.iterations,
                "fallback_reason": fallback_reason,
            })
            control_trace.append({
                "scenario_id": row["scenario_id"], "method": method, "time_s": time_s,
                "df1_hz": observation.frequency_deviation_hz[0], "df2_hz": observation.frequency_deviation_hz[1],
                "ace1_pu": observation.ace_pu[0], "ace2_pu": observation.ace_pu[1],
                "tie_pu": observation.tie_line_pu, "cumulative_control_loss_cost": cumulative_cost,
                "cmd_sg1": command[0], "cmd_b1": command[1], "cmd_sg2": command[2], "cmd_b2": command[3],
                "pb1": state.bess.power_pu[0], "pb2": state.bess.power_pu[1],
                "e1_mwh": state.bess.energy_mwh[0], "e2_mwh": state.bess.energy_mwh[1],
            })
            update_index += 1
        frequency = observation.frequency_deviation_hz
        ace = observation.ace_pu
        rocof = (frequency - previous_frequency) / dt_s if step else np.zeros(2)
        maximum_frequency = max(maximum_frequency, float(np.max(np.abs(frequency))))
        maximum_rocof = max(maximum_rocof, float(np.max(np.abs(rocof))))
        frequency_iae += float(np.mean(np.abs(frequency))) * dt_s
        ace_iae += float(np.mean(np.abs(ace))) * dt_s
        tie_iae += abs(observation.tie_line_pu) * dt_s
        frequency_square += float(np.mean(frequency**2)) * dt_s
        sg_mileage += float(np.sum(np.abs(state.mechanical_power_pu - previous_pm)))
        bess_mileage += float(np.sum(np.abs(state.bess.power_pu - previous_pb)))
        instantaneous = (
            20.0 * float(np.mean(frequency**2)) + 50.0 * float(np.mean(ace**2))
            + 20.0 * observation.tie_line_pu**2
        )
        cumulative_cost += instantaneous * dt_s
        previous_frequency = frequency.copy()
        previous_pm = state.mechanical_power_pu.copy()
        previous_pb = state.bess.power_pu.copy()
        if step == steps:
            break
        try:
            state, _ = plant.step(
                state, command, load_at(row, time_s), capability_at(row, time_s)
            )
        except Exception as error:
            code_failure = f"{type(error).__name__}:{error}"
            break

    trace = pd.DataFrame(control_trace)
    terminal = trace[trace["time_s"] >= max(0.0, trace["time_s"].max() - 20.0)]
    terminal_frequency = float(terminal[["df1_hz", "df2_hz"]].abs().to_numpy().mean())
    terminal_ace = float(terminal[["ace1_pu", "ace2_pu"]].abs().to_numpy().mean())
    terminal_tie = float(terminal["tie_pu"].abs().mean())
    solver_frame = pd.DataFrame(solver_records)
    solver_success = float(solver_frame["solved"].mean())
    fallback_count = int((solver_frame["fallback_reason"] != "").sum())
    physical_success = bool(
        not code_failure and maximum_frequency <= 0.80 and maximum_rocof <= 1.0
        and terminal_frequency <= 0.05 and terminal_ace <= 0.03 and terminal_tie <= 0.03
        and (solver_success >= 0.95 or fallback_count > 0)
    )
    if code_failure:
        failure_class = "code_failure"
    elif maximum_frequency > 0.80 or maximum_rocof > 1.0:
        failure_class = "physical_frequency_failure"
    elif terminal_ace > 0.03 or terminal_tie > 0.03 or terminal_frequency > 0.05:
        failure_class = "physical_ace_tie_failure"
    elif solver_success < 0.95 and fallback_count == 0:
        failure_class = "solver_infeasible"
    else:
        failure_class = "none"
    residuals = solver_frame["primal_residual"].to_numpy(dtype=float)
    solver_residual_p99 = (
        float("inf") if not np.isfinite(residuals).all()
        else float(np.quantile(residuals, 0.99))
    )
    episode = {
        **{column: row[column] for column in row.index if not column.startswith("phase_")},
        "method": method, "physical_success": physical_success, "failure_class": failure_class,
        "code_failure_detail": code_failure, "max_abs_frequency_hz": maximum_frequency,
        "max_abs_rocof_hz_s": maximum_rocof, "terminal_frequency_mean_hz": terminal_frequency,
        "terminal_ace_mean_pu": terminal_ace, "terminal_tie_mean_pu": terminal_tie,
        "frequency_iae_hz_s": frequency_iae, "frequency_rms_hz": np.sqrt(frequency_square / duration_s),
        "ace_iae_pu_s": ace_iae, "tie_iae_pu_s": tie_iae,
        "sg_mileage_pu": sg_mileage, "bess_mileage_pu": bess_mileage,
        "final_energy_1_mwh": float(state.bess.energy_mwh[0]),
        "final_energy_2_mwh": float(state.bess.energy_mwh[1]),
        "solver_success_fraction": solver_success,
        "solver_residual_p99": solver_residual_p99,
        "solver_time_median_s": float(solver_frame["solve_time_s"].median()),
        "solver_time_p99_s": float(solver_frame["solve_time_s"].quantile(0.99)),
        "fallback_count": fallback_count,
        "independent_rollout_objective": cumulative_cost,
    }
    return episode, trace


def _simulate_manifest_chunk(
    records: list[dict[str, Any]], horizon: int,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    """Isolated deterministic worker for an assigned manifest chunk."""

    periods = sorted({float(record["sfr_period_s"]) for record in records})
    banks = {period: ControllerBank(period, horizon=horizon) for period in periods}
    episodes: list[dict[str, Any]] = []
    traces: list[pd.DataFrame] = []
    for record in records:
        row = pd.Series(record)
        bank = banks[float(row["sfr_period_s"])]
        for method in METHODS:
            episode, trace = simulate_plant_a_episode(row, method, bank)
            episodes.append(episode)
            traces.append(trace)
    return episodes, pd.concat(traces, ignore_index=True)


def paired_bootstrap_improvement(
    pair: pd.DataFrame, baseline_column: str, oracle_column: str, samples: int = 1000,
) -> tuple[float, float, float]:
    baseline = pair[baseline_column].to_numpy(float)
    oracle = pair[oracle_column].to_numpy(float)
    point = 1.0 - float(np.mean(oracle)) / max(float(np.mean(baseline)), 1e-12)
    rng = np.random.default_rng(20260731)
    values = []
    for _ in range(samples):
        indices = rng.integers(0, len(pair), len(pair))
        values.append(1.0 - np.mean(oracle[indices]) / max(np.mean(baseline[indices]), 1e-12))
    return point, float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))


def select_best_baseline(episodes: pd.DataFrame) -> str:
    candidates = episodes[episodes["method"] != "oracle_o2_nmpc"]
    scores = []
    for method, frame in candidates.groupby("method"):
        success = float(frame["physical_success"].mean())
        cost = float(frame["independent_rollout_objective"].mean())
        scores.append((method, success, cost))
    scores.sort(key=lambda item: (-item[1], item[2], item[0]))
    return scores[0][0]


def materiality_summary(episodes: pd.DataFrame, best_baseline: str) -> pd.DataFrame:
    main = episodes[episodes["sfr_period_s"] == 4.0]
    records = []
    for (mechanism, tension), frame in main.groupby(["mechanism", "sg_tension"]):
        baseline = frame[frame["method"] == best_baseline].set_index("scenario_id")
        oracle = frame[frame["method"] == "oracle_o2_nmpc"].set_index("scenario_id")
        common = baseline.index.intersection(oracle.index)
        baseline = baseline.loc[common]
        oracle = oracle.loc[common]
        both_success = baseline["physical_success"] & oracle["physical_success"]
        joined = pd.DataFrame(index=common)
        for metric in ("frequency_iae_hz_s", "ace_iae_pu_s", "tie_iae_pu_s"):
            joined[f"b_{metric}"] = baseline[metric]
            joined[f"o_{metric}"] = oracle[metric]
        joined = joined[both_success]
        improvements: dict[str, tuple[float, float, float]] = {}
        for metric in ("frequency_iae_hz_s", "ace_iae_pu_s", "tie_iae_pu_s"):
            improvements[metric] = paired_bootstrap_improvement(
                joined, f"b_{metric}", f"o_{metric}"
            ) if len(joined) >= 2 else (float("nan"), float("nan"), float("nan"))
        success_difference = float(oracle["physical_success"].mean() - baseline["physical_success"].mean())
        continuous_passes = sum(
            np.isfinite(value[0]) and value[0] >= 0.10 and value[1] > 0.0
            for value in improvements.values()
        )
        gate_cell = success_difference >= 0.10 or continuous_passes >= 2
        records.append({
            "mechanism": mechanism, "sg_tension": tension, "episodes": len(common),
            "baseline_success_rate": float(baseline["physical_success"].mean()),
            "oracle_success_rate": float(oracle["physical_success"].mean()),
            "success_rate_difference": success_difference,
            "frequency_iae_improvement": improvements["frequency_iae_hz_s"][0],
            "frequency_iae_ci_low": improvements["frequency_iae_hz_s"][1],
            "frequency_iae_ci_high": improvements["frequency_iae_hz_s"][2],
            "ace_iae_improvement": improvements["ace_iae_pu_s"][0],
            "ace_iae_ci_low": improvements["ace_iae_pu_s"][1],
            "ace_iae_ci_high": improvements["ace_iae_pu_s"][2],
            "tie_iae_improvement": improvements["tie_iae_pu_s"][0],
            "tie_iae_ci_low": improvements["tie_iae_pu_s"][1],
            "tie_iae_ci_high": improvements["tie_iae_pu_s"][2],
            "continuous_metrics_passing": continuous_passes,
            "cell_materiality_pass": gate_cell,
        })
    return pd.DataFrame(records)


def oracle_qualification(bank: ControllerBank) -> pd.DataFrame:
    plant = TwoAreaPlantAV2(dt_s=0.05)
    state = plant.equilibrium()
    truth = CapabilityTruthV2(
        upper_headroom_fraction=(0.4, 0.4), lower_headroom_fraction=(0.4, 0.4)
    )
    for _ in range(20):
        state, _ = plant.step(state, np.zeros(4), np.array([0.06, 0.0]), truth)
    rows = []
    objectives = []
    for variant in (-1, 0, 1):
        action, diagnostic = bank.oracle.solve_independent_nonlinear_qualification(
            state, truth, np.array([0.06, 0.0]), 0.05, initial_guess_variant=variant
        )
        objectives.append(diagnostic.objective)
        rows.append({
            "check": f"independent_slsqp_initial_guess_{variant}",
            "passed": diagnostic.solved, "objective": diagnostic.objective,
            "primal_residual": diagnostic.primal_residual,
            "solve_time_s": diagnostic.solve_time_s, "iterations": diagnostic.iterations,
            "first_action_norm": float(np.linalg.norm(action)),
            "transcription": diagnostic.transcription,
        })
    objective_spread = (max(objectives) - min(objectives)) / max(abs(min(objectives)), 1e-12)
    rows.append({
        "check": "multi_initial_objective_spread", "passed": objective_spread <= 0.02,
        "objective": objective_spread, "primal_residual": 0.0, "solve_time_s": 0.0,
        "iterations": 0, "first_action_norm": float("nan"), "transcription": "qualification",
    })
    return pd.DataFrame(rows)


def run_native_direction_check(
    best_baseline: str, horizon: int, pilot: bool,
) -> pd.DataFrame:
    records = []
    mechanisms = MECHANISMS[:1] if pilot else MECHANISMS
    seeds = [0] if pilot else list(range(5))
    for mechanism in mechanisms:
        for seed in seeds:
            tension = "scarce" if seed < 3 else "critical"
            row = {
                "mechanism": mechanism, "capability_change_time_s": 4.0,
                "sg_reserve_pu": TENSIONS[tension],
            }
            load_magnitude = 0.03 + 0.005 * seed
            for method in (best_baseline, "oracle_o2_nmpc"):
                bank = ControllerBank(4.0, horizon)
                bank.reset()
                estimator = SharedCausalEstimator(4.0, nominal_frequency_hz=60.0)
                synthetic_energy = np.array([25.0, 25.0])

                def policy(observation: PublicObservationV2) -> np.ndarray:
                    nonlocal synthetic_energy
                    estimate, load_estimate = estimator.update(observation)
                    if method == "oracle_o2_nmpc":
                        power = np.asarray(observation.bess_power_pu)
                        parameters = bank.oracle.plant.parameters.bess
                        synthetic_energy = synthetic_energy + 4.0 * np.where(
                            power >= 0.0,
                            -power * parameters.system_base_mva / parameters.eta_discharge / 3600.0,
                            -power * parameters.system_base_mva * parameters.eta_charge / 3600.0,
                        )
                        bess_state = BESSStateV2(
                            power.copy(), synthetic_energy.copy(),
                            BESSStateV2.equilibrium(parameters, 0.05).delay,
                        )
                        omega = observation.frequency_deviation_hz / 60.0
                        synthetic = PlantAStateV2(
                            omega, observation.tie_line_pu,
                            observation.sg_mechanical_power_pu.copy(),
                            observation.sg_mechanical_power_pu.copy(), bess_state,
                        )
                        action, diagnostic = bank.oracle.solve_evaluation_only(
                            synthetic, capability_at(row, observation.time_s),
                            load_estimate, float(row["sg_reserve_pu"]),
                        )
                    elif method == "robust_capability_mpc":
                        action, diagnostic = bank.robust.update(
                            observation, estimate, load_estimate, float(row["sg_reserve_pu"])
                        )
                    elif method == "nominal_mpc":
                        action, diagnostic = bank.nominal.update(
                            observation, estimate, load_estimate, float(row["sg_reserve_pu"])
                        )
                    elif method == "rls_adaptive_mpc":
                        action, diagnostic = bank.rls.update(
                            observation, estimate, load_estimate, float(row["sg_reserve_pu"])
                        )
                    elif method == "sg_only_pi":
                        action, _ = bank.sg_only.update(observation)
                        action[[0, 2]] = np.clip(
                            action[[0, 2]], -float(row["sg_reserve_pu"]), float(row["sg_reserve_pu"])
                        )
                        action[[1, 3]] = 0.0
                        return action
                    else:
                        action, _ = bank.fixed.update(observation)
                        action[[0, 2]] = np.clip(
                            action[[0, 2]], -float(row["sg_reserve_pu"]), float(row["sg_reserve_pu"])
                        )
                        return action
                    if not diagnostic.solved:
                        action, _ = bank.fallback.update(observation)
                        action[[0, 2]] = np.clip(
                            action[[0, 2]], -float(row["sg_reserve_pu"]), float(row["sg_reserve_pu"])
                        )
                        action[[1, 3]] = 0.0
                    return action

                native = AndesKundurPlantBV2(dt_s=0.05)
                trace = native.run_causal_closed_loop(
                    duration_s=24.0, control_period_s=4.0,
                    load_profile=lambda time_s, magnitude=load_magnitude: np.array([
                        magnitude if time_s >= 8.0 else 0.0, 0.0
                    ]),
                    policy=policy,
                    capability_profile=lambda time_s, scenario=row: capability_at(scenario, time_s),
                )
                dt = np.diff(trace.time_s, prepend=trace.time_s[0])
                records.append({
                    "plant": "B", "mechanism": mechanism, "seed": seed,
                    "sg_tension": tension, "method": method, "converged": trace.converged,
                    "frequency_iae_hz_s": float(np.sum(np.mean(np.abs(trace.frequency_deviation_hz), axis=1) * dt)),
                    "ace_iae_pu_s": float(np.sum(np.mean(np.abs(trace.ace_pu), axis=1) * dt)),
                    "tie_iae_pu_s": float(np.sum(np.abs(trace.tie_line_pu) * dt)),
                    "max_abs_frequency_hz": float(np.max(np.abs(trace.frequency_deviation_hz))),
                    "terminal_abs_frequency_hz": float(np.max(np.abs(trace.frequency_deviation_hz[-1]))),
                    "balance_p99_pu": trace.algebraic_power_balance_p99_pu,
                })
    return pd.DataFrame(records)


def write_documents(
    episodes: pd.DataFrame, summary: pd.DataFrame, best_baseline: str,
    qualification: pd.DataFrame, native: pd.DataFrame, gate_passed: bool,
) -> list[Path]:
    ORACLE_DOC.mkdir(parents=True, exist_ok=True)
    SUMMARY_DOC.mkdir(parents=True, exist_ok=True)
    formulation = ORACLE_DOC / "ORACLE_FORMULATION.md"
    formulation.write_text("""# O2 current-capability rolling NMPC

O2 is evaluation-only.  At each 2/4 s instant it receives the current physical state and current external capability truth, assumes that capability is held over the horizon, and receives the same causal load estimate used by deployable baselines.  It never receives future load, future switching, or future communication outcomes.

The online real-time iteration contains explicit state and action decision sequences, multiple-shooting dynamics, input/state/terminal constraints, current headroom/ramp/delay/energy/availability bounds, and a terminal SG-backup neighborhood.  The piecewise charge/discharge energy law is converted to a sustainable horizon power bound at the current energy.  One convex SQP subproblem is solved with OSQP, warm-started, and only its first action is executed.  An independent nonlinear SLSQP multiple-shooting transcription with explicit energy nodes is used for multi-start qualification; it is not substituted for episode failures.

Nominal, RLS-adaptive, and worst-case controllers solve the same rolling finite-horizon structure with their deployable information.  SG-only and fixed-allocation PI are named PI, not MPC.  Oracle performance is an upper bound on current-capability information, not exact global optimality.
""", encoding="utf-8")
    boundary = ORACLE_DOC / "INFORMATION_FAIRNESS_AUDIT.md"
    boundary.write_text("""# E3 information fairness audit

All deployable methods receive `PublicObservationV2`, the same causal state/load estimator, the same update period, declared SG reserve, and no capability truth.  Nominal MPC retains nameplate capability; RLS uses only past command/POI-power pairs; robust MPC uses the frozen global worst-case set.  Only O2 receives current truth and true current physical state, through a method whose class and output are explicitly marked evaluation-only.  No controller receives future loads, events, modes, or final seeds.
""", encoding="utf-8")
    report = SUMMARY_DOC / "E3_MATERIALITY_REPORT.md"
    passed_cells = summary[summary["cell_materiality_pass"]]
    oracle_residuals = episodes.loc[
        episodes.method == "oracle_o2_nmpc", "solver_residual_p99"
    ].to_numpy(dtype=float)
    oracle_residual_p99 = float(np.quantile(
        oracle_residuals[np.isfinite(oracle_residuals)], 0.99
    ))
    nonfinite_residual_episodes = int((~np.isfinite(oracle_residuals)).sum())
    report.write_text(f"""# E3 materiality report

Best deployable baseline (success-first, then mean matched cost): **{best_baseline}**.  O2 mean update solver success is {episodes.loc[episodes.method == 'oracle_o2_nmpc', 'solver_success_fraction'].mean():.2%}; successful-solve residual P99 is {oracle_residual_p99:.3e}.  {nonfinite_residual_episodes} episodes contain at least one failed solve; they remain in the episode table and are assessed by the separate solver-success/fallback Gate rather than being silently removed.  {len(passed_cells)} mechanism/tension cells satisfy the preregistered materiality rule.  Plant-B paired direction is {'consistent' if gate_passed else 'not sufficient for a positive Gate'}.

G3 result: **{'PASS' if gate_passed else 'FAIL — PROBLEM_NOT_MATERIAL'}**.  Continuous improvements are ratios of aggregate paired means, with seed-cluster bootstrap intervals; no mean of episode-wise relative ratios is used.  Failures, fallback episodes, and no-load negative controls remain in the episode table.
""", encoding="utf-8")
    return [formulation, boundary, report]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    suffix = "pilot" if args.pilot else "full"
    output_dir = RESULT / suffix
    output_dir.mkdir(parents=True, exist_ok=True)
    FIGURE.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(args.pilot)
    manifest.to_csv(output_dir / "E3_EXPERIMENT_MANIFEST.csv", index=False)
    horizon = 3 if args.pilot else 4
    episodes: list[dict[str, Any]] = []
    traces: list[pd.DataFrame] = []
    records = manifest.to_dict(orient="records")
    worker_count = min(args.workers, len(records))
    if worker_count == 1:
        result_chunks = [_simulate_manifest_chunk(records, horizon)]
    else:
        chunks = [records[index::worker_count] for index in range(worker_count)]
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            result_chunks = list(executor.map(
                _simulate_manifest_chunk, chunks, [horizon] * worker_count
            ))
    for episode_chunk, trace_chunk in result_chunks:
        episodes.extend(episode_chunk)
        traces.append(trace_chunk)
    episode_frame = pd.DataFrame(episodes)
    trace_frame = pd.concat(traces, ignore_index=True)
    episode_frame = episode_frame.sort_values(["scenario_id", "method"]).reset_index(drop=True)
    trace_frame = trace_frame.sort_values(["scenario_id", "method", "time_s"]).reset_index(drop=True)
    banks = {
        period: ControllerBank(period, horizon=horizon)
        for period in sorted(manifest["sfr_period_s"].unique())
    }
    episode_frame.to_parquet(output_dir / "E3_MATERIALITY_EPISODES.parquet", index=False)
    trace_frame.to_parquet(output_dir / "E3_CONTROL_RATE_TRACES.parquet", index=False)
    best_baseline = select_best_baseline(episode_frame)
    summary = materiality_summary(episode_frame, best_baseline)
    summary.to_csv(output_dir / "E3_MATERIALITY_SUMMARY.csv", index=False)
    qualification = oracle_qualification(banks[4.0])
    qualification.to_csv(output_dir / "ORACLE_QUALIFICATION.csv", index=False)
    native = run_native_direction_check(best_baseline, horizon, args.pilot)
    native.to_parquet(output_dir / "PLANT_B_DIRECTION_CHECK.parquet", index=False)

    oracle_rows = episode_frame[episode_frame["method"] == "oracle_o2_nmpc"]
    oracle_success = float((oracle_rows["solver_success_fraction"] >= 0.95).mean())
    oracle_residuals = oracle_rows["solver_residual_p99"].to_numpy(dtype=float)
    finite_oracle_residuals = oracle_residuals[np.isfinite(oracle_residuals)]
    oracle_residual_p99 = (
        float(np.quantile(finite_oracle_residuals, 0.99))
        if len(finite_oracle_residuals) else float("inf")
    )
    qualified = bool(
        oracle_success >= 0.95 and oracle_residual_p99 <= 1e-5
        and bool(qualification["passed"].all())
    )
    passing = summary[summary["cell_materiality_pass"]]
    mechanisms_passing = int(passing["mechanism"].nunique())
    tensions_passing = int(passing["sg_tension"].nunique())
    native_pivot = native.pivot_table(
        index=["mechanism", "seed"], columns="method", values="frequency_iae_hz_s"
    )
    native_direction = bool(
        best_baseline in native_pivot and "oracle_o2_nmpc" in native_pivot
        and float((native_pivot["oracle_o2_nmpc"] <= native_pivot[best_baseline]).mean()) >= 0.60
    )
    materiality = bool(qualified and mechanisms_passing >= 2 and tensions_passing >= 2 and native_direction)
    gate = {
        "oracle_solver_qualification": qualified,
        "at_least_two_mechanisms": mechanisms_passing >= 2,
        "at_least_two_sg_tensions": tensions_passing >= 2,
        "plant_a_b_direction_consistent": native_direction,
    }

    # Matched counterfactual Tcrit uses a development-frozen Jmat and does not
    # replace the materiality Gate.
    j_mat = 0.02
    tcrit_records = []
    for scenario_id in manifest["scenario_id"]:
        baseline = trace_frame[
            (trace_frame.scenario_id == scenario_id) & (trace_frame.method == best_baseline)
        ].set_index("time_s")
        oracle = trace_frame[
            (trace_frame.scenario_id == scenario_id) & (trace_frame.method == "oracle_o2_nmpc")
        ].set_index("time_s")
        common = baseline.index.intersection(oracle.index)
        difference = baseline.loc[common, "cumulative_control_loss_cost"] - oracle.loc[common, "cumulative_control_loss_cost"]
        after = difference[common >= 20.0]
        crossed = after[after >= j_mat]
        tcrit_records.append({
            "scenario_id": scenario_id, "J_mat": j_mat,
            "Tcrit_s": float(crossed.index[0]) if len(crossed) else float("nan"),
            "max_counterfactual_loss_gap": float(after.max()) if len(after) else 0.0,
        })
    pd.DataFrame(tcrit_records).to_csv(output_dir / "TCRIT_DEVELOPMENT.csv", index=False)

    plt.figure(figsize=(9, 5))
    plot = summary.copy()
    x = np.arange(len(plot))
    plt.bar(x - 0.2, 100 * plot["frequency_iae_improvement"], width=0.2, label="frequency IAE")
    plt.bar(x, 100 * plot["ace_iae_improvement"], width=0.2, label="ACE IAE")
    plt.bar(x + 0.2, 100 * plot["tie_iae_improvement"], width=0.2, label="tie IAE")
    plt.axhline(10.0, color="black", linestyle="--", linewidth=1)
    plt.xticks(x, [f"{m}\n{t}" for m, t in zip(plot.mechanism, plot.sg_tension)], rotation=60)
    plt.ylabel("O2 improvement over best baseline [%]")
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIGURE / f"e3_materiality_{suffix}.png", dpi=180)
    plt.close()

    docs = write_documents(episode_frame, summary, best_baseline, qualification, native, materiality)
    outputs = [
        output_dir / "E3_EXPERIMENT_MANIFEST.csv", output_dir / "E3_MATERIALITY_EPISODES.parquet",
        output_dir / "E3_CONTROL_RATE_TRACES.parquet", output_dir / "E3_MATERIALITY_SUMMARY.csv",
        output_dir / "ORACLE_QUALIFICATION.csv", output_dir / "PLANT_B_DIRECTION_CHECK.parquet",
        output_dir / "TCRIT_DEVELOPMENT.csv", FIGURE / f"e3_materiality_{suffix}.png", *docs,
    ]
    progress = {
        "stage": "E3", "run_type": suffix,
        "goal": "Qualify O2 and test whether current capability knowledge is materially valuable",
        "status": "PASSED" if materiality else "FAILED",
        "gate": "G3_MATERIALITY", "gate_passed": materiality,
        "gate_components": gate, "oracle_qualified": qualified,
        "best_deployable_baseline": best_baseline,
        "mechanisms_passing": mechanisms_passing, "sg_tensions_passing": tensions_passing,
        "decision": "CONTINUE_TO_E4" if materiality else "PROBLEM_NOT_MATERIAL",
        "tests": {
            "plant_a_unique_scenarios": len(manifest),
            "plant_a_episode_rows": len(episode_frame),
            "minimum_main_seeds_per_mechanism_tension": int(
                manifest[manifest.sfr_period_s == 4.0].groupby(["mechanism", "sg_tension"]).size().min()
            ),
            "plant_b_rows": len(native),
            "oracle_episode_qualification_rate": oracle_success,
            "oracle_residual_p99": oracle_residual_p99,
            "oracle_nonfinite_residual_episode_count": int(
                (~np.isfinite(oracle_residuals)).sum()
            ),
            "oracle_residual_basis": "finite successful-solve residual summaries; failures retained by solver-success and fallback fields",
        },
        "failures": [] if materiality else [key for key, value in gate.items() if not value],
        "repairs": [],
        "commands": [
            "python scripts/phase_e/run_e3_materiality.py --pilot",
            f"python scripts/phase_e/run_e3_materiality.py --workers {args.workers}",
            "python -m pytest tests/phase_e/test_e3_materiality.py -q",
        ],
        "outputs_sha256": {path.relative_to(REPO).as_posix(): sha256(path) for path in outputs},
        "next_stage": "E4" if materiality else "E9",
    }
    progress_path = REPO / "progress_phase_e" / f"E3_{suffix}.json"
    progress_path.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(progress, indent=2))
    if not materiality:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
