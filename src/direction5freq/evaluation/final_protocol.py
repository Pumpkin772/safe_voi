"""Locked factor-explicit manifests and physical profiles for Direction5 R5."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from direction5freq.models.capability_contract import CapabilityRealization
from direction5freq.models.plant_a_full import PlantAParameters


MECHANISMS = ("power_drop", "ramp_drop", "delay_increase")
TENSIONS = ("low", "high")
PERIODS_S = (2.0, 4.0)


def plant_parameters(tension: str, nominal_frequency_hz: float = 50.0) -> PlantAParameters:
    base = PlantAParameters(nominal_frequency_hz=nominal_frequency_hz)
    if tension == "low":
        return base
    if tension == "high":
        return replace(
            base,
            valve_upper_pu=(0.105, 0.105),
            sg_power_upper_pu=(0.090, 0.090),
            grc_up_pu_per_s=(0.009, 0.009),
        )
    raise ValueError(f"unknown SG tension: {tension}")


def _independent_permutation(values: list, seed_parts: tuple[int, ...], factor: int) -> np.ndarray:
    rng = np.random.default_rng(np.random.SeedSequence((*seed_parts, factor)))
    return np.asarray(values, dtype=object)[rng.permutation(len(values))]


def build_plant_a_manifest(split: str) -> pd.DataFrame:
    if split not in {"development", "validation"}:
        raise ValueError(split)
    local_seeds = range(0, 1) if split == "development" else range(30, 40)
    rows = []
    scenario_index = 0
    for mechanism_index, mechanism in enumerate(MECHANISMS):
        for tension_index, tension in enumerate(TENSIONS):
            for period_index, period_s in enumerate(PERIODS_S):
                count = len(local_seeds)
                seed_parts = (20260804, 701, mechanism_index, tension_index, period_index, count)
                rng = np.random.default_rng(np.random.SeedSequence((*seed_parts, 0)))
                magnitude_class = _independent_permutation(
                    (["sustainable"] * 5 + ["bridge"] * 3 + ["infeasible"] * 2)[:count]
                    if count == 1 else
                    ["sustainable"] * 5 + ["bridge"] * 3 + ["infeasible"] * 2,
                    seed_parts, 1,
                )
                timing = _independent_permutation(
                    (["before"] if count == 1 else ["before"] * 4 + ["after"] * 3 + ["simultaneous"] * 3),
                    seed_parts, 2,
                )
                area = _independent_permutation(
                    (["both"] if count == 1 else ["area0"] * 4 + ["area1"] * 3 + ["both"] * 3),
                    seed_parts, 3,
                )
                sign = _independent_permutation(
                    ([1] if count == 1 else [1] * 7 + [-1] * 3), seed_parts, 4
                )
                condition = _independent_permutation(
                    (["known"] if count == 1 else ["known"] * 5 + ["OOD"] * 5),
                    seed_parts, 5,
                )
                soc = _independent_permutation(
                    ([0.50] if count == 1 else [0.35, 0.50, 0.65, 0.35, 0.50, 0.65, 0.35, 0.50, 0.65, 0.50]),
                    seed_parts, 6,
                )
                noise = _independent_permutation(
                    ([0.0] if count == 1 else [0.0, 0.0, 0.0001, 0.0001, 0.0002, 0.0002, 0.0, 0.0001, 0.0002, 0.0]),
                    seed_parts, 7,
                )
                jitter = _independent_permutation(
                    ([0.0] if count == 1 else [0.0, 0.0, 0.01, 0.01, 0.02, 0.02, 0.0, 0.01, 0.02, 0.0]),
                    seed_parts, 8,
                )
                dropout = _independent_permutation(
                    ([0.0] if count == 1 else [0.0, 0.0, 0.0, 0.001, 0.001, 0.002, 0.0, 0.001, 0.002, 0.0]),
                    seed_parts, 9,
                )
                repeated = _independent_permutation(
                    ([False] if count == 1 else [True, True] + [False] * 8), seed_parts, 10
                )
                for local_index, seed in enumerate(local_seeds):
                    capability_time = float(rng.uniform(100.0, 135.0))
                    relation = str(timing[local_index])
                    if relation == "before":
                        load_time = capability_time - float(rng.uniform(10.0, 22.0))
                    elif relation == "after":
                        load_time = capability_time + float(rng.uniform(10.0, 22.0))
                    else:
                        load_time = capability_time
                    rows.append({
                        "scenario_id": f"R5-{split[0].upper()}-A-{scenario_index:03d}",
                        "split": split,
                        "seed": int(seed),
                        "plant": "A_full_nonlinear",
                        "mechanism": mechanism,
                        "sg_tension": tension,
                        "period_s": period_s,
                        "duration_s": 300.0,
                        "magnitude_class": str(magnitude_class[local_index]),
                        "timing_relation": relation,
                        "load_area": str(area[local_index]),
                        "load_sign": int(sign[local_index]),
                        "condition": str(condition[local_index]),
                        "capability_change_time_s": capability_time,
                        "load_event_time_s": load_time,
                        "second_capability_change_time_s": (
                            capability_time + 82.0 if bool(repeated[local_index]) else np.nan
                        ),
                        "initial_soc": float(soc[local_index]),
                        "frequency_noise_std_hz": float(noise[local_index]),
                        "control_jitter_s": float(jitter[local_index]),
                        "dropout_probability": float(dropout[local_index]),
                        "nominal_warmup_s": 60.0,
                        "factor_assignment": "INDEPENDENT_REGISTERED_PER_FACTOR_PERMUTATIONS",
                        "contract_violation": False,
                    })
                    scenario_index += 1
    return pd.DataFrame(rows)


def build_plant_b_manifest() -> pd.DataFrame:
    rows = []
    index = 0
    for mechanism_index, mechanism in enumerate(MECHANISMS):
        count = 8
        seed_parts = (20260804, 719, mechanism_index)
        rng = np.random.default_rng(np.random.SeedSequence((*seed_parts, 0)))
        periods = _independent_permutation([2.0] * 4 + [4.0] * 4, seed_parts, 1)
        signs = _independent_permutation([1] * 5 + [-1] * 3, seed_parts, 2)
        areas = _independent_permutation(["area0"] * 3 + ["area1"] * 3 + ["both"] * 2, seed_parts, 3)
        conditions = _independent_permutation(["known"] * 4 + ["OOD"] * 4, seed_parts, 4)
        operating = _independent_permutation(["base"] * 4 + ["stressed"] * 4, seed_parts, 5)
        noise = _independent_permutation([0.0] * 4 + [0.00015] * 4, seed_parts, 6)
        jitter = _independent_permutation([0.0] * 4 + [0.01] * 4, seed_parts, 7)
        for local_index, seed in enumerate(range(30, 38)):
            capability_time = float(rng.uniform(100.0, 130.0))
            relation = ("before", "after", "simultaneous")[local_index % 3]
            load_time = capability_time + (-14.0 if relation == "before" else 14.0 if relation == "after" else 0.0)
            rows.append({
                "scenario_id": f"R5-V-B-{index:03d}",
                "split": "validation",
                "seed": seed,
                "plant": "B_native_ANDES_Kundur",
                "mechanism": mechanism,
                "sg_tension": str(operating[local_index]),
                "operating_point": str(operating[local_index]),
                "period_s": float(periods[local_index]),
                "duration_s": 300.0,
                "magnitude_class": "sustainable",
                "timing_relation": relation,
                "load_area": str(areas[local_index]),
                "load_sign": int(signs[local_index]),
                "condition": str(conditions[local_index]),
                "capability_change_time_s": capability_time,
                "load_event_time_s": load_time,
                "second_capability_change_time_s": np.nan,
                "initial_soc": float(rng.choice([0.40, 0.50, 0.60])),
                "frequency_noise_std_hz": float(noise[local_index]),
                "control_jitter_s": float(jitter[local_index]),
                "dropout_probability": 0.001 if local_index in (2, 6) else 0.0,
                "nominal_warmup_s": 60.0,
                "factor_assignment": "INDEPENDENT_REGISTERED_PER_FACTOR_PERMUTATIONS",
                "contract_violation": False,
            })
            index += 1
    return pd.DataFrame(rows)


def build_normal_manifest() -> pd.DataFrame:
    rows = []
    for index, seed in enumerate(range(40, 46)):
        rows.append({
            "scenario_id": f"R5-N-{index:02d}",
            "split": "validation",
            "seed": seed,
            "plant": "A_full_nonlinear",
            "mechanism": MECHANISMS[index % 3],
            "sg_tension": "low",
            "period_s": 4.0,
            "duration_s": 3600.0,
            "magnitude_class": "normal_profile",
            "timing_relation": "independent_profile",
            "load_area": "both",
            "load_sign": 1,
            "condition": "known" if index < 3 else "OOD",
            "capability_change_time_s": 1100.0 + 100.0 * index,
            "load_event_time_s": 0.0,
            "second_capability_change_time_s": 2400.0 + 40.0 * index,
            "initial_soc": 0.50,
            "frequency_noise_std_hz": 0.0001,
            "control_jitter_s": 0.01,
            "dropout_probability": 0.001,
            "nominal_warmup_s": 60.0,
            "factor_assignment": "REGISTERED_SYNTHETIC_PROFILE_FACTORS",
            "profile_provenance": "SYNTHETIC_AR2_MULTI_SINE_REGISTERED_NOT_PUBLIC_MEASURED",
            "contract_violation": False,
        })
    return pd.DataFrame(rows)


def build_contract_violation_manifest() -> pd.DataFrame:
    base = build_plant_a_manifest("development").iloc[:6].copy()
    base["scenario_id"] = [f"R5-CV-{index:02d}" for index in range(len(base))]
    base["split"] = "validation_contract_violation_separate"
    base["seed"] = np.arange(50, 50 + len(base))
    base["contract_violation"] = True
    base["magnitude_class"] = "bridge"
    base["load_sign"] = 1
    base["condition"] = "contract_violation"
    return base


def capability_for(row: pd.Series, time_s: float) -> CapabilityRealization:
    nominal = CapabilityRealization()
    if time_s < float(row.capability_change_time_s):
        return nominal
    if bool(row.get("contract_violation", False)):
        return CapabilityRealization(
            lower_power_pu=(-0.020, -0.020),
            upper_power_pu=(0.020, 0.020),
            ramp_down_pu_per_s=(0.010, 0.010),
            ramp_up_pu_per_s=(0.010, 0.010),
            delay_s=(2.0, 2.0),
        )
    condition = str(row.condition)
    if row.mechanism == "power_drop":
        value = 0.052 if condition == "known" else 0.047
        changed = CapabilityRealization(
            lower_power_pu=(-value, -0.96 * value),
            upper_power_pu=(value, 0.96 * value),
            ramp_down_pu_per_s=(0.055, 0.052),
            ramp_up_pu_per_s=(0.055, 0.052),
            delay_s=(0.25, 0.30),
        )
    elif row.mechanism == "ramp_drop":
        value = 0.034 if condition == "known" else 0.027
        changed = CapabilityRealization(
            lower_power_pu=(-0.075, -0.072),
            upper_power_pu=(0.075, 0.072),
            ramp_down_pu_per_s=(value, 0.96 * value),
            ramp_up_pu_per_s=(value, 0.96 * value),
            delay_s=(0.25, 0.30),
        )
    elif row.mechanism == "delay_increase":
        value = 1.10 if condition == "known" else 1.45
        changed = CapabilityRealization(
            lower_power_pu=(-0.075, -0.072),
            upper_power_pu=(0.075, 0.072),
            ramp_down_pu_per_s=(0.055, 0.052),
            ramp_up_pu_per_s=(0.055, 0.052),
            delay_s=(value, min(value + 0.05, 1.50)),
        )
    else:
        raise ValueError(str(row.mechanism))
    second = row.second_capability_change_time_s
    if pd.notna(second) and time_s >= float(second):
        return CapabilityRealization(
            lower_power_pu=tuple(np.minimum(np.asarray(changed.lower_power_pu) * 1.08, -0.045)),
            upper_power_pu=tuple(np.maximum(np.asarray(changed.upper_power_pu) * 1.08, 0.045)),
            ramp_down_pu_per_s=tuple(np.maximum(np.asarray(changed.ramp_down_pu_per_s) * 1.08, 0.025)),
            ramp_up_pu_per_s=tuple(np.maximum(np.asarray(changed.ramp_up_pu_per_s) * 1.08, 0.025)),
            delay_s=tuple(np.maximum(np.asarray(changed.delay_s) - 0.15, 0.10)),
        )
    return changed


def load_for(row: pd.Series, parameters: PlantAParameters, time_s: float) -> np.ndarray:
    if time_s < float(row.load_event_time_s):
        return np.zeros(2)
    sign = int(row.load_sign)
    if row.magnitude_class == "sustainable":
        limit = min(parameters.sg_power_upper_pu) if sign > 0 else abs(max(parameters.sg_power_lower_pu))
        magnitude = 0.58 * limit
    elif row.magnitude_class == "bridge":
        magnitude = (
            min(parameters.sg_power_upper_pu) + 0.028
            if sign > 0 else abs(max(parameters.sg_power_lower_pu)) + 0.018
        )
    elif row.magnitude_class == "infeasible":
        magnitude = (
            min(parameters.sg_power_upper_pu) + max(parameters.slow_reserve.upper_pu) + 0.022
            if sign > 0 else abs(max(parameters.sg_power_lower_pu)) + 0.025
        )
    else:
        raise ValueError(str(row.magnitude_class))
    signed = sign * magnitude
    if row.load_area == "area0":
        return np.array((signed, 0.25 * signed))
    if row.load_area == "area1":
        return np.array((0.25 * signed, signed))
    return np.array((signed, 0.78 * signed))


def synthetic_normal_profile(seed: int) -> np.ndarray:
    rng = np.random.default_rng(np.random.SeedSequence([20260804, seed, 733]))
    values = np.zeros((3601, 2))
    innovations = rng.normal(0.0, 0.00035, (3601, 2))
    for index in range(1, 3601):
        values[index] = 0.990 * values[index - 1] + innovations[index]
    time_s = np.arange(3601)
    values += np.column_stack((
        0.0045 * np.sin(2 * np.pi * time_s / 820.0),
        0.0040 * np.sin(2 * np.pi * time_s / 970.0 + 0.4),
    ))
    return np.clip(values, -0.015, 0.015)


__all__ = [
    "MECHANISMS", "TENSIONS", "PERIODS_S", "plant_parameters",
    "build_plant_a_manifest", "build_plant_b_manifest", "build_normal_manifest",
    "build_contract_violation_manifest", "capability_for", "load_for",
    "synthetic_normal_profile",
]
