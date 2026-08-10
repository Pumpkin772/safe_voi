"""Registered A1 perfect-capability materiality experiment."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from direction5freq.controllers.dcsv_mpc_final import DCSVInput
from direction5freq.controllers.domain_supervisor import DomainSupervisor
from direction5freq.controllers.contract_robust_mpc import ContractOnlyRollingRobustMPC
from direction5freq.controllers.oracle_mpc import TrueCapabilityOracleMPC
from direction5freq.estimation.deliverability_set_membership import DeliverabilitySetMembership
from direction5freq.estimation.grid_load_mhe import ConstrainedGridLoadMHE
from direction5freq.estimation.grid_load_observer import LoadObserverInput
from direction5freq.models.capability_contract import CapabilityRealization
from direction5freq.models.plant_a_full import PlantAFull, PlantAParameters, PublicObservation


METHODS = ("contract_only_rolling_mpc", "perfect_capability_oracle_mpc")
METRICS = ("ace_iae_pu_s", "tie_iae_pu_s", "sg_mechanical_mileage_pu")


def plant_parameters(tension: str) -> PlantAParameters:
    base = PlantAParameters()
    if tension == "low":
        return base
    if tension == "high":
        return replace(
            base,
            valve_upper_pu=(0.105, 0.105),
            sg_power_upper_pu=(0.090, 0.090),
            grc_up_pu_per_s=(0.009, 0.009),
        )
    raise ValueError(tension)


def build_manifest(lock: dict[str, Any]) -> pd.DataFrame:
    """Build an explicit factorial manifest without seed-modulo factor binding."""

    seeds = iter(range(int(lock["seed_range_used"][0]), int(lock["seed_range_used"][1]) + 1))
    offsets = tuple(float(value) for value in lock["load_event_offsets_s"])
    rng = np.random.default_rng(202608101)
    rows: list[dict[str, Any]] = []
    index = 0
    for mechanism in lock["mechanisms"]:
        for tension in lock["sg_tensions"]:
            for period_s in lock["periods_s"]:
                for replicate in range(int(lock["replicates_per_design_cell"])):
                    seed = next(seeds)
                    capability_time = float(rng.uniform(*lock["capability_change_time_range_s"]))
                    offset = offsets[replicate]
                    rows.append({
                        "scenario_id": f"A1-D-{index:03d}",
                        "split": "development",
                        "seed": seed,
                        "plant": "A_full_nonlinear",
                        "mechanism": mechanism,
                        "sg_tension": tension,
                        "period_s": float(period_s),
                        "duration_s": float(lock["duration_s"]),
                        "nominal_warmup_s": float(lock["nominal_warmup_min_s"]),
                        "capability_change_time_s": capability_time,
                        "load_event_time_s": capability_time + offset,
                        "timing_relation": "before" if offset < 0 else "after" if offset > 0 else "simultaneous",
                        "load_area": "area0" if replicate != 1 else "area1",
                        "load_sign": 1,
                        "initial_soc": float(lock["initial_soc"]),
                        "known_ood": "known",
                        "contract_violation": False,
                        "factor_assignment": "EXPLICIT_FACTORIAL_NOT_SEED_MODULO",
                    })
                    index += 1
    return pd.DataFrame(rows)


def capability_for(row: pd.Series, time_s: float, lock: dict[str, Any]) -> CapabilityRealization:
    if time_s < float(row.capability_change_time_s):
        return CapabilityRealization()
    values = lock["capability_after_change"][str(row.mechanism)]
    return CapabilityRealization(**{
        key: tuple(float(value) for value in values[key])
        for key in (
            "lower_power_pu", "upper_power_pu", "ramp_down_pu_per_s",
            "ramp_up_pu_per_s", "delay_s",
        )
    })


def load_for(row: pd.Series, parameters: PlantAParameters, time_s: float, lock: dict[str, Any]) -> np.ndarray:
    if time_s < float(row.load_event_time_s):
        return np.zeros(2)
    magnitude = float(lock["load_fraction_of_sg_upper"]) * min(parameters.sg_power_upper_pu)
    cross = float(lock["load_cross_area_fraction"])
    if row.load_area == "area0":
        return np.array((magnitude, cross * magnitude))
    return np.array((cross * magnitude, magnitude))


def _control_observation(public: PublicObservation) -> PublicObservation:
    return PublicObservation(
        time_s=public.time_s,
        frequency_deviation_hz=public.frequency_deviation_hz.copy(),
        ace_pu=public.ace_pu.copy(),
        tie_line_pu=public.tie_line_pu,
        valve_pu=public.valve_pu.copy(),
        sg_mechanical_power_pu=public.sg_mechanical_power_pu.copy(),
        bess_actual_power_pu=public.bess_actual_power_pu.copy(),
        measured_soc=public.measured_soc.copy(),
        slow_reserve_power_pu=public.slow_reserve_power_pu.copy(),
        issued_command_pu=public.issued_command_pu.copy(),
    )


def simulate_episode(row_dict: dict[str, Any], method: str, lock: dict[str, Any]) -> dict[str, Any]:
    if method not in METHODS:
        raise ValueError(method)
    row = pd.Series(row_dict)
    parameters = plant_parameters(str(row.sg_tension))
    dt_s = float(lock["physical_dt_s"])
    period_s = float(row.period_s)
    duration_s = float(row.duration_s)
    plant = PlantAFull(parameters, dt_s=dt_s)
    state = plant.equilibrium((float(row.initial_soc), float(row.initial_soc)))
    observer = ConstrainedGridLoadMHE(
        nominal_frequency_hz=parameters.nominal_frequency_hz,
        inertia_s=parameters.inertia_s,
        damping_pu_per_pu_frequency=parameters.damping_pu_per_pu_frequency,
        derivative_filter=0.40,
        warmup_samples=8,
    )
    estimator = DeliverabilitySetMembership(parameters.bess.contract, period_s)
    supervisor = DomainSupervisor(parameters)
    if method == "contract_only_rolling_mpc":
        controller: Any = ContractOnlyRollingRobustMPC(period_s, int(lock["horizon_steps"]), parameters)
    else:
        controller = TrueCapabilityOracleMPC(period_s, int(lock["horizon_steps"]), parameters)

    command = np.zeros(4)
    reserve_request = np.zeros(2)
    next_control_s = 0.0
    frequency_peak_hz = 0.0
    ace_iae = 0.0
    tie_iae = 0.0
    sg_mileage = 0.0
    bess_energy_throughput = 0.0
    hard_violation = False
    solver_calls = 0
    fallbacks = 0
    restorations = 0
    solve_times: list[float] = []
    previous_mechanical = state.mechanical_power_pu.copy()
    terminal_frequency: list[float] = []
    terminal_ace: list[float] = []

    steps = int(round(duration_s / dt_s))
    for step in range(steps + 1):
        time_s = step * dt_s
        public = plant.public_observation(time_s, state, command)
        estimate = observer.update(LoadObserverInput(
            time_s=time_s,
            frequency_deviation_hz=public.frequency_deviation_hz,
            tie_line_pu=public.tie_line_pu,
            sg_mechanical_power_pu=public.sg_mechanical_power_pu,
            bess_actual_poi_power_pu=public.bess_actual_power_pu,
            slow_reserve_power_pu=public.slow_reserve_power_pu,
        ))
        if time_s + 1e-10 >= next_control_s:
            requested = (
                -parameters.bess.pfr_gain_pu_power_per_pu_frequency
                * public.frequency_deviation_hz / parameters.nominal_frequency_hz
                + command[[1, 3]]
            )
            envelope = estimator.update(time_s, requested, public.bess_actual_power_pu)
            domain = supervisor.classify(estimate.load_pu, public.measured_soc)
            inputs = DCSVInput(_control_observation(public), estimate.load_pu, envelope, domain)
            truth = capability_for(row, time_s, lock)
            if method == "perfect_capability_oracle_mpc":
                result = controller.propose_with_evaluation_truth(inputs, truth)
            else:
                result = controller.propose(inputs)
            command = result.proposed_action_pu.copy()
            reserve_request = result.slow_reserve_request_pu.copy()
            command[[0, 2]] = np.clip(command[[0, 2]], parameters.valve_lower_pu, parameters.valve_upper_pu)
            command[[1, 3]] = np.clip(command[[1, 3]], -parameters.bess.rating_pu, parameters.bess.rating_pu)
            controller.commit(command, public.bess_actual_power_pu)
            diagnostics = result.diagnostics
            solver_calls += int(getattr(diagnostics, "attempted_optimization_calls", 1))
            fallbacks += int(diagnostics.fallback_used)
            restorations += int(diagnostics.restoration_used)
            solve_times.append(float(diagnostics.solve_time_s))
            next_control_s += period_s

        frequency_peak_hz = max(frequency_peak_hz, float(np.max(np.abs(public.frequency_deviation_hz))))
        ace_iae += float(np.sum(np.abs(public.ace_pu))) * dt_s
        tie_iae += abs(float(public.tie_line_pu)) * dt_s
        if time_s >= duration_s - 30.0:
            terminal_frequency.append(float(np.max(np.abs(public.frequency_deviation_hz))))
            terminal_ace.append(float(np.max(np.abs(public.ace_pu))))

        if step < steps:
            truth = capability_for(row, time_s, lock)
            state, diagnostics = plant.step(
                state, command, load_for(row, parameters, time_s, lock), truth, reserve_request
            )
            sg_mileage += float(np.sum(np.abs(state.mechanical_power_pu - previous_mechanical)))
            previous_mechanical = state.mechanical_power_pu.copy()
            bess_energy_throughput += float(np.sum(np.abs(state.bess.power_pu))) * dt_s
            soc = state.bess.measured_soc(parameters.bess)
            hard_violation |= bool(
                np.any(soc < parameters.bess.soc_min - 1e-9)
                or np.any(soc > parameters.bess.soc_max + 1e-9)
                or np.any(state.mechanical_power_pu < np.asarray(parameters.sg_power_lower_pu) - 1e-9)
                or np.any(state.mechanical_power_pu > np.asarray(parameters.sg_power_upper_pu) + 1e-9)
            )

    terminal_recovery = bool(
        max(terminal_frequency, default=np.inf) <= 0.12
        and max(terminal_ace, default=np.inf) <= 0.06
    )
    result_row = dict(row_dict)
    result_row.update({
        "method": method,
        "physical_success": bool(not hard_violation and frequency_peak_hz <= float(lock["gate"]["frequency_peak_hz_max"]) and terminal_recovery),
        "hard_violation": hard_violation,
        "terminal_recovery": terminal_recovery,
        "frequency_peak_hz": frequency_peak_hz,
        "ace_iae_pu_s": ace_iae,
        "tie_iae_pu_s": tie_iae,
        "sg_mechanical_mileage_pu": sg_mileage,
        "bess_energy_throughput_pu_s": bess_energy_throughput,
        "controller_calls": int(round(duration_s / period_s)) + 1,
        "attempted_optimization_calls": solver_calls,
        "fallback_calls": fallbacks,
        "restoration_calls": restorations,
        "p99_solve_time_s": float(np.quantile(solve_times, 0.99)),
        "true_capability_read_by_ordinary_controller": False,
        "evaluation_only_truth_used": method == "perfect_capability_oracle_mpc",
        "full_rolling": True,
    })
    return result_row


def paired_analysis(episodes: pd.DataFrame, bootstrap_resamples: int = 5000) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = ["scenario_id", "mechanism", "sg_tension", "period_s", "seed"]
    values = episodes.pivot(index=index, columns="method", values=list(METRICS)).reset_index()
    paired = values[index].copy()
    for metric in METRICS:
        paired[f"delta_{metric}"] = (
            values[(metric, "contract_only_rolling_mpc")]
            - values[(metric, "perfect_capability_oracle_mpc")]
        )

    rng = np.random.default_rng(202608102)
    rows: list[dict[str, Any]] = []
    for (mechanism, tension), group in paired.groupby(["mechanism", "sg_tension"], sort=True):
        periods = sorted(group.period_s.unique())
        samples = {metric: [] for metric in METRICS}
        for _ in range(int(bootstrap_resamples)):
            for metric in METRICS:
                period_means = []
                for period in periods:
                    values_metric = group.loc[group.period_s == period, f"delta_{metric}"].to_numpy()
                    period_means.append(float(np.mean(rng.choice(values_metric, len(values_metric), replace=True))))
                samples[metric].append(float(np.mean(period_means)))
        row: dict[str, Any] = {
            "mechanism": mechanism,
            "sg_tension": tension,
            "scenario_count": int(len(group)),
            "period_count": len(periods),
        }
        positive_metrics = []
        for metric in METRICS:
            point = float(group.groupby("period_s")[f"delta_{metric}"].mean().mean())
            lower, upper = np.quantile(samples[metric], (0.025, 0.975))
            row[f"mean_delta_{metric}"] = point
            row[f"ci_lower_{metric}"] = float(lower)
            row[f"ci_upper_{metric}"] = float(upper)
            if point > 0.0 and lower > 0.0:
                positive_metrics.append(metric)
        row["positive_metrics"] = ";".join(positive_metrics)
        row["materiality_positive"] = bool(positive_metrics)
        rows.append(row)
    return paired, pd.DataFrame(rows)


__all__ = [
    "METHODS", "METRICS", "build_manifest", "capability_for", "load_for",
    "paired_analysis", "plant_parameters", "simulate_episode",
]
