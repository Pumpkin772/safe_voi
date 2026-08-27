"""Full nonlinear Plant-A episodes for the frozen boundary policy."""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np

from direction5freq.models.capability_contract import CapabilityRealization
from direction5freq.models.plant_a_full import PlantAFull, PublicObservation

from rolling_boundary_controller import (
    PerfectCapabilityBoundaryOracle, RollingBoundaryController,
)
from selective_boundary_policy import FrozenBoundaryLookup
from voi_boundary_engine import BoundaryPoint, plant_parameters


def capability_at(row: dict[str, Any], time_s: float) -> CapabilityRealization:
    if time_s < float(row["capability_change_time_s"]):
        return CapabilityRealization()
    power = float(row["true_power_pu"]); ramp = float(row["true_ramp_pu_per_s"])
    delay = float(row["true_delay_s"])
    return CapabilityRealization(
        lower_power_pu=(-power, -power), upper_power_pu=(power, power),
        ramp_down_pu_per_s=(ramp, ramp), ramp_up_pu_per_s=(ramp, ramp),
        delay_s=(delay, delay),
    )


def load_at(row: dict[str, Any], time_s: float) -> np.ndarray:
    if time_s < float(row["load_event_time_s"]):
        return np.zeros(2)
    magnitude = float(row["load_magnitude_pu"]) * float(row.get("load_sign", 1.0))
    area = str(row.get("load_area", "both"))
    if area == "area0":
        return np.array((magnitude, 0.25 * magnitude))
    if area == "area1":
        return np.array((0.25 * magnitude, magnitude))
    return np.array((magnitude, 0.65 * magnitude))


def load_profile(
    row: dict[str, Any], duration_s: float, dt_s: float
) -> tuple[np.ndarray, np.ndarray]:
    """Generate the paired, truth-side load path before closed-loop control.

    The mean-reverting regulation path is independent of controller actions,
    hidden capability, and the contingency draw.  It is piecewise constant at
    the registered 4 s regulation-update scale and hard bounded so that its
    sum with the contingency remains inside the predecessor load envelope.
    """

    steps = int(round(duration_s / dt_s))
    background = np.zeros((steps + 1, 2), dtype=float)
    if row.get("load_process_kind") != "bounded_bivariate_ou_plus_contingency":
        total = np.asarray(
            [load_at(row, step * dt_s) for step in range(steps + 1)],
            dtype=float,
        )
        return total, background

    rng = np.random.default_rng(int(row["regulation_seed"]))
    start_s = float(row["regulation_start_time_s"])
    update_s = float(row["regulation_update_period_s"])
    tau_s = float(row["regulation_time_constant_s"])
    stationary_std = float(row["regulation_stationary_std_pu"])
    hard_bound = float(row["regulation_hard_bound_pu"])
    correlation = float(row["regulation_area_correlation"])
    phi = float(np.exp(-update_s / tau_s))
    innovation_std = stationary_std * np.sqrt(1.0 - phi ** 2)
    correlation_matrix = np.asarray(((1.0, correlation), (correlation, 1.0)))
    cholesky = np.linalg.cholesky(correlation_matrix)
    state = np.zeros(2)
    next_update_s = start_s
    for step in range(steps + 1):
        time_s = step * dt_s
        if time_s + 1e-10 >= next_update_s:
            innovation = innovation_std * (cholesky @ rng.normal(size=2))
            state = np.clip(phi * state + innovation, -hard_bound, hard_bound)
            next_update_s += update_s
        if time_s >= start_s:
            background[step] = state
    contingency = np.asarray(
        [load_at(row, step * dt_s) for step in range(steps + 1)],
        dtype=float,
    )
    return background + contingency, background


def noisy_observation(
    observation: PublicObservation,
    rng: np.random.Generator,
    frequency_noise_std_hz: float,
    poi_noise_std_pu: float,
    *,
    frequency_noise_hz: np.ndarray | None = None,
    poi_noise_pu: np.ndarray | None = None,
) -> PublicObservation:
    frequency_noise = (
        rng.normal(0.0, frequency_noise_std_hz, 2)
        if frequency_noise_hz is None else np.asarray(frequency_noise_hz, dtype=float)
    )
    poi_noise = (
        rng.normal(0.0, poi_noise_std_pu, 2)
        if poi_noise_pu is None else np.asarray(poi_noise_pu, dtype=float)
    )
    frequency = observation.frequency_deviation_hz + frequency_noise
    poi = observation.bess_actual_power_pu + poi_noise
    omega = frequency / 50.0
    ace = np.array((21.0 * omega[0] + observation.tie_line_pu,
                    21.0 * omega[1] - observation.tie_line_pu))
    return replace(
        observation, frequency_deviation_hz=frequency,
        ace_pu=ace, bess_actual_power_pu=poi,
    )


def simulate_plant_a(
    row: dict[str, Any],
    method: str,
    template: BoundaryPoint,
    *,
    lookup: FrozenBoundaryLookup | None = None,
    dt_s: float = 0.02,
    trace_path: Path | None = None,
) -> dict[str, Any]:
    parameters = plant_parameters(template.sg_tension, template.nominal_frequency_hz)
    plant = PlantAFull(parameters, dt_s=dt_s)
    state = plant.equilibrium((float(row["initial_soc"]), float(row["initial_soc"])))
    horizon_s = float(row.get("rolling_horizon_s", 24.0))
    if method == "perfect_capability_oracle":
        controller: RollingBoundaryController = PerfectCapabilityBoundaryOracle(
            template, parameters, horizon_s=horizon_s, observation_dt_s=dt_s,
        )
    elif method == "selective_voi_accr_mpc":
        controller = RollingBoundaryController(
            template, parameters, lookup=lookup, horizon_s=horizon_s, observation_dt_s=dt_s,
        )
    elif method == "contract_mpc":
        controller = RollingBoundaryController(
            template, parameters, lookup=None, horizon_s=horizon_s, observation_dt_s=dt_s,
        )
    else:
        raise ValueError(method)
    control_seed, poi_seed = np.random.SeedSequence(int(row["seed"])).spawn(2)
    control_rng = np.random.default_rng(control_seed)
    poi_rng = np.random.default_rng(poi_seed)
    command = np.zeros(4); next_control = 0.0
    next_poi_observation = 0.0
    poi_noise_state = np.zeros(2)
    poi_noise_correlation = float(row.get("poi_noise_correlation", 0.0))
    poi_observation_period_s = float(
        row.get("poi_observation_period_s", template.period_s)
    )
    duration_s = float(row["duration_s"]); steps = int(round(duration_s / dt_s))
    episode_load, regulation_load = load_profile(row, duration_s, dt_s)
    frequency_peak = 0.0; ace_iae = 0.0; tie_iae = 0.0
    frequency_normalized_ise = 0.0
    ace_normalized_ise = 0.0
    tie_normalized_ise = 0.0
    sg_mileage = 0.0; bess_throughput = 0.0
    previous_mechanical = state.mechanical_power_pu.copy()
    hard = False; command_violation = False; trace_rows = []
    valve_boundary_steps = 0; sg_boundary_steps = 0
    grc_active_steps = 0; bess_power_saturation_steps = 0
    bess_ramp_saturation_steps = 0; contract_violation_steps = 0
    terminal_frequency: list[float] = []; terminal_ace: list[float] = []
    for step in range(steps + 1):
        time_s = step * dt_s
        public = plant.public_observation(time_s, state, command)
        if time_s + 1e-10 >= next_poi_observation:
            poi_noise_state = (
                poi_noise_correlation * poi_noise_state
                + np.sqrt(1.0 - poi_noise_correlation ** 2)
                * poi_rng.normal(0.0, float(row["poi_noise_std_pu"]), 2)
            )
            controller.observe_actual(noisy_observation(
                public,
                poi_rng,
                float(row["frequency_noise_std_hz"]),
                float(row["poi_noise_std_pu"]),
                frequency_noise_hz=poi_rng.normal(
                    0.0, float(row["frequency_noise_std_hz"]), 2
                ),
                poi_noise_pu=poi_noise_state,
            ))
            next_poi_observation += poi_observation_period_s
        if time_s + 1e-10 >= next_control:
            causal = noisy_observation(
                public, control_rng, float(row["frequency_noise_std_hz"]),
                float(row["poi_noise_std_pu"]),
            )
            if method == "perfect_capability_oracle":
                command = controller.propose_with_truth(causal, capability_at(row, time_s))
            else:
                command = controller.propose(causal)
            command_violation |= bool(
                np.any(command[[0, 2]] < np.asarray(parameters.valve_lower_pu) - 1e-9)
                or np.any(command[[0, 2]] > np.asarray(parameters.valve_upper_pu) + 1e-9)
                or np.any(np.abs(command[[1, 3]]) > parameters.bess.rating_pu + 1e-9)
            )
            if trace_path is not None:
                trace_rows.append({
                    "time_s": time_s,
                    "frequency0_hz": public.frequency_deviation_hz[0],
                    "frequency1_hz": public.frequency_deviation_hz[1],
                    "ace0_pu": public.ace_pu[0], "ace1_pu": public.ace_pu[1],
                    "tie_pu": public.tie_line_pu,
                    "sg0_pu": command[0], "bess0_pu": command[1],
                    "sg1_pu": command[2], "bess1_pu": command[3],
                    "actual_bess0_pu": public.bess_actual_power_pu[0],
                    "actual_bess1_pu": public.bess_actual_power_pu[1],
                })
            next_control += template.period_s
        frequency_peak = max(
            frequency_peak, float(np.max(np.abs(public.frequency_deviation_hz)))
        )
        ace_iae += float(np.sum(np.abs(public.ace_pu))) * dt_s
        tie_iae += abs(float(public.tie_line_pu)) * dt_s
        frequency_normalized_ise += float(np.sum(
            (public.frequency_deviation_hz / 0.20) ** 2
        )) * dt_s
        ace_normalized_ise += float(np.sum((public.ace_pu / 0.05) ** 2)) * dt_s
        tie_normalized_ise += float((public.tie_line_pu / 0.025) ** 2) * dt_s
        if time_s >= duration_s - 30.0:
            terminal_frequency.append(float(np.max(np.abs(public.frequency_deviation_hz))))
            terminal_ace.append(float(np.max(np.abs(public.ace_pu))))
        if step < steps:
            state, diagnostics = plant.step(
                state, command, episode_load[step], capability_at(row, time_s),
                np.zeros(2),
            )
            sg_mileage += float(np.sum(np.abs(state.mechanical_power_pu - previous_mechanical)))
            previous_mechanical = state.mechanical_power_pu.copy()
            bess_throughput += float(np.sum(np.abs(state.bess.power_pu))) * dt_s
            valve_boundary_steps += int(np.any(diagnostics.valve_boundary_active))
            sg_boundary_steps += int(np.any(diagnostics.sg_boundary_active))
            grc_active_steps += int(np.any(diagnostics.grc_active))
            bess_power_saturation_steps += int(np.any(diagnostics.bess.power_saturation))
            bess_ramp_saturation_steps += int(np.any(diagnostics.bess.ramp_saturation))
            contract_violation_steps += int(diagnostics.bess.contract_violation_truth)
            # Boundary activation and capability saturation are physical
            # operating modes, not violations.  A hard violation means the
            # state or issued command actually crossed a registered bound.
            hard |= bool(
                np.any(state.valve_pu < np.asarray(parameters.valve_lower_pu) - 1e-9)
                or np.any(state.valve_pu > np.asarray(parameters.valve_upper_pu) + 1e-9)
                or np.any(state.mechanical_power_pu < np.asarray(parameters.sg_power_lower_pu) - 1e-9)
                or np.any(state.mechanical_power_pu > np.asarray(parameters.sg_power_upper_pu) + 1e-9)
                or np.any(state.bess.measured_soc(parameters.bess) < parameters.bess.soc_min - 1e-9)
                or np.any(state.bess.measured_soc(parameters.bess) > parameters.bess.soc_max + 1e-9)
            )
    terminal_recovery = bool(
        max(terminal_frequency, default=np.inf) <= 0.12
        and max(terminal_ace, default=np.inf) <= 0.06
    )
    controller_diagnostics = asdict(controller.diagnostics())
    result = dict(row)
    result.update(
        method=method, plant="A_full_nonlinear",
        physical_success=bool(
            not hard and not command_violation and frequency_peak <= 1.0 and terminal_recovery
        ),
        frequency_peak_hz=frequency_peak, ace_iae_pu_s=ace_iae,
        tie_iae_pu_s=tie_iae, sg_mechanical_mileage_pu=sg_mileage,
        bess_energy_throughput_pu_s=bess_throughput,
        regulation_load_rms_pu=float(np.sqrt(np.mean(regulation_load ** 2))),
        regulation_load_peak_pu=float(np.max(np.abs(regulation_load))),
        total_load_peak_pu=float(np.max(np.abs(episode_load))),
        poi_observation_period_s=poi_observation_period_s,
        poi_noise_correlation=poi_noise_correlation,
        frequency_normalized_ise_s=frequency_normalized_ise,
        ace_normalized_ise_s=ace_normalized_ise,
        tie_normalized_ise_s=tie_normalized_ise,
        grid_service_cost_s=(
            frequency_normalized_ise
            + ace_normalized_ise
            + tie_normalized_ise
        ),
        hard_violation=hard, command_violation=command_violation,
        valve_boundary_steps=valve_boundary_steps,
        sg_boundary_steps=sg_boundary_steps,
        grc_active_steps=grc_active_steps,
        bess_power_saturation_steps=bess_power_saturation_steps,
        bess_ramp_saturation_steps=bess_ramp_saturation_steps,
        contract_violation_steps=contract_violation_steps,
        terminal_recovery=terminal_recovery,
        **controller_diagnostics,
    )
    if trace_path is not None:
        import pandas as pd

        trace_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(trace_rows).to_parquet(trace_path, index=False, compression="zstd")
    return result


__all__ = ["capability_at", "load_at", "load_profile", "simulate_plant_a"]
