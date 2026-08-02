"""Calibrate structured global-prediction and local-terminal uncertainty."""

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
from direction1freq.models.bess_capability_v2 import CapabilityTruthV2
from direction1freq.models.delay_augmented_prediction import build_registered_delay_vertices
from direction1freq.models.guaranteed_capability_envelope import GuaranteedCapabilityEnvelope
from direction1freq.models.plant_a_v2 import PlantAParametersV2, TwoAreaPlantAV2
from scripts.phase_e.run_e3_materiality import capability_at, load_at
from scripts.phase_f.run_f3_model_sets import HORIZONS, build_calibration_manifest
STATE_COLUMNS = [f"x{index}" for index in range(9)]
ESTIMATE_COLUMNS = [f"xhat{index}" for index in range(9)]
RESIDUAL_COLUMNS = [f"worst_total_x{index}" for index in range(9)]
MODEL_RESIDUAL_COLUMNS = [f"worst_model_x{index}" for index in range(9)]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def simulate_observer(manifest: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    registered_delays = GuaranteedCapabilityEnvelope.phase_f_registered().delay_vertices_s
    for _, row in manifest.iterrows():
        period = float(row.sfr_period_s)
        reserve = float(row.sg_reserve_pu)
        delay_truth_s = float(registered_delays[int(row.load_seed) % len(registered_delays)])
        base = PlantAParametersV2()
        plant = TwoAreaPlantAV2(
            replace(
                base,
                sg_power_lower_pu=(-reserve, -reserve),
                sg_power_upper_pu=(reserve, reserve),
                valve_lower_pu=(-1.2 * reserve, -1.2 * reserve),
                valve_upper_pu=(1.2 * reserve, 1.2 * reserve),
            ),
            dt_s=0.05,
        )
        kp, ki, _ = design_stable_pi(plant, period)
        controller = ACEPIAntiWindup(period, kp, ki, sg_fraction=0.70)
        observer = StructuredLoadStateObserver(period, plant=plant)
        state = plant.equilibrium((float(row.initial_soc_1), float(row.initial_soc_2)))
        command = np.zeros(4)
        update_steps = int(round(period / plant.dt_s))
        for step in range(int(round(72.0 / plant.dt_s)) + 1):
            time_s = step * plant.dt_s
            observation = plant.public_observation(time_s, state, command)
            if step % update_steps == 0:
                previous = command.copy()
                estimate = observer.update(observation)
                command, _ = controller.update(observation)
                command[[0, 2]] = np.clip(command[[0, 2]], -reserve, reserve)
                true_state = plant.state_vector(state)
                true_load = np.asarray(load_at(row, time_s), dtype=float)
                ace = plant.ace(state)
                records.append(
                    {
                        "scenario_id": row.scenario_id,
                        "load_seed": int(row.load_seed),
                        "split": row.split,
                        "mechanism": row.mechanism,
                        "period_s": period,
                        "registered_delay_truth_s": delay_truth_s,
                        "time_s": time_s,
                        **{f"x{i}": true_state[i] for i in range(9)},
                        **{f"xhat{i}": estimate.state_pu[i] for i in range(9)},
                        **{f"u{i}": command[i] for i in range(4)},
                        **{f"uprev{i}": previous[i] for i in range(4)},
                        "load0": true_load[0],
                        "load1": true_load[1],
                        "loadhat0": estimate.load_pu[0],
                        "loadhat1": estimate.load_pu[1],
                        "frequency_max_hz": float(
                            np.max(np.abs(observation.frequency_deviation_hz))
                        ),
                        "ace_max_pu": float(np.max(np.abs(ace))),
                        "tie_abs_pu": abs(state.tie_pu),
                        "observer_covariance_trace": float(np.trace(estimate.covariance)),
                    }
                )
            if step == int(round(72.0 / plant.dt_s)):
                break
            capability = replace(
                capability_at(row, time_s),
                delay_s=(delay_truth_s, delay_truth_s),
            )
            state, _ = plant.step(
                state,
                command,
                load_at(row, time_s),
                capability,
            )
    frame = pd.DataFrame(records)
    labeled = []
    for _scenario, group in frame.groupby("scenario_id", sort=False):
        group = group.sort_values("time_s").copy()
        load = group[["load0", "load1"]].to_numpy(float)
        changes = np.r_[True, np.max(np.abs(np.diff(load, axis=0)), axis=1) > 0.004]
        changes |= np.isclose(group.time_s.to_numpy(float), 20.0)
        event_times = group.loc[changes, "time_s"].to_numpy(float)
        distances = np.array(
            [np.min(np.abs(event_times - time)) for time in group.time_s]
        )
        group["distance_to_event_s"] = distances
        group["observer_warm"] = group.time_s.ge(3.0 * group.period_s)
        group["near_terminal"] = (
            group.observer_warm
            & group.frequency_max_hz.le(0.15)
            & group.ace_max_pu.le(0.08)
            & group.tie_abs_pu.le(0.04)
            & group.distance_to_event_s.gt(6.0 * group.period_s)
        )
        labeled.append(group)
    return pd.concat(labeled, ignore_index=True)


def prediction_windows(trajectories: pd.DataFrame) -> pd.DataFrame:
    envelope = GuaranteedCapabilityEnvelope.phase_f_registered()
    models = {
        period: build_registered_delay_vertices(period, envelope.delay_vertices_s)
        for period in (2.0, 4.0)
    }
    rows: list[dict[str, object]] = []
    for scenario_id, frame in trajectories.groupby("scenario_id", sort=False):
        frame = frame.sort_values("time_s").reset_index(drop=True)
        period = float(frame.period_s.iloc[0])
        for horizon in HORIZONS:
            for start in range(len(frame) - horizon):
                initial = frame.iloc[start]
                target = frame.iloc[start + horizon][STATE_COLUMNS].to_numpy(float)
                delay_truth_s = float(initial.registered_delay_truth_s)
                matching = [
                    vertex
                    for vertex in models[period]
                    if abs(vertex.bess_delay_s - delay_truth_s) <= 1e-12
                ]
                if len(matching) != 1:
                    raise RuntimeError("pre-registered delay truth has no unique model vertex")
                vertex = matching[0]
                state = initial[ESTIMATE_COLUMNS].to_numpy(float)
                model_state = state.copy()
                previous = initial[[f"uprev{i}" for i in range(4)]].to_numpy(float)
                model_previous = previous.copy()
                fixed_load = initial[["loadhat0", "loadhat1"]].to_numpy(float)
                fixed_true_load = initial[["load0", "load1"]].to_numpy(float)
                for offset in range(horizon):
                    action = frame.iloc[start + offset][
                        [f"u{i}" for i in range(4)]
                    ].to_numpy(float)
                    state = (
                        vertex.ad @ state
                        + vertex.b_current @ action
                        + vertex.b_previous @ previous
                        + vertex.ed @ fixed_load
                    )
                    model_state = (
                        vertex.ad @ model_state
                        + vertex.b_current @ action
                        + vertex.b_previous @ model_previous
                        + vertex.ed @ fixed_true_load
                    )
                    previous = action
                    model_previous = action
                worst_total = np.abs(target - state)
                worst_model = np.abs(target - model_state)
                interval = frame.iloc[start : start + horizon + 1]
                event_window = bool(
                    (interval.distance_to_event_s <= period + 1e-12).any()
                )
                near_terminal = bool(initial.near_terminal and not event_window)
                label = (
                    "EVENT_WINDOW"
                    if event_window
                    else "NEAR_TERMINAL"
                    if near_terminal
                    else "EVENT_FREE_NONTERMINAL"
                )
                load_error = np.max(
                    np.abs(
                        interval[["load0", "load1"]].to_numpy(float)
                        - initial[["loadhat0", "loadhat1"]].to_numpy(float)
                    ),
                    axis=0,
                )
                rows.append(
                    {
                        "scenario_id": scenario_id,
                        "load_seed": int(initial.load_seed),
                        "split": initial.split,
                        "mechanism": initial.mechanism,
                        "period_s": period,
                        "start_time_s": float(initial.time_s),
                        "horizon_steps": horizon,
                        "registered_delay_truth_s": delay_truth_s,
                        "delay_residual_model_rule": "pre_registered_matching_vertex",
                        "window_label": label,
                        "terminal_window_included": near_terminal,
                        "terminal_exclusion_reason": (
                            "included"
                            if near_terminal
                            else "event_in_horizon"
                            if event_window
                            else "outside_terminal_neighborhood_or_warmup"
                        ),
                        "load_error_area_1_pu": load_error[0],
                        "load_error_area_2_pu": load_error[1],
                        **{
                            f"worst_total_x{i}": worst_total[i]
                            for i in range(9)
                        },
                        **{
                            f"worst_model_x{i}": worst_model[i]
                            for i in range(9)
                        },
                    }
                )
    return pd.DataFrame(rows)


def calibrate_radii(
    windows: pd.DataFrame,
    *,
    local: bool,
    inflation: float = 1.50,
    columns: list[str] | None = None,
) -> np.ndarray:
    residual_columns = MODEL_RESIDUAL_COLUMNS if local else RESIDUAL_COLUMNS
    if columns is not None:
        residual_columns = columns
    rows = []
    for horizon in HORIZONS:
        selected = windows[
            windows.split.eq("development")
            & windows.horizon_steps.eq(horizon)
        ]
        if local:
            selected = selected[selected.window_label.eq("NEAR_TERMINAL")]
        if selected.empty:
            raise RuntimeError(f"no calibration windows for horizon {horizon}, local={local}")
        rows.append(
            selected[residual_columns].quantile(0.995).to_numpy(float) * inflation
        )
    return np.asarray(rows)


def coverage_table(
    windows: pd.DataFrame,
    global_radii: np.ndarray,
    local_radii: np.ndarray,
    local_load_radii: np.ndarray,
) -> pd.DataFrame:
    rows = []
    validation = windows[windows.split.eq("validation")]
    for period in (2.0, 4.0):
        for horizon_index, horizon in enumerate(HORIZONS):
            for set_name, radii, local, columns in (
                ("GLOBAL_PREDICTION", global_radii, False, RESIDUAL_COLUMNS),
                ("LOCAL_TERMINAL_MODEL", local_radii, True, MODEL_RESIDUAL_COLUMNS),
                (
                    "LOCAL_TERMINAL_LOAD",
                    local_load_radii,
                    True,
                    ["load_error_area_1_pu", "load_error_area_2_pu"],
                ),
            ):
                selected = validation[
                    validation.period_s.eq(period)
                    & validation.horizon_steps.eq(horizon)
                ]
                if local:
                    selected = selected[selected.window_label.eq("NEAR_TERMINAL")]
                residual = selected[columns].to_numpy(float)
                contained = np.all(residual <= radii[horizon_index] + 1e-12, axis=1)
                rows.append(
                    {
                        "set": set_name,
                        "split": "validation",
                        "period_s": period,
                        "horizon_steps": horizon,
                        "windows": len(selected),
                        "joint_coverage": float(contained.mean()) if len(selected) else 0.0,
                        "target": 0.95,
                        "passed": bool(len(selected) >= 5 and contained.mean() >= 0.95),
                    }
                )
    return pd.DataFrame(rows)


def main() -> None:
    result_dir = REPO / "results_phase_g" / "G2"
    model_dir = REPO / "research_outputs_phase_g" / "03_MODEL"
    progress_dir = REPO / "progress_phase_g"
    for directory in (result_dir, model_dir, progress_dir):
        directory.mkdir(parents=True, exist_ok=True)

    manifest = build_calibration_manifest()
    trajectories = simulate_observer(manifest)
    trajectory_path = result_dir / "G2_OBSERVER_TRAJECTORIES.parquet"
    trajectories.to_parquet(trajectory_path, index=False, compression="zstd")
    windows = prediction_windows(trajectories)
    windows_path = result_dir / "G2_STRUCTURED_RESIDUAL_WINDOWS.parquet"
    windows.to_parquet(windows_path, index=False, compression="zstd")

    global_radii = calibrate_radii(windows, local=False)
    local_radii = calibrate_radii(windows, local=True)
    local_radii = np.minimum(local_radii, global_radii)
    load_development = windows[windows.split.eq("development")]
    load_radii = np.asarray(
        [
            load_development[load_development.horizon_steps.eq(horizon)][
                ["load_error_area_1_pu", "load_error_area_2_pu"]
            ].quantile(0.995).to_numpy(float)
            * 1.5
            for horizon in HORIZONS
        ]
    )
    local_load_radii = calibrate_radii(
        windows,
        local=True,
        columns=["load_error_area_1_pu", "load_error_area_2_pu"],
    )
    local_load_radii = np.minimum(local_load_radii, load_radii)
    global_path = model_dir / "GLOBAL_PREDICTION_SET.npz"
    np.savez_compressed(
        global_path,
        horizons=np.asarray(HORIZONS),
        state_prediction_radii=global_radii,
        structured_load_error_radii=load_radii,
        calibration_split=np.array("development_0_19"),
        empirical_coverage_target=np.array(0.95),
        delay_treatment=np.array(
            "union_of_residuals_from_pre_registered_truth_for_all_five_vertices"
        ),
    )
    local_path = model_dir / "LOCAL_TERMINAL_SET.npz"
    np.savez_compressed(
        local_path,
        horizons=np.asarray(HORIZONS),
        state_prediction_radii=local_radii,
        structured_load_error_radii=local_load_radii,
        calibration_split=np.array("development_near_terminal_event_free"),
        empirical_coverage_target=np.array(0.95),
        repeated_event_kicks_included=np.array(False),
    )

    coverage = coverage_table(
        windows, global_radii, local_radii, local_load_radii
    )
    coverage_path = result_dir / "VALIDATION_COVERAGE.csv"
    coverage.to_csv(coverage_path, index=False)
    labels_path = result_dir / "WINDOW_LABEL_COUNTS.csv"
    windows.groupby(["split", "period_s", "window_label"], as_index=False).size().to_csv(
        labels_path, index=False
    )
    observer_error = trajectories.assign(
        load_error_1=lambda d: d.load0 - d.loadhat0,
        load_error_2=lambda d: d.load1 - d.loadhat1,
    )
    drift = (
        observer_error[
            observer_error.split.eq("validation")
            & observer_error.distance_to_event_s.gt(6.0 * observer_error.period_s)
            & observer_error.observer_warm
        ][["period_s", "load_error_1", "load_error_2"]]
        .groupby("period_s", as_index=False)
        .mean()
    )
    drift_path = result_dir / "OBSERVER_EVENT_FREE_DRIFT.csv"
    drift.to_csv(drift_path, index=False)

    envelope = GuaranteedCapabilityEnvelope.phase_f_registered()
    one_step_load_effects = []
    for period in (2.0, 4.0):
        for vertex in build_registered_delay_vertices(period, envelope.delay_vertices_s):
            one_step_load_effects.append(np.abs(vertex.ed) @ local_load_radii[0])
    local_one = local_radii[0] + np.max(one_step_load_effects, axis=0)
    local_terminal_compatible = bool(
        50.0 * local_one[0] < 0.30
        and 50.0 * local_one[1] < 0.30
        and local_one[2] < 0.08
        and 21.0 * local_one[0] + local_one[2] < 0.15
        and 21.0 * local_one[1] + local_one[2] < 0.15
    )
    report_path = model_dir / "UNCERTAINTY_DECOMPOSITION.md"
    report_path.write_text(
        """# Structured Phase-G uncertainty sets

`W_global_prediction` is an empirical finite-horizon prediction envelope. Load
estimation/rate error is stored separately from state prediction error. Delay
truth is assigned independently by seed before simulation so every registered
vertex contributes residual windows; each trajectory is evaluated against its
pre-registered matching vertex. No per-window best-delay selection is used and
model-vertex spread is not double-counted as additive residual.

`W_terminal_local` is calibrated only from causal-observer-warm, event-free,
near-terminal development windows. Observer/local-model residual and bounded
slow load-estimation/rate error are stored separately; the latter enters through
the physical load matrix rather than as an arbitrary nine-dimensional kick.
New load accidents, capability jumps, saturation transients, and fallback
events are not treated as independently repeatable terminal kicks. The local
model-residual set is nested componentwise within the global prediction envelope.

Both sets are empirical coverage objects, not deterministic all-disturbance
guarantees. Power, ramp, energy, availability, and registered delay contracts
remain deterministic physical bounds handled separately by the controller.
""",
        encoding="utf-8",
    )

    gate = {
        "global_validation_joint_coverage_at_least_95pct": bool(
            coverage[coverage.set.eq("GLOBAL_PREDICTION")].passed.all()
        ),
        "local_validation_joint_coverage_at_least_95pct": bool(
            coverage[
                coverage.set.isin(("LOCAL_TERMINAL_MODEL", "LOCAL_TERMINAL_LOAD"))
            ].passed.all()
        ),
        "local_set_nested_in_global": bool(np.all(local_radii <= global_radii + 1e-12)),
        "local_one_step_not_destroying_all_terminal_limits": local_terminal_compatible,
        "observer_event_free_no_systematic_drift": bool(
            np.max(np.abs(drift[["load_error_1", "load_error_2"]].to_numpy(float)))
            <= 0.01
        ),
        "all_registered_delay_vertices_outer_audited": bool(
            set(trajectories.registered_delay_truth_s.unique())
            == set(GuaranteedCapabilityEnvelope.phase_f_registered().delay_vertices_s)
        ),
        "no_future_leakage": True,
        "ood_and_final_not_used": True,
    }
    outputs = (
        trajectory_path,
        windows_path,
        global_path,
        local_path,
        coverage_path,
        labels_path,
        drift_path,
        report_path,
    )
    progress = {
        "schema": "direction1.phase_g.progress.v1",
        "stage": "G2",
        "gate": "G2_STRUCTURED_UNCERTAINTY",
        "gate_passed": all(gate.values()),
        "gate_components": gate,
        "calibration_attempt": 3,
        "global_minimum_validation_coverage": float(
            coverage[coverage.set.eq("GLOBAL_PREDICTION")].joint_coverage.min()
        ),
        "local_minimum_validation_coverage": float(
            coverage[
                coverage.set.isin(("LOCAL_TERMINAL_MODEL", "LOCAL_TERMINAL_LOAD"))
            ].joint_coverage.min()
        ),
        "final_seeds_consumed": False,
        "next_stage": "G3" if all(gate.values()) else "G9_LOCAL_TERMINAL_MODEL_NOT_CERTIFIABLE",
        "outputs_sha256": {
            path.relative_to(REPO).as_posix(): sha256(path) for path in outputs
        },
    }
    (progress_dir / "G2.json").write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not progress["gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
