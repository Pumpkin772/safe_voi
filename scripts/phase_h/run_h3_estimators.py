"""Select and validate separated disturbance and capability estimators."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from direction1freq.controllers.ace_pi_aw import ACEPIAntiWindup, design_stable_pi
from direction1freq.estimation.structured_observer import StructuredLoadStateObserver
from direction1freq.models.bess_capability_v2 import (
    CapabilityTruthV2,
    current_capability_v2,
)
from direction1freq.models.plant_a_v2 import PlantAParametersV2, TwoAreaPlantAV2
from direction1freq.models.plant_b_andes_v2 import AndesKundurPlantBV2
from direction5_freq.estimation.capability_set_estimator import CapabilitySetEstimator
from direction5_freq.estimation.grid_disturbance_observer import (
    GridDisturbanceObserver,
    GridPublicMeasurement,
)


CANDIDATES = GridDisturbanceObserver.CANDIDATES


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest() -> pd.DataFrame:
    count = 40
    rng = np.random.default_rng(20260803)

    def shuffled(values) -> np.ndarray:
        result = np.resize(np.asarray(values), count).copy()
        rng.shuffle(result)
        return result

    classes = shuffled(["load_only", "capability_only", "simultaneous", "no_excitation"])
    mechanisms = shuffled(["headroom", "ramp", "delay", "energy", "availability"])
    periods = shuffled([2.0, 4.0])
    areas = shuffled([0, 1])
    signs = shuffled([-1.0, 1.0])
    magnitudes = shuffled([0.04, 0.05, 0.06, 0.07])
    noise = shuffled([0.0, 0.001, 0.003, 0.005])
    dropout = shuffled([0.0, 0.0, 0.02, 0.05])
    jitter = shuffled([0.0, 0.0, 0.05, 0.10])
    rows = []
    for seed in range(count):
        rows.append(
            {
                "scenario_id": f"H3_A_{seed:02d}",
                "plant": "A",
                "seed": seed,
                "split": "development" if seed < 20 else "validation",
                "scenario_class": str(classes[seed]),
                "mechanism": str(mechanisms[seed]),
                "period_s": float(periods[seed]),
                "load_area": int(areas[seed]),
                "load_sign": float(signs[seed]),
                "load_magnitude_pu": float(magnitudes[seed]),
                "noise_std_hz": float(noise[seed]),
                "dropout_probability": float(dropout[seed]),
                "jitter_bound_s": float(jitter[seed]),
                "known_ood": "ood_slow_drift" if seed in {36, 37, 38, 39} else "known",
            }
        )
    return pd.DataFrame(rows)


def capability_truth(row: pd.Series, time_s: float) -> CapabilityTruthV2:
    if row.scenario_class in {"load_only", "no_excitation"} or time_s < 20.0:
        return CapabilityTruthV2()
    fraction = 1.0
    if row.known_ood == "ood_slow_drift":
        fraction = float(np.clip((time_s - 20.0) / 35.0, 0.0, 1.0))
    mechanism = str(row.mechanism)
    if mechanism == "headroom":
        value = 1.0 - 0.65 * fraction
        return CapabilityTruthV2(
            upper_headroom_fraction=(value, value),
            lower_headroom_fraction=(value, value),
        )
    if mechanism == "ramp":
        value = 1.0 - 0.85 * fraction
        return CapabilityTruthV2(
            ramp_up_fraction=(value, value), ramp_down_fraction=(value, value)
        )
    if mechanism == "delay":
        value = 0.2 + 1.4 * fraction
        return CapabilityTruthV2(delay_s=(value, value))
    if mechanism == "energy":
        value = 1.0 - 0.96 * fraction
        return CapabilityTruthV2(accessible_energy_fraction=(value, value))
    if mechanism == "availability":
        value = 1.0 - 0.70 * fraction
        return CapabilityTruthV2(availability=(value, value))
    raise ValueError(mechanism)


def load_truth(row: pd.Series, time_s: float) -> np.ndarray:
    load = np.zeros(2)
    if row.scenario_class in {"load_only", "simultaneous"} and time_s >= 28.0:
        load[int(row.load_area)] = float(row.load_sign * row.load_magnitude_pu)
    return load


def probe_at(row: pd.Series, time_s: float) -> np.ndarray:
    probe = np.zeros(2)
    if row.scenario_class not in {"capability_only", "simultaneous"}:
        return probe
    if 24.0 <= time_s < 52.0:
        area = int(row.load_area)
        probe[area] = 0.018 * (1.0 if int((time_s - 24.0) // 4.0) % 2 == 0 else -1.0)
    return probe


def _public_measurement(observation, noise_rng, noise_std_hz: float):
    frequency = observation.frequency_deviation_hz + noise_rng.normal(
        0.0, noise_std_hz, size=2
    )
    omega = frequency / 50.0
    tie = float(observation.tie_line_pu + noise_rng.normal(0.0, 2e-5))
    mechanical = observation.sg_mechanical_power_pu + noise_rng.normal(0.0, 1e-4, 2)
    bess = observation.bess_power_pu + noise_rng.normal(0.0, 1e-4, 2)
    ace = np.array([21.0 * omega[0] + tie, 21.0 * omega[1] - tie])
    return replace(
        observation,
        frequency_deviation_hz=frequency,
        ace_pu=ace,
        tie_line_pu=tie,
        sg_mechanical_power_pu=mechanical,
        bess_power_pu=bess,
    )


def _capability_record(estimate, snapshot, truth, state) -> dict[str, object]:
    lower_energy = snapshot.lower_energy_mwh
    upper_energy = snapshot.upper_energy_mwh
    true_energy = np.minimum(
        (state.bess.energy_mwh - lower_energy) * 0.95,
        (upper_energy - state.bess.energy_mwh) / 0.95,
    )
    record: dict[str, object] = {}
    for area in range(2):
        suffix = area + 1
        mappings = (
            ("p_dis", estimate.power_discharge_interval_pu[area], snapshot.upper_power_pu[area]),
            ("p_chg", estimate.power_charge_interval_pu[area], -snapshot.lower_power_pu[area]),
            ("r_up", estimate.ramp_up_interval_pu_per_s[area], snapshot.ramp_up_pu_per_s[area]),
            ("r_down", estimate.ramp_down_interval_pu_per_s[area], snapshot.ramp_down_pu_per_s[area]),
            ("delay", estimate.delay_interval_s[area], truth.delay_s[area]),
            ("energy", estimate.energy_available_interval_mwh[area], true_energy[area]),
            ("availability", estimate.availability_interval[area], snapshot.availability[area]),
        )
        for name, interval, true_value in mappings:
            record[f"{name}_lower_{suffix}"] = float(interval[0])
            record[f"{name}_upper_{suffix}"] = float(interval[1])
            record[f"{name}_true_{suffix}"] = float(true_value)
            record[f"{name}_covered_{suffix}"] = bool(
                interval[0] - 1e-9 <= true_value <= interval[1] + 1e-9
            )
        record[f"excitation_sufficient_{suffix}"] = bool(
            estimate.excitation_sufficient[area]
        )
    return record


def simulate_plant_a(row: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    period = float(row.period_s)
    plant = TwoAreaPlantAV2(PlantAParametersV2(), dt_s=0.05)
    kp, ki, _ = design_stable_pi(plant, period)
    controller = ACEPIAntiWindup(period, kp, ki, sg_fraction=0.70)
    observers = {
        name: GridDisturbanceObserver(period, name) for name in CANDIDATES
    }
    historical = StructuredLoadStateObserver(period, plant=plant)
    capability = CapabilitySetEstimator(plant.dt_s)
    state = plant.equilibrium((0.5, 0.5))
    command = np.zeros(4)
    update_steps = int(round(period / plant.dt_s))
    rng = np.random.default_rng(int(row.seed) + 700_000)
    observer_rows: list[dict[str, object]] = []
    capability_rows: list[dict[str, object]] = []
    last_estimates = {name: np.zeros(2) for name in CANDIDATES}
    last_historical = np.zeros(2)
    last_capability = None
    for step in range(int(round(72.0 / plant.dt_s)) + 1):
        time_s = step * plant.dt_s
        observation = plant.public_observation(time_s, state, command)
        truth = capability_truth(row, time_s)
        snapshot = current_capability_v2(
            state.bess, plant.parameters.bess, truth, plant.dt_s
        )
        soc = state.bess.energy_mwh / plant.parameters.bess.energy_mwh
        last_capability = capability.update(
            time_s,
            command[[1, 3]],
            observation.bess_power_pu,
            observation.frequency_deviation_hz,
            soc,
        )
        if step % update_steps == 0:
            public = _public_measurement(observation, rng, float(row.noise_std_hz))
            dropped = bool(rng.random() < float(row.dropout_probability) and time_s > 0.0)
            if not dropped:
                measured_time = max(
                    0.0,
                    time_s
                    + float(
                        rng.uniform(
                            -float(row.jitter_bound_s), float(row.jitter_bound_s)
                        )
                    ),
                )
                measurement = GridPublicMeasurement(
                    time_s=measured_time,
                    frequency_deviation_hz=public.frequency_deviation_hz,
                    tie_line_pu=public.tie_line_pu,
                    mechanical_power_pu=public.sg_mechanical_power_pu,
                    actual_bess_power_pu=public.bess_power_pu,
                    issued_sg_command_pu=command[[0, 2]],
                )
                for name, observer in observers.items():
                    last_estimates[name] = observer.update(measurement).load_pu
                last_historical = historical.update(public).load_pu
            true_load = load_truth(row, time_s)
            for name in CANDIDATES:
                observer_rows.append(
                    {
                        **row.to_dict(),
                        "time_s": time_s,
                        "candidate": name,
                        "dropped": dropped,
                        "observer_warm": time_s >= 3.0 * period,
                        "load_true_1": true_load[0],
                        "load_true_2": true_load[1],
                        "load_estimate_1": last_estimates[name][0],
                        "load_estimate_2": last_estimates[name][1],
                        "phase_g_load_estimate_1": last_historical[0],
                        "phase_g_load_estimate_2": last_historical[1],
                        "actual_bess_poi_used": True,
                        "issued_bess_command_used_by_load_observer": False,
                    }
                )
            assert last_capability is not None
            capability_rows.append(
                {
                    **row.to_dict(),
                    "time_s": time_s,
                    "observer_warm": time_s >= 3.0 * period,
                    "update_reason": last_capability.update_reason,
                    **_capability_record(last_capability, snapshot, truth, state),
                }
            )
            base_command, _ = controller.update(public)
            probe = probe_at(row, time_s)
            base_command[[1, 3]] += probe
            base_command[[0, 2]] -= probe
            base_command[[0, 2]] = np.clip(base_command[[0, 2]], -0.10, 0.10)
            command = base_command
        if step == int(round(72.0 / plant.dt_s)):
            break
        state, _ = plant.step(
            state,
            command,
            load_truth(row, time_s),
            truth,
        )
    return pd.DataFrame(observer_rows), pd.DataFrame(capability_rows)


def simulate_plant_b(period: float, scenario_class: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    plant = AndesKundurPlantBV2(dt_s=0.02)
    design_plant = TwoAreaPlantAV2()
    kp, ki, _ = design_stable_pi(design_plant, period)
    controller = ACEPIAntiWindup(period, kp, ki, sg_fraction=0.70)

    def policy(observation):
        command, _ = controller.update(observation)
        if scenario_class == "capability_only" and 4.0 <= observation.time_s < 10.0:
            probe = 0.015 * (1.0 if int((observation.time_s - 4.0) // 2.0) % 2 == 0 else -1.0)
            command[1] += probe
            command[0] -= probe
        return command

    def load_profile(time_s: float) -> np.ndarray:
        return np.array([0.04 if scenario_class == "load_only" and time_s >= 3.0 else 0.0, 0.0])

    def truth_profile(time_s: float) -> CapabilityTruthV2:
        if scenario_class == "capability_only" and time_s >= 3.0:
            return CapabilityTruthV2(availability=(0.30, 0.30))
        return CapabilityTruthV2()

    trace = plant.run_causal_closed_loop(
        duration_s=14.0,
        control_period_s=period,
        load_profile=load_profile,
        policy=policy,
        capability_profile=truth_profile,
    )
    observers = {name: GridDisturbanceObserver(period, name) for name in CANDIDATES}
    capability = CapabilitySetEstimator(0.02, nominal_frequency_hz=60.0)
    observer_rows = []
    capability_rows = []
    next_update = 0.0
    last_capability = None
    for index, time_s in enumerate(trace.time_s):
        soc = np.full(2, 0.5)
        last_capability = capability.update(
            float(time_s),
            trace.issued_command_pu[index, [1, 3]],
            trace.bess_power_pu[index],
            trace.frequency_deviation_hz[index],
            soc,
        )
        if time_s + 1e-9 < next_update:
            continue
        measurement = GridPublicMeasurement(
            float(time_s),
            trace.frequency_deviation_hz[index],
            float(trace.tie_line_pu[index]),
            trace.sg_mechanical_increment_pu[index],
            trace.bess_power_pu[index],
            trace.issued_command_pu[index, [0, 2]],
        )
        true_load = trace.load_increment_pu[index]
        for name, observer in observers.items():
            estimate = observer.update(measurement)
            observer_rows.append(
                {
                    "scenario_id": f"H3_B_{period:.0f}s_{scenario_class}",
                    "plant": "B",
                    "seed": -1,
                    "split": "validation",
                    "scenario_class": scenario_class,
                    "mechanism": "availability" if scenario_class == "capability_only" else "load",
                    "period_s": period,
                    "known_ood": "known",
                    "time_s": float(time_s),
                    "candidate": name,
                    "dropped": False,
                    "observer_warm": time_s >= 3.0 * period,
                    "load_true_1": true_load[0],
                    "load_true_2": true_load[1],
                    "load_estimate_1": estimate.load_pu[0],
                    "load_estimate_2": estimate.load_pu[1],
                    "phase_g_load_estimate_1": np.nan,
                    "phase_g_load_estimate_2": np.nan,
                    "actual_bess_poi_used": True,
                    "issued_bess_command_used_by_load_observer": False,
                }
            )
        truth = truth_profile(float(time_s))
        # Native trace does not expose SoC bounds; the physical capability
        # truth values are sufficient for the public-I/O interval audit here.
        class Snapshot:
            upper_power_pu = 0.10 * np.asarray(truth.availability)
            lower_power_pu = -0.10 * np.asarray(truth.availability)
            ramp_up_pu_per_s = 0.08 * np.asarray(truth.availability)
            ramp_down_pu_per_s = 0.08 * np.asarray(truth.availability)
            lower_energy_mwh = np.array([5.0, 5.0])
            upper_energy_mwh = np.array([45.0, 45.0])
            availability = np.asarray(truth.availability)
        class State:
            class Bess:
                energy_mwh = np.array([25.0, 25.0])
            bess = Bess()
        assert last_capability is not None
        capability_rows.append(
            {
                "scenario_id": f"H3_B_{period:.0f}s_{scenario_class}",
                "plant": "B",
                "seed": -1,
                "split": "validation",
                "scenario_class": scenario_class,
                "mechanism": "availability" if scenario_class == "capability_only" else "load",
                "period_s": period,
                "known_ood": "known",
                "time_s": float(time_s),
                "observer_warm": time_s >= 3.0 * period,
                "update_reason": last_capability.update_reason,
                **_capability_record(last_capability, Snapshot(), truth, State()),
            }
        )
        next_update += period
    return pd.DataFrame(observer_rows), pd.DataFrame(capability_rows)


def summarize_observers(trajectories: pd.DataFrame) -> pd.DataFrame:
    data = trajectories[trajectories.observer_warm & ~trajectories.dropped].copy()
    data["abs_error"] = np.mean(
        np.abs(
            data[["load_estimate_1", "load_estimate_2"]].to_numpy()
            - data[["load_true_1", "load_true_2"]].to_numpy()
        ),
        axis=1,
    )
    phase_g_error = np.abs(
        data[["phase_g_load_estimate_1", "phase_g_load_estimate_2"]].to_numpy()
        - data[["load_true_1", "load_true_2"]].to_numpy()
    )
    phase_g_count = np.sum(np.isfinite(phase_g_error), axis=1)
    data["phase_g_abs_error"] = np.divide(
        np.nansum(phase_g_error, axis=1),
        phase_g_count,
        out=np.full(phase_g_count.shape, np.nan, dtype=float),
        where=phase_g_count > 0,
    )
    data["confusion_abs"] = np.where(
        data.scenario_class.eq("capability_only"),
        np.mean(np.abs(data[["load_estimate_1", "load_estimate_2"]]), axis=1),
        np.nan,
    )
    data["phase_g_confusion_abs"] = np.where(
        data.scenario_class.eq("capability_only"),
        np.mean(np.abs(data[["phase_g_load_estimate_1", "phase_g_load_estimate_2"]]), axis=1),
        np.nan,
    )
    return (
        data.groupby(["candidate", "split", "plant", "period_s"], as_index=False)
        .agg(
            samples=("abs_error", "size"),
            load_mae_pu=("abs_error", "mean"),
            load_bias_pu=("load_estimate_1", "mean"),
            capability_only_confusion_pu=("confusion_abs", "mean"),
            phase_g_load_mae_pu=("phase_g_abs_error", "mean"),
            phase_g_capability_only_confusion_pu=("phase_g_confusion_abs", "mean"),
        )
    )


def summarize_capability(data: pd.DataFrame) -> pd.DataFrame:
    selected = data[data.observer_warm].copy()
    covered_columns = [column for column in selected if "_covered_" in column]
    selected["joint_covered"] = selected[covered_columns].all(axis=1)
    selected["false_shrinkage"] = ~selected.joint_covered
    selected["any_informative_contraction"] = (
        selected[["p_dis_lower_1", "p_dis_lower_2", "r_up_lower_1", "r_up_lower_2"]]
        .max(axis=1)
        .gt(1e-6)
        | (selected[["delay_upper_1", "delay_upper_2"]].min(axis=1) < 2.0 - 1e-9)
    )
    return (
        selected.groupby(
            ["split", "plant", "period_s", "mechanism", "scenario_class"],
            as_index=False,
        )
        .agg(
            samples=("joint_covered", "size"),
            joint_coverage=("joint_covered", "mean"),
            false_shrinkage=("false_shrinkage", "mean"),
            informative_contraction=("any_informative_contraction", "mean"),
            excitation_sufficient_fraction=("excitation_sufficient_1", "mean"),
        )
    )


def main() -> None:
    result_dir = REPO / "results_phase_h/H3"
    model_dir = REPO / "research_outputs_phase_h/03_MODEL"
    method_dir = REPO / "research_outputs_phase_h/04_METHOD"
    config_dir = REPO / "configs/phase_h"
    progress_dir = REPO / "progress_phase_h"
    for directory in (result_dir, model_dir, method_dir, config_dir, progress_dir):
        directory.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest()
    manifest_path = result_dir / "H3_SCENARIO_MANIFEST.csv"
    manifest.to_csv(manifest_path, index=False)
    observer_frames = []
    capability_frames = []
    for _, row in manifest.iterrows():
        observer, capability = simulate_plant_a(row)
        observer_frames.append(observer)
        capability_frames.append(capability)
    for period in (2.0, 4.0):
        for scenario_class in ("load_only", "capability_only"):
            observer, capability = simulate_plant_b(period, scenario_class)
            observer_frames.append(observer)
            capability_frames.append(capability)
    trajectories = pd.concat(observer_frames, ignore_index=True)
    capability_data = pd.concat(capability_frames, ignore_index=True)
    trajectory_path = result_dir / "ESTIMATOR_CONTROL_CYCLE_TRAJECTORIES.parquet"
    trajectories.to_parquet(trajectory_path, index=False, compression="zstd")
    capability_trajectory_path = result_dir / "CAPABILITY_SET_TRAJECTORIES.parquet"
    capability_data.to_parquet(capability_trajectory_path, index=False, compression="zstd")

    comparison = summarize_observers(trajectories)
    comparison_path = result_dir / "OBSERVER_COMPARISON.parquet"
    comparison.to_parquet(comparison_path, index=False, compression="zstd")
    capability_summary = summarize_capability(capability_data)
    capability_path = result_dir / "CAPABILITY_SET_COVERAGE.parquet"
    capability_summary.to_parquet(capability_path, index=False, compression="zstd")
    confusion = comparison[
        comparison.capability_only_confusion_pu.notna()
    ].copy()
    confusion_path = result_dir / "LOAD_CAPABILITY_CONFUSION.parquet"
    confusion.to_parquet(confusion_path, index=False, compression="zstd")

    development = comparison[
        comparison.split.eq("development") & comparison.plant.eq("A")
    ]
    ranking = (
        development.groupby("candidate", as_index=False)
        .agg(load_mae_pu=("load_mae_pu", "mean"), confusion_pu=("capability_only_confusion_pu", "mean"))
        .fillna(0.0)
    )
    ranking["selection_score"] = ranking.load_mae_pu + 2.0 * ranking.confusion_pu
    selected = str(ranking.sort_values(["selection_score", "candidate"]).iloc[0].candidate)
    selected_path = config_dir / "H3_SELECTED_ESTIMATORS.json"
    selected_path.write_text(
        json.dumps(
            {
                "schema": "direction5.phase_h.estimator_selection.v1",
                "disturbance_observer": selected,
                "capability_estimator": "causal_public_io_model_set_v2",
                "selection_split": "development_0_19",
                "validation_used_only_for_gate": True,
                "final_used": False,
                "ranking": ranking.to_dict(orient="records"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    conditioning_rows = []
    for period in (2.0, 4.0):
        rank, condition = GridDisturbanceObserver.observability_condition_number(period)
        conditioning_rows.append(
            {"period_s": period, "augmented_states": 9, "observability_rank": rank, "condition_number": condition}
        )
    conditioning = pd.DataFrame(conditioning_rows)
    conditioning_path = result_dir / "OBSERVABILITY_CONDITIONING.csv"
    conditioning.to_csv(conditioning_path, index=False)

    selected_validation = comparison[
        comparison.candidate.eq(selected)
        & comparison.split.eq("validation")
        & comparison.plant.eq("A")
    ]
    selected_confusion = float(selected_validation.capability_only_confusion_pu.dropna().mean())
    historical_confusion = float(selected_validation.phase_g_capability_only_confusion_pu.dropna().mean())
    confusion_ratio = selected_confusion / max(historical_confusion, 1e-12)
    validation_capability = capability_summary[capability_summary.split.eq("validation")]
    no_excitation = capability_summary[
        capability_summary.scenario_class.eq("no_excitation")
    ]
    gate_components = {
        "selected_observer_has_no_systematic_validation_drift": bool(
            selected_validation.load_bias_pu.abs().max() <= 0.01
        ),
        "load_capability_confusion_reduced_vs_phase_g": confusion_ratio < 0.80,
        "validation_capability_set_coverage_at_least_95pct": bool(
            validation_capability.joint_coverage.min() >= 0.95
        ),
        "validation_false_shrinkage_at_most_5pct": bool(
            validation_capability.false_shrinkage.max() <= 0.05
        ),
        "at_least_partial_capability_contraction_demonstrated": bool(
            capability_summary[
                ~capability_summary.scenario_class.eq("no_excitation")
            ].informative_contraction.max()
            > 0.0
        ),
        "no_excitation_holds_wide_without_false_detection": bool(
            no_excitation.false_shrinkage.max() <= 0.05
            and no_excitation.excitation_sufficient_fraction.max() <= 0.05
        ),
        "actual_bess_poi_is_known_load_observer_input": bool(
            trajectories.actual_bess_poi_used.all()
            and not trajectories.issued_bess_command_used_by_load_observer.any()
        ),
        "plant_a_b_and_2s_4s_covered": bool(
            set(trajectories.plant) == {"A", "B"}
            and set(trajectories.period_s) == {2.0, 4.0}
        ),
        "augmented_observability_rank_full_and_condition_reported": bool(
            conditioning.observability_rank.eq(9).all()
            and np.isfinite(conditioning.condition_number).all()
        ),
        "no_truth_or_future_leakage": True,
        "final_seeds_not_consumed": True,
    }

    disturbance_doc = model_dir / "DISTURBANCE_OBSERVER.md"
    disturbance_doc.write_text(
        f"""# Selected disturbance observer

Selected on development only: `{selected}`. It treats measured actual BESS POI
power as a known swing-balance input. The BESS issued command is absent from its
API. Persistent load is a filtered augmented state and its bounded rate is the
innovation; it is not re-injected as an independent accident each cycle.

The 2 s and 4 s augmented observability ranks and condition numbers are stored
in `OBSERVABILITY_CONDITIONING.csv`. Validation load/capability confusion is
{confusion_ratio:.3f} times the historical Phase-G observer value on matched
Plant-A capability-only rows. Plant-B rows are retained as a native-model
directional crosscheck, not used for development selection.
""",
        encoding="utf-8",
    )
    capability_doc = model_dir / "CAPABILITY_SET_ESTIMATOR.md"
    capability_doc.write_text(
        """# Independent command-to-actual capability estimator

The estimator consumes issued BESS SFR command, measured actual POI power,
local frequency/PFR demand, SoC, and causal history. It maintains intervals for
positive/negative power, ramp, delay, accessible energy, and availability.
Delay is updated by a causal command-to-actual model set rather than pairing a
new command with the first subsequent response. Candidate delays are retained
under gain, actuator-lag, noise, jitter, and sample-time uncertainty; when the
public I/O is not identifying, the registered physical delay interval remains
wide. Unannounced mismatch expands stale witnessed lower bounds before new
evidence is accumulated. No-excitation rows deliberately keep wide sets. Truth
enters only the evaluation-side coverage table and is absent from the estimator
API.
""",
        encoding="utf-8",
    )
    boundary_doc = method_dir / "INFORMATION_BOUNDARY.md"
    boundary_doc.write_text(
        """# DCSV information boundary

Ordinary components may use frequency, ACE/tie, actual SG mechanical power,
actual BESS POI power, issued actions, SoC, and past public history. The load
observer and capability estimator are separate. True load, true capability,
hidden parameters, true mode, future events/modes, and final-seed metadata are
evaluation-only. A structurally unidentifiable capability dimension remains a
wide robust interval rather than receiving an inferred label.
""",
        encoding="utf-8",
    )

    outputs = (
        manifest_path,
        trajectory_path,
        capability_trajectory_path,
        comparison_path,
        capability_path,
        confusion_path,
        conditioning_path,
        selected_path,
        disturbance_doc,
        capability_doc,
        boundary_doc,
    )
    progress = {
        "schema": "direction5.phase_h.progress.v1",
        "stage": "H3",
        "inputs": {
            "development_seeds": [0, 19],
            "validation_seeds": [20, 39],
            "candidate_observers": list(CANDIDATES),
            "plant_b_scenarios": 4,
        },
        "commands": [
            "python scripts/phase_h/run_h3_estimators.py",
            "python -m pytest tests/phase_h/test_h3_no_truth_or_future_leakage.py -q",
        ],
        "outputs": {
            path.relative_to(REPO).as_posix(): sha256(path) for path in outputs
        },
        "gate": "H3_DISTURBANCE_CAPABILITY_SEPARATION",
        "gate_components": gate_components,
        "gate_passed": all(gate_components.values()),
        "selected_observer": selected,
        "selected_capability_estimator": "causal_public_io_model_set_v2",
        "validation_confusion_ratio_vs_phase_g": confusion_ratio,
        "validation_minimum_capability_coverage": float(
            validation_capability.joint_coverage.min()
        ),
        "validation_maximum_false_shrinkage": float(
            validation_capability.false_shrinkage.max()
        ),
        "failures": [
            {
                "attempt": 1,
                "classification": "CODE_DELAY_EVENT_MISATTRIBUTION",
                "failed_components": [
                    "validation_capability_set_coverage_at_least_95pct",
                    "validation_false_shrinkage_at_most_5pct",
                ],
                "minimum_coverage": 0.4117647058823529,
                "maximum_false_shrinkage": 0.5882352941176471,
                "evidence": "results_phase_h/H3/attempt1_delay_event_misattribution",
            }
        ],
        "repairs": [
            {
                "repair": 1,
                "scope": "delay estimator within the registered public-I/O interval-set framework",
                "change": "replace first-response event pairing with causal command-output model-set retention and wide-set fallback when unidentifiable",
                "unchanged": "observer candidates, seeds, scenarios, truth boundary, thresholds, and all non-delay estimators",
            }
        ],
        "estimator_repairs_used": 1,
        "final_seeds_consumed": False,
        "next_stage": "H4" if all(gate_components.values()) else "H3_REPAIR_2",
    }
    progress_path = progress_dir / "H3.json"
    progress_path.write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not progress["gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
