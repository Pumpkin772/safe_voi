"""Event-triggered allocation-neutral safe capability probing."""

from __future__ import annotations

from dataclasses import dataclass
import ast
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from direction5freq.models.capability_contract import CapabilityRealization
from direction5freq.models.plant_a_full import PlantAFull


@dataclass(frozen=True, slots=True)
class CapabilityHypothesis:
    power_pu: float
    ramp_pu_per_s: float
    delay_s: float


@dataclass(frozen=True, slots=True)
class ProbeCandidate:
    probe_id: str
    amplitude_pu: float
    normalized_sequence: np.ndarray

    @property
    def sequence_pu(self) -> np.ndarray:
        return self.amplitude_pu * self.normalized_sequence


def load_probe_library(path: Path, amplitudes: list[float]) -> list[ProbeCandidate]:
    library = pd.read_csv(path)
    candidates = []
    for row in library.itertuples(index=False):
        sequence = np.asarray(ast.literal_eval(row.normalized_sequence), dtype=float)
        if abs(float(sequence.sum())) > 1e-12:
            continue
        for amplitude in amplitudes:
            candidates.append(ProbeCandidate(str(row.probe_id), float(amplitude), sequence))
    return candidates


def candidate_models(lock: dict) -> list[CapabilityHypothesis]:
    return [
        CapabilityHypothesis(float(power), float(ramp), float(delay))
        for power, ramp, delay in product(
            lock["power_candidates_pu"],
            lock["ramp_candidates_pu_per_s"],
            lock["delay_candidates_s"],
        )
    ]


def allocation_neutral_action(base_action: np.ndarray, q_pu: float) -> np.ndarray:
    action = np.asarray(base_action, dtype=float).copy()
    action[0] -= float(q_pu)
    action[1] += float(q_pu)
    if abs(float(action[0] + action[1] - base_action[0] - base_action[1])) > 1e-12:
        raise RuntimeError("probe violated command-level allocation neutrality")
    return action


def _command_at(time_s: float, probe: ProbeCandidate, period_s: float, base_power: float) -> float:
    if time_s < 0.0:
        return float(base_power)
    index = int(time_s // period_s)
    q = probe.sequence_pu[index] if index < len(probe.sequence_pu) else 0.0
    return float(base_power + q)


def simulate_hypothesis(
    hypothesis: CapabilityHypothesis,
    probe: ProbeCandidate,
    *,
    period_s: float,
    dt_s: float,
    base_power_pu: float,
) -> np.ndarray:
    duration = len(probe.sequence_pu) * period_s + hypothesis.delay_s + 0.5
    steps = int(round(duration / dt_s)) + 1
    power = float(base_power_pu)
    values = np.zeros(steps)
    for step in range(steps):
        time_s = step * dt_s
        delayed = _command_at(time_s - hypothesis.delay_s, probe, period_s, base_power_pu)
        target = float(np.clip(delayed, -hypothesis.power_pu, hypothesis.power_pu))
        raw_rate = (target - power) / 0.15
        rate = float(np.clip(raw_rate, -hypothesis.ramp_pu_per_s, hypothesis.ramp_pu_per_s))
        power += dt_s * rate
        power = min(power, target) if target >= values[max(step - 1, 0)] else max(power, target)
        values[step] = power
    return values


def filter_models(
    models: list[CapabilityHypothesis],
    measured: np.ndarray,
    probe: ProbeCandidate,
    *,
    period_s: float,
    dt_s: float,
    base_power_pu: float,
    residual_bound_pu: float,
) -> list[CapabilityHypothesis]:
    retained = []
    for model in models:
        predicted = simulate_hypothesis(
            model, probe, period_s=period_s, dt_s=dt_s, base_power_pu=base_power_pu
        )
        count = min(len(predicted), len(measured))
        if np.max(np.abs(predicted[:count] - measured[:count])) <= residual_bound_pu:
            retained.append(model)
    return retained


def normalized_diameter(models: list[CapabilityHypothesis], lock: dict) -> float:
    if len(models) <= 1:
        return 0.0
    power = np.asarray([model.power_pu for model in models])
    ramp = np.asarray([model.ramp_pu_per_s for model in models])
    delay = np.asarray([model.delay_s for model in models])
    weights = lock["diameter_weights"]
    power_range = max(lock["power_candidates_pu"]) - min(lock["power_candidates_pu"])
    ramp_range = max(lock["ramp_candidates_pu_per_s"]) - min(lock["ramp_candidates_pu_per_s"])
    delay_range = max(lock["delay_candidates_s"]) - min(lock["delay_candidates_s"])
    return float(
        weights["power"] * np.ptp(power) / power_range
        + weights["ramp"] * np.ptp(ramp) / ramp_range
        + weights["delay"] * np.ptp(delay) / delay_range
    )


def identification_result(
    truth: CapabilityHypothesis,
    probe: ProbeCandidate,
    models: list[CapabilityHypothesis],
    lock: dict,
    rng: np.random.Generator | None = None,
) -> dict:
    measured = simulate_hypothesis(
        truth, probe, period_s=float(lock["period_s"]),
        dt_s=float(lock["identification_dt_s"]),
        base_power_pu=float(lock["base_action_pu"][1]),
    )
    if rng is not None:
        measured = measured + rng.uniform(
            -float(lock["measurement_noise_bound_pu"]),
            float(lock["measurement_noise_bound_pu"]), len(measured),
        )
    bound = float(lock["measurement_noise_bound_pu"]) + float(lock["model_residual_bound_pu"])
    retained = filter_models(
        models, measured, probe, period_s=float(lock["period_s"]),
        dt_s=float(lock["identification_dt_s"]),
        base_power_pu=float(lock["base_action_pu"][1]), residual_bound_pu=bound,
    )
    before = normalized_diameter(models, lock)
    after = normalized_diameter(retained, lock)
    contained = truth in retained
    certified_power = min((m.power_pu for m in retained), default=float("nan"))
    certified_ramp = min((m.ramp_pu_per_s for m in retained), default=float("nan"))
    certified_delay = max((m.delay_s for m in retained), default=float("nan"))
    return {
        "models_before": len(models), "models_after": len(retained),
        "diameter_before": before, "diameter_after": after,
        "diameter_reduction": 0.0 if before <= 0 else (before - after) / before,
        "truth_contained": contained,
        "false_optimism": bool(
            not retained or certified_power > truth.power_pu
            or certified_ramp > truth.ramp_pu_per_s or certified_delay < truth.delay_s
        ),
        "certified_power_pu": certified_power,
        "certified_ramp_pu_per_s": certified_ramp,
        "certified_max_delay_s": certified_delay,
    }


def _plant_trace(
    probe: ProbeCandidate,
    hypothesis: CapabilityHypothesis,
    lock: dict,
    *,
    apply_probe: bool,
) -> dict:
    dt_s = float(lock["physical_dt_s"])
    duration = float(lock["episode_duration_s"])
    start = float(lock["probe_start_s"])
    period = float(lock["period_s"])
    plant = PlantAFull(dt_s=dt_s)
    state = plant.equilibrium()
    base = np.asarray(lock["base_action_pu"], dtype=float)
    load = np.asarray(lock["base_load_pu"], dtype=float)
    truth = CapabilityRealization(
        lower_power_pu=(-hypothesis.power_pu, -0.080),
        upper_power_pu=(hypothesis.power_pu, 0.080),
        ramp_down_pu_per_s=(hypothesis.ramp_pu_per_s, 0.060),
        ramp_up_pu_per_s=(hypothesis.ramp_pu_per_s, 0.060),
        delay_s=(hypothesis.delay_s, 0.20),
    )
    frequency = []
    ace = []
    tie = []
    hard = False
    steps = int(round(duration / dt_s))
    for step in range(steps + 1):
        time_s = step * dt_s
        observation = plant.public_observation(time_s, state, base)
        frequency.append(observation.frequency_deviation_hz.copy())
        ace.append(observation.ace_pu.copy())
        tie.append(observation.tie_line_pu)
        if step == steps:
            break
        q = 0.0
        if apply_probe and start <= time_s < start + len(probe.sequence_pu) * period:
            q = float(probe.sequence_pu[int((time_s - start) // period)])
        action = allocation_neutral_action(base, q)
        state, _ = plant.step(state, action, load, truth, np.zeros(2))
        soc = state.bess.measured_soc(plant.parameters.bess)
        hard |= bool(
            np.any(soc < plant.parameters.bess.soc_min - 1e-9)
            or np.any(soc > plant.parameters.bess.soc_max + 1e-9)
            or np.any(state.mechanical_power_pu > np.asarray(plant.parameters.sg_power_upper_pu) + 1e-9)
        )
    return {
        "frequency": np.asarray(frequency), "ace": np.asarray(ace),
        "tie": np.asarray(tie), "hard_violation": hard,
    }


def safety_result(probe: ProbeCandidate, hypothesis: CapabilityHypothesis, lock: dict) -> dict:
    baseline = _plant_trace(probe, hypothesis, lock, apply_probe=False)
    tested = _plant_trace(probe, hypothesis, lock, apply_probe=True)
    dt_s = float(lock["physical_dt_s"])
    start_index = int(round(float(lock["probe_start_s"]) / dt_s))
    end_index = start_index + int(round(len(probe.sequence_pu) * float(lock["period_s"]) / dt_s)) + 1
    freq_delta = tested["frequency"][start_index:end_index] - baseline["frequency"][start_index:end_index]
    ace_delta = tested["ace"][start_index:end_index] - baseline["ace"][start_index:end_index]
    tie_delta = tested["tie"][start_index:end_index] - baseline["tie"][start_index:end_index]
    normalization = float(np.sum(np.abs(lock["base_load_pu"]))) * len(probe.sequence_pu) * float(lock["period_s"])
    return {
        "incremental_frequency_peak_hz": float(np.max(np.abs(freq_delta))),
        "incremental_ace_fraction": float(np.sum(np.abs(ace_delta)) * dt_s / normalization),
        "incremental_tie_fraction": float(np.sum(np.abs(tie_delta)) * dt_s / normalization),
        "hard_violation": bool(tested["hard_violation"]),
    }


def safety_pass(result: dict, lock: dict) -> bool:
    gates = lock["gates"]
    return bool(
        not result["hard_violation"]
        and result["incremental_frequency_peak_hz"] <= gates["incremental_frequency_hz_max"]
        and result["incremental_ace_fraction"] <= gates["incremental_ace_fraction_max"]
        and result["incremental_tie_fraction"] <= gates["incremental_tie_fraction_max"]
    )


__all__ = [
    "CapabilityHypothesis", "ProbeCandidate", "allocation_neutral_action",
    "candidate_models", "filter_models", "identification_result",
    "load_probe_library", "normalized_diameter", "safety_pass", "safety_result",
    "simulate_hypothesis",
]

