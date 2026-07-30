"""Independent reproduction of decisive Phase-D audit findings.

Run from the Phase-D source root with its package installed, or pass
--source-root to prepend `<root>/src` to sys.path.

This script is evidence-only. It does not modify the project.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np


def configure_import(source_root: str | None) -> None:
    if source_root:
        sys.path.insert(0, str(Path(source_root).resolve() / "src"))


def nominal_closed_loop(mode: str, duration_s: float, initial_omega: float, background: bool) -> dict[str, float]:
    from direction1freq.models import CapabilityRegime, TwoAreaPlantA
    from direction1freq.models.plant_a import PlantAState

    dt = 0.05
    control_period = 2.0
    plant = TwoAreaPlantA(dt_s=dt)
    state = plant.equilibrium()
    if initial_omega:
        state = PlantAState(
            np.array([initial_omega, 0.0]), state.tie_pu, state.valve_pu,
            state.mechanical_power_pu, state.bess,
        )
    integral = np.zeros(2)
    command = np.zeros(4)
    next_control = 0.0
    frequencies, aces, commands = [], [], []
    for step in range(int(round(duration_s / dt))):
        time_s = step * dt
        if time_s + 1e-12 >= next_control:
            ace = plant.ace(state)
            integral = np.clip(integral + control_period * ace, -0.12, 0.12)
            request = np.clip(-1.4 * ace - 0.18 * integral, -0.10, 0.10)
            if mode == "registered":
                command = np.array([0.35 * request[0], 0.65 * request[0], 0.35 * request[1], 0.65 * request[1]])
            elif mode == "sg_only":
                command = np.array([request[0], 0.0, request[1], 0.0])
            elif mode == "bess_only":
                command = np.array([0.0, request[0], 0.0, request[1]])
            elif mode == "none":
                command = np.zeros(4)
            else:
                raise ValueError(mode)
            next_control += control_period
        load = (
            0.0015 * np.array([
                np.sin(2 * np.pi * time_s / 27.0 + 0.3),
                np.sin(2 * np.pi * time_s / 31.0 + 1.2),
            ]) if background else np.zeros(2)
        )
        state, _ = plant.step(state, command, load, CapabilityRegime())
        frequencies.append(plant.params.nominal_frequency_hz * state.omega_pu.copy())
        aces.append(plant.ace(state).copy())
        commands.append(command.copy())
    frequency = np.asarray(frequencies)
    ace = np.asarray(aces)
    command_array = np.asarray(commands)
    return {
        "max_abs_frequency_hz": float(np.max(np.abs(frequency))),
        "rms_frequency_hz": float(np.sqrt(np.mean(frequency**2))),
        "terminal_max_abs_frequency_hz": float(np.max(np.abs(frequency[-1]))),
        "max_abs_ace_pu": float(np.max(np.abs(ace))),
        "max_abs_command_pu": float(np.max(np.abs(command_array))),
    }


def delay_update_replay(seed: int = 100) -> dict[str, object]:
    from direction1freq.estimation import AugmentedLoadKalman
    from direction1freq.identification import CausalCapabilitySetEstimator
    from direction1freq.models import CapabilityRegime, TwoAreaPlantA

    dt = 0.05
    change_time = 45.0
    duration = 120.0
    control_period = 2.0
    rng = np.random.default_rng(seed)
    plant = TwoAreaPlantA(dt_s=dt)
    state = plant.equilibrium(soc=(float(rng.uniform(0.4, 0.6)), 0.5))
    estimator = CausalCapabilitySetEstimator(
        dt_s=dt, noise_bound_pu=0.0025, cusum_drift=1.5, cusum_threshold=12.0
    )
    load_filter = AugmentedLoadKalman(dt_s=dt, measurement_std=(3e-5, 3e-5, 3e-4))
    command = np.zeros(4)
    integral = np.zeros(2)
    next_control = 0.0
    load_size = float(rng.uniform(0.045, 0.060))
    phases = rng.uniform(0, 2 * np.pi, size=2)
    first_candidate_change = None
    first_truth_singleton = None
    first_alarm = None
    evaluator_update_time = None
    control_loss_time = None
    deficit_area = 0.0
    previous_candidates = estimator.delay_candidates

    for step in range(int(round(duration / dt))):
        time_s = step * dt
        background = 0.0015 * np.array([
            np.sin(2 * np.pi * time_s / 27.0 + phases[0]),
            np.sin(2 * np.pi * time_s / 31.0 + phases[1]),
        ])
        load = background + np.array([load_size if time_s >= 50.0 else 0.0, 0.0])
        if time_s + 1e-12 >= next_control:
            measured_ace = plant.ace(state) + rng.normal(0.0, 2e-4, size=2)
            integral = np.clip(integral + control_period * measured_ace, -0.12, 0.12)
            request = np.clip(-1.4 * measured_ace - 0.18 * integral, -0.10, 0.10)
            command = np.array([0.35 * request[0], 0.65 * request[0], 0.35 * request[1], 0.65 * request[1]])
            next_control += control_period
        regime = CapabilityRegime() if time_s < change_time else CapabilityRegime(delay_s=(1.0, 0.2))
        issued_total = float(-plant.params.bess.pfr_gain_pu_power_per_pu_frequency * state.omega_pu[0] + command[1])
        next_state, _ = plant.step(state, command, load, regime)
        observation = plant.observation(next_state, command)
        measured_frequency = observation[:2] + rng.normal(0.0, 0.0015, size=2)
        measured_tie = float(observation[4] + rng.normal(0.0, 1e-4))
        measured_pm = observation[5:7] + rng.normal(0.0, 2e-4, size=2)
        measured_pb = observation[7:9] + rng.normal(0.0, 0.0010, size=2)
        load_filter.update(
            measured_frequency, measured_tie,
            np.array([measured_pm[0], measured_pb[0], measured_pm[1], measured_pb[1]])
        )
        estimate = estimator.update(issued_total, measured_pb[0])
        if estimate.alarm and first_alarm is None:
            first_alarm = time_s
        # This is the Phase-D evaluator's actual semantics.
        if estimate.alarm and time_s >= change_time and evaluator_update_time is None:
            evaluator_update_time = time_s
        if time_s >= change_time and estimate.delay_candidates_s != previous_candidates and first_candidate_change is None:
            first_candidate_change = time_s
        previous_candidates = estimate.delay_candidates_s
        if (
            time_s >= change_time and first_truth_singleton is None
            and len(estimate.delay_candidates_s) == 1
            and abs(estimate.delay_candidates_s[0] - 1.0) <= dt / 2
        ):
            first_truth_singleton = time_s
        if time_s >= change_time:
            deficit_area += max(abs(issued_total) - abs(next_state.bess.power_pu[0]) - 0.004, 0.0) * dt
            if control_loss_time is None and deficit_area >= 0.015:
                control_loss_time = time_s
        state = next_state
    return {
        "seed": seed,
        "true_delay_change_time_s": change_time,
        "first_delay_candidate_set_change_s": first_candidate_change,
        "first_correct_singleton_delay_set_s": first_truth_singleton,
        "first_cusum_alarm_s": first_alarm,
        "phase_d_evaluator_update_time_s": evaluator_update_time,
        "phase_d_deficit_area_loss_time_s": control_loss_time,
        "finding": "delay set updates without alarm; Phase-D update-time scorer misses it",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", default=None)
    parser.add_argument("--output", default="independent_audit_results.json")
    args = parser.parse_args()
    configure_import(args.source_root)
    results = {
        "tiny_initial_perturbation_registered_pi": nominal_closed_loop("registered", 200.0, 1e-6, False),
        "background_no_sfr": nominal_closed_loop("none", 200.0, 0.0, True),
        "background_registered_pi": nominal_closed_loop("registered", 200.0, 0.0, True),
        "background_sg_only_pi": nominal_closed_loop("sg_only", 200.0, 0.0, True),
        "background_bess_only_pi": nominal_closed_loop("bess_only", 200.0, 0.0, True),
        "delay_update_replay": delay_update_replay(),
    }
    Path(args.output).write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
