"""Run locked Phase-B2 validation smoke or final known/OOD experiments."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd

from d5freq.controllers.phase_b2_conventional import ConventionalACEPIController
from d5freq.evaluation.phase_b2_exact_nmpc import (
    ExactMultipleShootingNMPC,
    ExactNMPCConfig,
    OracleSolveRecord,
)
from d5freq.evaluation.phase_b2_identified_mpc import (
    TruthRegimeIdentifiedMPC,
    load_identified_model,
)
from d5freq.evaluation.phase_b2_plant import load_plant_b_parameters
from d5freq.models.two_area_plant_b import (
    PlantBObservation,
    PlantBStateIndex,
    TwoAreaPlantB,
    TwoAreaPlantBSimulator,
    UpperCommand,
)


KNOWN_SCENARIOS = (
    "load_only_step",
    "mode_only_headroom",
    "regime_before_load_energy",
    "coincident_communication_load",
    "regime_after_load_disable",
    "recovery_repeated",
)
OOD_SCENARIOS = (
    "structural_ood_coincident",
    "asymmetric_mixed_regime",
    "extreme_load_critical",
    "untrained_combination",
    "rapid_repeated_switches",
)
METHODS = (
    "O0_conventional_ACE_PI",
    "O1_truth_regime_identified_MPC",
    "O2_exact_current_regime_NMPC",
    "current_RLS_MPC_unported",
    "old_SD_BMPC_historical",
)
COST_RATIOS = (0.25, 0.5, 1.0, 2.0)


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    scenario_id: str
    partition: str
    timing_class: str
    initial_soc: tuple[float, float]
    load: Callable[[float, int], tuple[float, float]]
    regimes: Callable[[float], tuple[str, str]]
    o2_eligible: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--mode", choices=("validation", "final"), required=True)
    return parser.parse_args()


def _step_load(time_s: float, seed: int) -> tuple[float, float]:
    magnitudes = (0.02, 0.04, 0.06, 0.08)
    magnitude = magnitudes[seed % len(magnitudes)]
    sign = 1.0 if (seed // len(magnitudes)) % 2 == 0 else -1.0
    return (sign * magnitude, 0.0) if time_s >= 0.0 else (0.0, 0.0)


def scenario_definitions(partition: str) -> tuple[ScenarioDefinition, ...]:
    nominal = lambda _time: ("nominal_available", "nominal_available")
    if partition == "known":
        return (
            ScenarioDefinition(
                "load_only_step",
                partition,
                "load_only",
                (0.50, 0.50),
                _step_load,
                nominal,
                True,
            ),
            ScenarioDefinition(
                "mode_only_headroom",
                partition,
                "mode_only",
                (0.50, 0.50),
                lambda _t, _s: (0.0, 0.0),
                lambda _t: (
                    "headroom_or_current_limited",
                    "headroom_or_current_limited",
                ),
                False,
            ),
            ScenarioDefinition(
                "regime_before_load_energy",
                partition,
                "before",
                (0.14, 0.14),
                lambda t, _s: (0.06, 0.0) if t >= 5.0 else (0.0, 0.0),
                lambda _t: ("energy_limited", "energy_limited"),
                False,
            ),
            ScenarioDefinition(
                "coincident_communication_load",
                partition,
                "coincident",
                (0.50, 0.50),
                lambda _t, _s: (0.06, 0.0),
                lambda _t: ("communication_degraded", "communication_degraded"),
                True,
            ),
            ScenarioDefinition(
                "regime_after_load_disable",
                partition,
                "after",
                (0.50, 0.50),
                lambda _t, _s: (0.06, 0.0),
                lambda t: (
                    ("nominal_available", "nominal_available")
                    if t < 5.0
                    else ("service_disabled", "service_disabled")
                ),
                False,
            ),
            ScenarioDefinition(
                "recovery_repeated",
                partition,
                "repeated_recovery",
                (0.50, 0.50),
                lambda _t, _s: (0.04, 0.0),
                lambda t: (
                    ("service_disabled", "service_disabled")
                    if t < 4.0
                    else (
                        ("recovery", "recovery")
                        if t < 10.0
                        else ("nominal_available", "nominal_available")
                    )
                ),
                False,
            ),
        )
    return (
        ScenarioDefinition(
            "structural_ood_coincident",
            partition,
            "coincident_ood",
            (0.30, 0.70),
            lambda _t, _s: (0.08, 0.0),
            lambda _t: ("structural_ood", "structural_ood"),
            False,
        ),
        ScenarioDefinition(
            "asymmetric_mixed_regime",
            partition,
            "asymmetric_ood",
            (0.20, 0.80),
            lambda _t, _s: (0.0, 0.06),
            lambda _t: ("structural_ood", "nominal_available"),
            False,
        ),
        ScenarioDefinition(
            "extreme_load_critical",
            partition,
            "extreme_load",
            (0.50, 0.50),
            lambda _t, _s: (0.10, 0.02),
            nominal,
            False,
        ),
        ScenarioDefinition(
            "untrained_combination",
            partition,
            "untrained_combination",
            (0.14, 0.50),
            lambda _t, _s: (0.04, 0.04),
            lambda _t: ("communication_degraded", "energy_limited"),
            False,
        ),
        ScenarioDefinition(
            "rapid_repeated_switches",
            partition,
            "rapid_repeated_ood",
            (0.50, 0.50),
            lambda _t, _s: (0.08, 0.0),
            lambda t: (
                ("nominal_available", "nominal_available")
                if t < 2.0
                else (
                    ("structural_ood", "structural_ood")
                    if t < 4.0
                    else (
                        ("recovery", "recovery")
                        if t < 6.0
                        else (
                            ("service_disabled", "service_disabled")
                            if t < 8.0
                            else ("structural_ood", "structural_ood")
                        )
                    )
                )
            ),
            False,
        ),
    )


def _noisy_observation(
    observation: PlantBObservation,
    *,
    rng: np.random.Generator,
    multiplier: float,
    params: Any,
) -> PlantBObservation:
    frequency = np.asarray(observation.frequency_hz) + rng.normal(
        0.0, 0.001 * multiplier, size=2
    )
    tie = observation.tie_line_1_to_2_pu + float(
        rng.normal(0.0, 0.001 * multiplier)
    )
    bess = np.asarray(observation.bess_poi_power_pu) + rng.normal(
        0.0, 0.001 * multiplier, size=2
    )
    sg = np.asarray(observation.sg_mechanical_power_pu) + rng.normal(
        0.0, 0.001 * multiplier, size=2
    )
    ace = (
        params.areas[0].ace_bias_pu_per_hz * frequency[0] + tie,
        params.areas[1].ace_bias_pu_per_hz * frequency[1] - tie,
    )
    return PlantBObservation(
        time_s=observation.time_s,
        frequency_hz=(float(frequency[0]), float(frequency[1])),
        tie_line_1_to_2_pu=tie,
        ace_pu=(float(ace[0]), float(ace[1])),
        bess_poi_power_pu=(float(bess[0]), float(bess[1])),
        sg_mechanical_power_pu=(float(sg[0]), float(sg[1])),
        issued_sg_command_pu=observation.issued_sg_command_pu,
        issued_ibr_command_pu=observation.issued_ibr_command_pu,
    )


def _empty_failure_row(
    scenario: ScenarioDefinition,
    seed: int,
    sg_level: str,
    noise_multiplier: float,
    method: str,
    failure_type: str,
) -> dict[str, object]:
    row: dict[str, object] = {
        "scenario_id": scenario.scenario_id,
        "partition": scenario.partition,
        "timing_class": scenario.timing_class,
        "seed": seed,
        "plant_id": "Plant_B",
        "sg_level": sg_level,
        "noise_multiplier": noise_multiplier,
        "method": method,
        "run_completed": False,
        "scientific_success": False,
        "failure_type": failure_type,
        "catastrophic": False,
        "solver_status": "not_run",
        "solver_iterations": 0,
        "solver_kkt": math.nan,
        "solver_constraint_residual": math.nan,
        "solver_wall_time_s": 0.0,
        "solver_timeout_count": 0,
        "solver_infeasible_count": 0,
    }
    for name in (
        "freq_iae",
        "ace_iae",
        "max_abs_freq_hz",
        "max_abs_rocof",
        "tie_line_iae",
        "settling_time",
        "sg_energy",
        "ibr_energy",
        "sg_mileage",
        "ibr_mileage",
    ):
        row[name] = math.nan
    for ratio in COST_RATIOS:
        row[f"total_cost_ratio_{str(ratio).replace('.', 'p')}"] = math.nan
    return row


def _metrics_from_trajectory(
    trajectory: pd.DataFrame,
    *,
    scenario: ScenarioDefinition,
    seed: int,
    sg_level: str,
    noise_multiplier: float,
    method: str,
    solver: dict[str, object],
    scientific_failure: str | None,
) -> dict[str, object]:
    dt = float(np.median(np.diff(trajectory["time_s"])))
    frequency = trajectory[["frequency_1_hz", "frequency_2_hz"]].to_numpy()
    ace = trajectory[["ace_1_pu", "ace_2_pu"]].to_numpy()
    tie = trajectory["tie_line_pu"].to_numpy()
    sg = trajectory[["sg_power_1_pu", "sg_power_2_pu"]].to_numpy()
    ibr = trajectory[["ibr_power_1_pu", "ibr_power_2_pu"]].to_numpy()
    freq_iae = float(np.sum(np.abs(frequency[:-1])) * dt)
    ace_iae = float(np.sum(np.abs(ace[:-1])) * dt)
    max_frequency = float(np.max(np.abs(frequency)))
    rocof = np.diff(frequency, axis=0) / dt
    sg_energy = float(np.sum(np.abs(sg[:-1])) * dt)
    ibr_energy = float(np.sum(np.abs(ibr[:-1])) * dt)
    sg_mileage = float(np.sum(np.abs(np.diff(sg, axis=0))))
    ibr_mileage = float(np.sum(np.abs(np.diff(ibr, axis=0))))
    unsettled = np.any(np.abs(frequency) > 0.01, axis=1) | np.any(
        np.abs(ace) > 0.005, axis=1
    )
    if unsettled[-1]:
        settling = float(trajectory["time_s"].iloc[-1])
        settling_censored = True
    elif unsettled.any():
        settling = float(trajectory.loc[unsettled, "time_s"].iloc[-1])
        settling_censored = False
    else:
        settling = 0.0
        settling_censored = False
    nonfinite = not np.isfinite(
        np.asarray((freq_iae, ace_iae, max_frequency, sg_energy, ibr_energy))
    ).all()
    success = scientific_failure is None and not nonfinite and max_frequency <= 0.20
    failure_type = scientific_failure or ("nonfinite" if nonfinite else ("frequency_safety" if not success else "none"))
    row: dict[str, object] = {
        "scenario_id": scenario.scenario_id,
        "partition": scenario.partition,
        "timing_class": scenario.timing_class,
        "seed": seed,
        "plant_id": "Plant_B",
        "sg_level": sg_level,
        "noise_multiplier": noise_multiplier,
        "method": method,
        "run_completed": True,
        "scientific_success": success,
        "failure_type": failure_type,
        "catastrophic": max_frequency > 0.50,
        "freq_iae": freq_iae,
        "ace_iae": ace_iae,
        "max_abs_freq_hz": max_frequency,
        "max_abs_rocof": float(np.max(np.abs(rocof))),
        "tie_line_iae": float(np.sum(np.abs(tie[:-1])) * dt),
        "settling_time": settling,
        "settling_censored": settling_censored,
        "sg_energy": sg_energy,
        "ibr_energy": ibr_energy,
        "sg_mileage": sg_mileage,
        "ibr_mileage": ibr_mileage,
        **solver,
    }
    for ratio in COST_RATIOS:
        row[f"total_cost_ratio_{str(ratio).replace('.', 'p')}"] = (
            sg_energy + 0.1 * sg_mileage + ratio * (ibr_energy + 0.1 * ibr_mileage)
        )
    return row


def _simulate_method(
    repository: Path,
    scenario: ScenarioDefinition,
    *,
    seed: int,
    sg_level: str,
    noise_multiplier: float,
    method: str,
    o2_cache: dict[tuple[str, str], ExactMultipleShootingNMPC],
) -> tuple[dict[str, object], pd.DataFrame | None]:
    if method == "current_RLS_MPC_unported":
        return (
            _empty_failure_row(
                scenario,
                seed,
                sg_level,
                noise_multiplier,
                method,
                "scientific_failure_not_ported_to_two_area_Plant_B_no_retuning",
            ),
            None,
        )
    if method == "old_SD_BMPC_historical":
        return (
            _empty_failure_row(
                scenario,
                seed,
                sg_level,
                noise_multiplier,
                method,
                "historical_Plant_A_only_not_applicable_to_Plant_B",
            ),
            None,
        )
    if method == "O2_exact_current_regime_NMPC" and not scenario.o2_eligible:
        return (
            _empty_failure_row(
                scenario,
                seed,
                sg_level,
                noise_multiplier,
                method,
                "oracle_not_preregistered_or_quality_qualified_for_this_scenario",
            ),
            None,
        )
    params = load_plant_b_parameters(
        repository / "configs" / "phase_b2_plant_b.yaml", sg_level=sg_level
    )
    initial_regime = scenario.regimes(0.0)
    simulator = TwoAreaPlantBSimulator(
        TwoAreaPlantB(params),
        initial_state=TwoAreaPlantB(params).initial_state(soc=scenario.initial_soc),
        initial_regime_ids=initial_regime,
        random_seed=seed,
    )
    rng = np.random.default_rng(seed + 100_000 * METHODS.index(method))
    o0 = ConventionalACEPIController(
        params.sg_capability, control_period_s=params.upper_control_period_s
    )
    previous = UpperCommand()
    past_ibr = np.zeros((2, 2), dtype=np.float64)
    o2_plan: np.ndarray | None = None
    solver_records: list[dict[str, object]] = []
    scientific_failure: str | None = None
    trajectory_rows: list[dict[str, object]] = []

    def record_row() -> None:
        observation = simulator.observation()
        truth = simulator.evaluation_truth_snapshot()
        trajectory_rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "partition": scenario.partition,
                "seed": seed,
                "method": method,
                "sg_level": sg_level,
                "noise_multiplier": noise_multiplier,
                "time_s": observation.time_s,
                "frequency_1_hz": observation.frequency_hz[0],
                "frequency_2_hz": observation.frequency_hz[1],
                "tie_line_pu": observation.tie_line_1_to_2_pu,
                "ace_1_pu": observation.ace_pu[0],
                "ace_2_pu": observation.ace_pu[1],
                "sg_power_1_pu": observation.sg_mechanical_power_pu[0],
                "sg_power_2_pu": observation.sg_mechanical_power_pu[1],
                "ibr_power_1_pu": observation.bess_poi_power_pu[0],
                "ibr_power_2_pu": observation.bess_poi_power_pu[1],
                "sg_command_1_pu": observation.issued_sg_command_pu[0],
                "sg_command_2_pu": observation.issued_sg_command_pu[1],
                "ibr_command_1_pu": observation.issued_ibr_command_pu[0],
                "ibr_command_2_pu": observation.issued_ibr_command_pu[1],
                "true_regime_1_evaluation_only": truth["regime_ids"][0],
                "true_regime_2_evaluation_only": truth["regime_ids"][1],
                "soc_1_evaluation_only": truth["soc"][0],
                "soc_2_evaluation_only": truth["soc"][1],
                "headroom_up_1_evaluation_only": truth["headroom_up_down_pu"][0][0],
                "headroom_up_2_evaluation_only": truth["headroom_up_down_pu"][1][0],
            }
        )

    record_row()
    total_steps = round(12.0 / params.integration_step_s)
    block_steps = round(params.upper_control_period_s / params.integration_step_s)
    for step in range(total_steps):
        time_s = simulator.time_s
        regimes = scenario.regimes(time_s)
        if regimes != simulator.regime_ids_evaluation_only:
            simulator.set_regimes(regimes)
        if step % block_steps == 0:
            if time_s < 2.0 - 1.0e-12:
                command = UpperCommand()
            elif method == "O0_conventional_ACE_PI":
                command = o0.command(
                    _noisy_observation(
                        simulator.observation(),
                        rng=rng,
                        multiplier=noise_multiplier,
                        params=params,
                    )
                )
            elif method == "O1_truth_regime_identified_MPC":
                if regimes[0] != regimes[1] or regimes[0] == "structural_ood":
                    scientific_failure = "O1_truth_regime_model_unavailable"
                    command = UpperCommand()
                else:
                    model_path = (
                        repository
                        / "artifacts_phase_b2"
                        / "identified_models"
                        / sg_level
                        / f"{regimes[0]}.npz"
                    )
                    if not model_path.exists():
                        scientific_failure = "O1_truth_regime_model_unavailable"
                        command = UpperCommand()
                    else:
                        identified = load_identified_model(model_path)
                        controller = TruthRegimeIdentifiedMPC(
                            params,
                            {identified.regime_pair: identified},
                            config=ExactNMPCConfig(horizon_s=10.0),
                        )
                        result = controller.solve(
                            simulator.state,
                            regime_pair=regimes,
                            current_load_pu=scenario.load(time_s, seed),
                            previous_command=previous,
                            past_ibr_commands_pu=past_ibr,
                        )
                        solver_records.append(
                            {
                                "status": result.solver_status,
                                "iterations": result.iterations,
                                "kkt": result.kkt_residual_inf,
                                "constraint": result.max_constraint_residual,
                                "wall": result.wall_time_s,
                                "success": result.success,
                            }
                        )
                        if result.success:
                            command = result.command
                        else:
                            scientific_failure = "O1_solver_failure"
                            command = UpperCommand()
            else:
                if o2_plan is None:
                    cache_key = (sg_level, regimes[0])
                    if cache_key not in o2_cache:
                        o2_cache[cache_key] = ExactMultipleShootingNMPC.for_current_regime(
                            params,
                            regimes,
                            config=ExactNMPCConfig(horizon_s=10.0, ipopt_max_iterations=100),
                        )
                    initial = "zero" if regimes[0] == "nominal_available" else "split_load"
                    result_o2: OracleSolveRecord = o2_cache[cache_key].solve(
                        simulator.state,
                        load_forecast_pu=scenario.load(time_s, seed),
                        previous_command=previous,
                        past_ibr_commands_pu=past_ibr,
                        initializations=(initial,),
                    )
                    solver_records.append(
                        {
                            "status": result_o2.solver_status,
                            "iterations": result_o2.iterations,
                            "kkt": result_o2.kkt_residual_inf,
                            "constraint": result_o2.max_constraint_residual,
                            "wall": result_o2.wall_time_s,
                            "success": result_o2.success,
                        }
                    )
                    if result_o2.success:
                        o2_plan = result_o2.action_sequence
                    else:
                        scientific_failure = "O2_solver_quality_failure"
                        o2_plan = np.zeros((4, 5), dtype=np.float64)
                plan_index = min(round((time_s - 2.0) / 2.0), 4)
                action = o2_plan[:, plan_index]
                command = UpperCommand(
                    sg_pu=(float(action[0]), float(action[1])),
                    ibr_pu=(float(action[2]), float(action[3])),
                )
            simulator.issue_command(command)
            previous = command
            past_ibr = np.column_stack((past_ibr[:, 1], np.asarray(command.ibr_pu)))
        simulator.advance(scenario.load(time_s, seed))
        record_row()
    trajectory = pd.DataFrame(trajectory_rows)
    if solver_records:
        solver_payload = {
            "solver_status": "|".join(str(row["status"]) for row in solver_records),
            "solver_iterations": int(sum(int(row["iterations"]) for row in solver_records)),
            "solver_kkt": float(max(float(row["kkt"]) for row in solver_records)),
            "solver_constraint_residual": float(
                max(float(row["constraint"]) for row in solver_records)
            ),
            "solver_wall_time_s": float(sum(float(row["wall"]) for row in solver_records)),
            "solver_timeout_count": int(
                sum("Maximum_Iterations" in str(row["status"]) for row in solver_records)
            ),
            "solver_infeasible_count": int(
                sum("Infeasible" in str(row["status"]) for row in solver_records)
            ),
        }
    else:
        solver_payload = {
            "solver_status": "not_applicable",
            "solver_iterations": 0,
            "solver_kkt": math.nan,
            "solver_constraint_residual": math.nan,
            "solver_wall_time_s": 0.0,
            "solver_timeout_count": 0,
            "solver_infeasible_count": 0,
        }
    return (
        _metrics_from_trajectory(
            trajectory,
            scenario=scenario,
            seed=seed,
            sg_level=sg_level,
            noise_multiplier=noise_multiplier,
            method=method,
            solver=solver_payload,
            scientific_failure=scientific_failure,
        ),
        trajectory,
    )


def _paired_failures(metrics: pd.DataFrame) -> pd.DataFrame:
    reference = "O0_conventional_ACE_PI"
    keys = ["scenario_id", "partition", "seed", "sg_level"]
    ref = metrics.loc[metrics["method"] == reference, keys + ["scientific_success"]].rename(
        columns={"scientific_success": "reference_success"}
    )
    rows = []
    for method in METHODS[1:]:
        candidate = metrics.loc[
            metrics["method"] == method, keys + ["scientific_success"]
        ].rename(columns={"scientific_success": "method_success"})
        paired = candidate.merge(ref, on=keys, how="outer", validate="one_to_one")
        for row in paired.itertuples(index=False):
            method_success = bool(row.method_success)
            reference_success = bool(row.reference_success)
            rows.append(
                {
                    "method": method,
                    "reference": reference,
                    "scenario": row.scenario_id,
                    "partition": row.partition,
                    "seed": row.seed,
                    "sg_level": row.sg_level,
                    "both_success": method_success and reference_success,
                    "method_only_failure": (not method_success) and reference_success,
                    "reference_only_failure": method_success and (not reference_success),
                    "both_failure": (not method_success) and (not reference_success),
                }
            )
    return pd.DataFrame(rows)


def _bootstrap_mean_ci(values: np.ndarray, *, seed: int, resamples: int = 10_000) -> tuple[float, float]:
    if len(values) == 0:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(values), size=(resamples, len(values)))
    estimates = values[indices].mean(axis=1)
    return float(np.quantile(estimates, 0.025)), float(np.quantile(estimates, 0.975))


def _materiality(metrics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    o2 = metrics.loc[
        (metrics["method"] == "O2_exact_current_regime_NMPC")
        & metrics["run_completed"]
    ]
    o0 = metrics.loc[metrics["method"] == "O0_conventional_ACE_PI"]
    keys = ["scenario_id", "partition", "seed", "sg_level"]
    continuous = ["freq_iae", "ace_iae", "max_abs_freq_hz"]
    cost_columns = [f"total_cost_ratio_{str(value).replace('.', 'p')}" for value in COST_RATIOS]
    paired = o2[keys + ["scientific_success", *continuous, *cost_columns]].merge(
        o0[keys + ["scientific_success", *continuous, *cost_columns]],
        on=keys,
        suffixes=("_O2", "_O0"),
        how="inner",
        validate="one_to_one",
    )
    rows: list[dict[str, object]] = []
    sensitivity: list[dict[str, object]] = []
    for (scenario, sg_level), group in paired.groupby(["scenario_id", "sg_level"]):
        common = group.loc[group["scientific_success_O2"] & group["scientific_success_O0"]]
        frequency_effect = (
            common["freq_iae_O0"].to_numpy() - common["freq_iae_O2"].to_numpy()
        )
        relative = frequency_effect / np.maximum(common["freq_iae_O0"].to_numpy(), 1.0e-12)
        ci_low, ci_high = _bootstrap_mean_ci(relative, seed=20260730)
        rows.append(
            {
                "scenario_id": scenario,
                "sg_level": sg_level,
                "attempted_pairs": len(group),
                "both_success_pairs": len(common),
                "method_only_failures": int(
                    ((~group["scientific_success_O2"]) & group["scientific_success_O0"]).sum()
                ),
                "reference_only_failures": int(
                    (group["scientific_success_O2"] & (~group["scientific_success_O0"])).sum()
                ),
                "scenario_balanced_absolute_freq_iae_effect": float(frequency_effect.mean())
                if len(common)
                else math.nan,
                "ratio_of_aggregate_means_freq_improvement": float(
                    1.0 - common["freq_iae_O2"].mean() / common["freq_iae_O0"].mean()
                )
                if len(common)
                else math.nan,
                "bootstrap_relative_effect_ci_low": ci_low,
                "bootstrap_relative_effect_ci_high": ci_high,
                "success_first_eligible": bool(
                    len(group) > 0
                    and len(common) == len(group)
                    and group["scientific_success_O2"].all()
                ),
            }
        )
        for ratio, column in zip(COST_RATIOS, cost_columns):
            if len(common):
                cost_effect = float(
                    1.0 - common[f"{column}_O2"].mean() / common[f"{column}_O0"].mean()
                )
            else:
                cost_effect = math.nan
            sensitivity.append(
                {
                    "scenario_id": scenario,
                    "sg_level": sg_level,
                    "ibr_to_sg_cost_ratio": ratio,
                    "total_cost_relative_improvement": cost_effect,
                    "total_cost_noninferior_within_2_percent": bool(
                        np.isfinite(cost_effect) and cost_effect >= -0.02
                    ),
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(sensitivity)


def _select_representatives(
    metrics: pd.DataFrame,
    trajectories: dict[tuple[str, int, str], pd.DataFrame],
) -> pd.DataFrame:
    selections: list[tuple[str, tuple[str, int, str]]] = []
    class_scenarios = {
        "load_only": "load_only_step",
        "mode_only_headroom": "mode_only_headroom",
        "before_energy": "regime_before_load_energy",
        "coincident_communication": "coincident_communication_load",
        "after_disable": "regime_after_load_disable",
        "recovery": "recovery_repeated",
        "ood": "structural_ood_coincident",
    }
    for label, scenario in class_scenarios.items():
        candidates = [key for key in trajectories if key[0] == scenario]
        for key in sorted(candidates, key=lambda item: (item[1], item[2]))[:3]:
            selections.append((label, key))
    completed = metrics.loc[metrics["run_completed"]]
    if len(completed):
        worst = completed.sort_values("max_abs_freq_hz", ascending=False).iloc[0]
        selections.append(
            (
                "worst_completed_episode",
                (worst.scenario_id, int(worst.seed), worst.method),
            )
        )
    eligible = metrics.loc[
        metrics["method"].isin(
            ("O0_conventional_ACE_PI", "O2_exact_current_regime_NMPC")
        )
        & metrics["run_completed"]
    ]
    pivot = eligible.pivot_table(
        index=["scenario_id", "seed"], columns="method", values="freq_iae"
    ).dropna()
    if len(pivot):
        pivot["gap"] = (
            pivot["O0_conventional_ACE_PI"] - pivot["O2_exact_current_regime_NMPC"]
        ).abs()
        scenario, seed = pivot["gap"].idxmax()
        for method in ("O0_conventional_ACE_PI", "O2_exact_current_regime_NMPC"):
            selections.append(("largest_O2_O0_difference", (scenario, int(seed), method)))
    frames = []
    seen: set[tuple[str, tuple[str, int, str]]] = set()
    for label, key in selections:
        marker = (label, key)
        if marker in seen or key not in trajectories:
            continue
        seen.add(marker)
        frame = trajectories[key].copy()
        frame.insert(0, "trajectory_class", label)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main() -> None:
    args = parse_args()
    repository = args.repository.resolve()
    if args.mode == "validation":
        partitions = (("known", range(800, 802), scenario_definitions("known")[:4:3]),)
        output_dir = repository / "results_phase_b2" / "experiment_validation_smoke"
    else:
        partitions = (
            ("known", range(5000, 5030), scenario_definitions("known")),
            ("ood_extreme", range(6000, 6050), scenario_definitions("ood_extreme")),
        )
        output_dir = repository / "results_phase_b2" / "final_experiment"
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_rows: list[dict[str, object]] = []
    trajectories: dict[tuple[str, int, str], pd.DataFrame] = {}
    o2_cache: dict[tuple[str, str], ExactMultipleShootingNMPC] = {}
    started = time.perf_counter()
    for _partition, seeds, scenarios in partitions:
        for seed in seeds:
            sg_level = ("adequate", "scarce", "critical")[seed % 3]
            noise_multiplier = (0.5, 1.0, 2.0)[(seed // 3) % 3]
            for scenario in scenarios:
                for method in METHODS:
                    row, trajectory = _simulate_method(
                        repository,
                        scenario,
                        seed=seed,
                        sg_level=sg_level,
                        noise_multiplier=noise_multiplier,
                        method=method,
                        o2_cache=o2_cache,
                    )
                    metrics_rows.append(row)
                    if trajectory is not None:
                        trajectories[(scenario.scenario_id, seed, method)] = trajectory
                print(
                    f"{args.mode}: seed={seed} scenario={scenario.scenario_id}",
                    flush=True,
                )
    metrics = pd.DataFrame(metrics_rows)
    failures = _paired_failures(metrics)
    materiality, sensitivity = _materiality(metrics)
    representatives = _select_representatives(metrics, trajectories)
    metrics.to_csv(output_dir / "per_episode_metrics.csv", index=False)
    failures.to_csv(output_dir / "paired_failure_outcomes.csv", index=False)
    materiality.to_csv(output_dir / "corrected_materiality.csv", index=False)
    sensitivity.to_csv(output_dir / "cost_sensitivity.csv", index=False)
    if len(representatives):
        representatives.to_parquet(
            output_dir / "representative_trajectories.parquet",
            index=False,
            compression="zstd",
        )
    manifest = {
        "schema_version": "d5freq.phase_b2.experiment_run.v1",
        "mode": args.mode,
        "elapsed_s": time.perf_counter() - started,
        "episode_rows": len(metrics),
        "run_completed_count": int(metrics["run_completed"].sum()),
        "scientific_success_count": int(metrics["scientific_success"].sum()),
        "scientific_failure_count": int((~metrics["scientific_success"]).sum()),
        "method_counts": metrics.groupby("method").size().to_dict(),
        "failure_type_counts": metrics.groupby("failure_type").size().to_dict(),
        "final_results_feedback_forbidden": args.mode == "final",
        "ordinary_methods_true_regime_access": False,
        "oracle_methods_evaluation_only": True,
        "deleted_episode_count": 0,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
