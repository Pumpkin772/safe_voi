"""Generate deterministic Phase-2 closed-loop baseline acceptance evidence.

The controller-facing path in this script contains only ``Measurement``
objects.  Simulator truth is appended after each action under columns prefixed
with ``eval_`` and is never used to select a control action.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from d5freq.controllers.fixed_model_mpc import FixedNominalMPCController
from d5freq.controllers.lqi_fallback import LQIFallbackConfig, LQIFallbackController
from d5freq.estimation.grid_kalman_filter import GridKalmanFilter
from d5freq.interfaces import FrequencyController, Measurement
from d5freq.models.grid_frequency import GridFrequencyModel, GridParams
from d5freq.models.hidden_mode_ibr import IBRModeParams
from d5freq.optimization.linear_mpc import (
    LinearMPC,
    MPCBounds,
    MPCWeights,
    linearize_grid_ibr,
)
from d5freq.simulation.disturbances import LoadDisturbanceSpec, LoadEvent
from d5freq.simulation.hybrid_simulator import HiddenModeFrequencySimulator, Scenario
from d5freq.simulation.mode_schedules import PiecewiseConstantModeSchedule
from d5freq.utils.config import config_sha256, load_yaml
from d5freq.utils.hashing import sha256_file, sha256_json


SCHEMA_VERSION = 1
EPISODE_DURATION_S = 90.0
LOAD_STEP_TIME_S = 5.0
LOAD_STEP_PU = 0.04
TAIL_START_TIME_S = 80.0
FIXED_TAIL_MAX_ABS_HZ = 0.002
LQI_TAIL_MAX_ABS_HZ = 0.01
LOAD_ESTIMATE_TOLERANCE_PU = 5.0e-4
LQI_MECHANICAL_POWER_TOLERANCE_PU = 2.0e-3
NUMERICAL_BOUND_TOLERANCE = 1.0e-7
ACCEPTED_MPC_STATUSES = frozenset(("optimal", "optimal_inaccurate"))


def _require_schema_version(config: dict[str, Any], path: Path) -> None:
    version = config.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"{path} has schema_version={version!r}; expected {SCHEMA_VERSION}"
        )


def _grid_model(base_config: dict[str, Any]) -> GridFrequencyModel:
    values = base_config["grid"]
    return GridFrequencyModel(
        GridParams(
            f0_hz=float(values["f0_hz"]),
            M_s=float(values["M_s"]),
            D_pu=float(values["D_pu"]),
            T_t_s=float(values["T_t_s"]),
            T_g_s=float(values["T_g_s"]),
            R_pu=float(values["R_pu"]),
            control_period_s=float(values["control_period_s"]),
            integration_step_s=float(values["integration_step_s"]),
        )
    )


def _configured_filter(
    grid_model: GridFrequencyModel,
    base_config: dict[str, Any],
) -> GridKalmanFilter:
    """Construct every covariance explicitly from the versioned YAML."""

    values = base_config["estimation"]["grid_kalman"]
    return GridKalmanFilter(
        grid_model,
        process_noise_covariance=np.diag(
            np.asarray(values["process_noise_diagonal"], dtype=float)
        ),
        measurement_noise_covariance=np.diag(
            np.asarray(values["measurement_noise_diagonal"], dtype=float)
        ),
        initial_covariance=np.diag(
            np.asarray(values["initial_covariance_diagonal"], dtype=float)
        ),
        load_random_walk_std_pu_per_s=float(
            values["load_random_walk_std_pu_per_s"]
        ),
    )


def _modes(modes_config: dict[str, Any]) -> dict[str, IBRModeParams]:
    if modes_config.get("truth_access") != "simulator_and_evaluation_only":
        raise ValueError("known-mode YAML must declare simulator/evaluation-only truth")
    return {
        str(name): IBRModeParams.from_mapping(str(name), values)
        for name, values in modes_config["known_modes"].items()
    }


def _mpc_weights(mpc_config: dict[str, Any]) -> MPCWeights:
    values = mpc_config["mpc"]
    return MPCWeights(
        q_freq=float(values["q_freq"]),
        q_integral=float(values["q_integral"]),
        q_rocof=float(values["q_rocof"]),
        r_sg=float(values["r_sg"]),
        r_ibr=float(values["r_ibr"]),
        s_delta_sg=float(values["s_delta_sg"]),
        s_delta_ibr=float(values["s_delta_ibr"]),
        q_terminal_freq=float(values["q_terminal_freq"]),
        q_terminal_integral=float(values["q_terminal_integral"]),
        rho_power_slack=float(values["rho_power_slack"]),
    )


def _mpc_bounds(base_config: dict[str, Any]) -> MPCBounds:
    grid = base_config["grid"]
    ibr = base_config["ibr_command"]
    return MPCBounds(
        u_min_pu=(float(grid["u_sg_min_pu"]), float(ibr["u_min_pu"])),
        u_max_pu=(float(grid["u_sg_max_pu"]), float(ibr["u_max_pu"])),
        ramp_pu_per_s=(
            float(grid["u_sg_ramp_pu_per_s"]),
            float(ibr["ramp_pu_per_s"]),
        ),
        freq_limit_hz=float(grid["freq_limit_hz"]),
        rocof_limit_hz_per_s=float(grid["rocof_limit_hz_per_s"]),
    )


def _fixed_controller(
    grid_model: GridFrequencyModel,
    nominal_mode: IBRModeParams,
    base_config: dict[str, Any],
    mpc_config: dict[str, Any],
) -> tuple[FixedNominalMPCController, GridKalmanFilter, MPCBounds]:
    values = mpc_config["mpc"]
    horizon_steps = int(values["horizon_steps"])
    if horizon_steps != 20:
        raise ValueError("Phase-2 acceptance requires configured horizon_steps=20")
    estimator = _configured_filter(grid_model, base_config)
    bounds = _mpc_bounds(base_config)
    optimizer = LinearMPC(
        linearize_grid_ibr(grid_model.params, nominal_mode),
        horizon_steps=horizon_steps,
        weights=_mpc_weights(mpc_config),
        bounds=bounds,
        solver_priority=("CLARABEL",),
        warm_start=bool(values["warm_start"]),
    )
    return FixedNominalMPCController(optimizer, estimator), estimator, bounds


def _lqi_controller(
    grid_model: GridFrequencyModel,
    base_config: dict[str, Any],
    mpc_config: dict[str, Any],
) -> tuple[LQIFallbackController, GridKalmanFilter, LQIFallbackConfig]:
    grid = base_config["grid"]
    weights = mpc_config["mpc"]
    fallback = mpc_config["fallback"]
    estimator = _configured_filter(grid_model, base_config)
    controller_config = LQIFallbackConfig(
        q_weights=(
            float(weights["q_freq"]),
            1.0,
            1.0,
            float(weights["q_integral"]),
        ),
        r_sg=float(weights["r_sg"]),
        u_sg_min_pu=float(grid["u_sg_min_pu"]),
        u_sg_max_pu=float(grid["u_sg_max_pu"]),
        u_sg_ramp_pu_per_s=float(grid["u_sg_ramp_pu_per_s"]),
        ibr_withdraw_rate_pu_per_s=float(
            fallback["ibr_withdraw_rate_pu_per_s"]
        ),
    )
    return (
        LQIFallbackController(grid_model, controller_config, estimator),
        estimator,
        controller_config,
    )


def _scenario(mode_name: str, scenario_name: str) -> Scenario:
    return Scenario(
        mode_schedule=PiecewiseConstantModeSchedule(mode_name),
        duration_s=EPISODE_DURATION_S,
        disturbance=LoadDisturbanceSpec(
            events=(LoadEvent(LOAD_STEP_TIME_S, LOAD_STEP_PU),)
        ),
        name=scenario_name,
        omega_measurement_std_pu=0.0,
        power_measurement_std_pu=0.0,
    )


def _run_episode(
    *,
    label: str,
    seed: int,
    simulator: HiddenModeFrequencySimulator,
    scenario: Scenario,
    controller: FrequencyController,
    estimator: GridKalmanFilter,
    f0_hz: float,
    sample_time_s: float,
) -> tuple[list[dict[str, Any]], float]:
    """Run one episode without routing evaluation truth back to the controller."""

    measurement = simulator.reset(seed, scenario)
    controller.reset(measurement)
    rows: list[dict[str, Any]] = []
    sample_index = 0
    while measurement.time_s < scenario.duration_s:
        control_start = measurement
        action = controller.act(control_start)
        d_hat_at_control_start = estimator.load_disturbance_estimate_pu
        next_measurement, evaluation = simulator.step(action)

        # All values read from ``evaluation`` remain in explicitly named eval
        # columns and are not consulted before the next controller action.
        rows.append(
            {
                "scenario": label,
                "sample_index": sample_index,
                "control_start_time_s": control_start.time_s,
                "time_s": next_measurement.time_s,
                "omega_measured_pu": next_measurement.omega_pu,
                "frequency_measured_hz": f0_hz * next_measurement.omega_pu,
                "p_mech_measured_pu": next_measurement.p_mech_pu,
                "p_ibr_measured_pu": next_measurement.p_ibr_pu,
                "u_sg_pu": action.u_sg_pu,
                "u_ibr_pu": action.u_ibr_pu,
                "u_sg_rate_pu_per_s": (
                    action.u_sg_pu - control_start.u_sg_prev_pu
                )
                / sample_time_s,
                "u_ibr_rate_pu_per_s": (
                    action.u_ibr_pu - control_start.u_ibr_prev_pu
                )
                / sample_time_s,
                "d_hat_control_start_pu": d_hat_at_control_start,
                "controller_state": action.controller_state,
                "solver_status": action.solver_status,
                "solve_time_s": action.solve_time_s,
                "max_freq_slack_hz": action.max_freq_slack_hz,
                "eval_true_mode": evaluation["true_mode_eval_only"],
                "eval_load_disturbance_pu": evaluation["load_disturbance_pu"],
                "eval_omega_true_pu": evaluation["omega_true_pu"],
                "eval_frequency_true_hz": f0_hz
                * float(evaluation["omega_true_pu"]),
                "eval_p_mech_true_pu": evaluation["p_mech_true_pu"],
                "eval_p_ibr_true_pu": evaluation["p_ibr_true_pu"],
                "eval_done": evaluation["done"],
            }
        )
        measurement = next_measurement
        sample_index += 1

    # The final returned measurement has not yet reached controller.act().
    # Update the estimator once, from visible signals only, to report d_hat at
    # exactly 90 s without solving or applying an unused control action.
    estimator.update_from_measurement(measurement)
    return rows, estimator.load_disturbance_estimate_pu


def _maximum_violation(
    values: list[float], lower: float, upper: float
) -> float:
    return max(
        0.0,
        *(lower - value for value in values),
        *(value - upper for value in values),
    )


def _summarize(
    rows: list[dict[str, Any]],
    *,
    final_d_hat_pu: float,
    command_bounds: dict[str, tuple[float, float]],
    rate_bounds: dict[str, float],
    expected_statuses: frozenset[str],
    tail_limit_hz: float,
    require_mechanical_recovery: bool,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot summarize an empty episode")
    tail = [row for row in rows if float(row["time_s"]) >= TAIL_START_TIME_S]
    if not tail:
        raise ValueError("episode contains no samples in the acceptance tail")
    tail_frequency = np.asarray(
        [float(row["frequency_measured_hz"]) for row in tail], dtype=float
    )
    u_sg = [float(row["u_sg_pu"]) for row in rows]
    u_ibr = [float(row["u_ibr_pu"]) for row in rows]
    sg_rate = [abs(float(row["u_sg_rate_pu_per_s"])) for row in rows]
    ibr_rate = [abs(float(row["u_ibr_rate_pu_per_s"])) for row in rows]
    status_counts = dict(sorted(Counter(str(row["solver_status"]) for row in rows).items()))
    sg_violation = _maximum_violation(u_sg, *command_bounds["u_sg_pu"])
    ibr_violation = _maximum_violation(u_ibr, *command_bounds["u_ibr_pu"])
    sg_rate_violation = max(0.0, max(sg_rate) - rate_bounds["u_sg_pu_per_s"])
    ibr_rate_violation = max(0.0, max(ibr_rate) - rate_bounds["u_ibr_pu_per_s"])
    final_row = rows[-1]
    statuses_accepted = set(status_counts).issubset(expected_statuses)
    bounds_accepted = max(
        sg_violation,
        ibr_violation,
        sg_rate_violation,
        ibr_rate_violation,
    ) <= NUMERICAL_BOUND_TOLERANCE
    tail_accepted = float(np.max(np.abs(tail_frequency))) < tail_limit_hz
    load_estimate_accepted = (
        abs(final_d_hat_pu - LOAD_STEP_PU) < LOAD_ESTIMATE_TOLERANCE_PU
    )
    mechanical_error = abs(float(final_row["p_mech_measured_pu"]) - LOAD_STEP_PU)
    mechanical_accepted = (
        not require_mechanical_recovery
        or mechanical_error < LQI_MECHANICAL_POWER_TOLERANCE_PU
    )
    acceptance = {
        "tail_frequency": tail_accepted,
        "load_estimate": load_estimate_accepted,
        "command_and_rate_bounds": bounds_accepted,
        "solver_statuses": statuses_accepted,
        "mechanical_power_recovery": mechanical_accepted,
    }
    return {
        "samples": len(rows),
        "tail_start_time_s": TAIL_START_TIME_S,
        "tail_samples": len(tail),
        "tail_frequency_hz": {
            "minimum": float(np.min(tail_frequency)),
            "maximum": float(np.max(tail_frequency)),
            "maximum_absolute": float(np.max(np.abs(tail_frequency))),
            "mean": float(np.mean(tail_frequency)),
            "mean_absolute": float(np.mean(np.abs(tail_frequency))),
            "final": float(tail_frequency[-1]),
            "acceptance_limit_maximum_absolute": tail_limit_hz,
        },
        "d_hat_final_pu": final_d_hat_pu,
        "d_hat_final_time_s": float(final_row["time_s"]),
        "d_hat_absolute_error_pu": abs(final_d_hat_pu - LOAD_STEP_PU),
        "d_hat_acceptance_tolerance_pu": LOAD_ESTIMATE_TOLERANCE_PU,
        "p_mech_final_pu": float(final_row["p_mech_measured_pu"]),
        "p_mech_final_load_tracking_error_pu": mechanical_error,
        "commands": {
            "configured_bounds": {
                name: {"minimum": bounds[0], "maximum": bounds[1]}
                for name, bounds in command_bounds.items()
            },
            "configured_rate_bounds_pu_per_s": rate_bounds,
            "observed": {
                "u_sg_minimum_pu": min(u_sg),
                "u_sg_maximum_pu": max(u_sg),
                "u_ibr_minimum_pu": min(u_ibr),
                "u_ibr_maximum_pu": max(u_ibr),
                "u_sg_maximum_absolute_rate_pu_per_s": max(sg_rate),
                "u_ibr_maximum_absolute_rate_pu_per_s": max(ibr_rate),
            },
            "maximum_violations": {
                "u_sg_amplitude_pu": sg_violation,
                "u_ibr_amplitude_pu": ibr_violation,
                "u_sg_rate_pu_per_s": sg_rate_violation,
                "u_ibr_rate_pu_per_s": ibr_rate_violation,
            },
        },
        "solver_status_counts": status_counts,
        "expected_solver_statuses": sorted(expected_statuses),
        "maximum_solve_time_s": max(float(row["solve_time_s"]) for row in rows),
        "mean_solve_time_s": float(
            np.mean([float(row["solve_time_s"]) for row in rows])
        ),
        "acceptance": acceptance,
        "accepted": all(acceptance.values()),
    }


def _python_source_manifest(source_root: Path) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "path": path.relative_to(source_root).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in sorted(source_root.rglob("*.py"))
        if path.is_file()
    )


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        raise ValueError("cannot write an empty trajectory")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-config", type=Path, default=Path("configs/base.yaml"))
    parser.add_argument("--mpc-config", type=Path, default=Path("configs/mpc.yaml"))
    parser.add_argument(
        "--modes-config", type=Path, default=Path("configs/modes_known.yaml")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/phase2"))
    args = parser.parse_args()

    config_paths = {
        "base": args.base_config.resolve(),
        "mpc": args.mpc_config.resolve(),
        "modes_known": args.modes_config.resolve(),
    }
    configs = {name: load_yaml(path) for name, path in config_paths.items()}
    for name, path in config_paths.items():
        _require_schema_version(configs[name], path)

    base_config = configs["base"]
    mpc_config = configs["mpc"]
    known_modes = _modes(configs["modes_known"])
    for required_mode in ("nominal", "unavailable"):
        if required_mode not in known_modes:
            raise ValueError(f"known-mode config is missing {required_mode!r}")

    grid_model = _grid_model(base_config)
    fixed_controller, fixed_filter, fixed_bounds = _fixed_controller(
        grid_model,
        known_modes["nominal"],
        base_config,
        mpc_config,
    )
    lqi_controller, lqi_filter, lqi_config = _lqi_controller(
        grid_model,
        base_config,
        mpc_config,
    )
    seed = int(base_config["project"]["seed"])
    fixed_rows, fixed_d_hat = _run_episode(
        label="fixed_nominal_mpc_nominal_mode",
        seed=seed,
        simulator=HiddenModeFrequencySimulator(grid_model, known_modes),
        scenario=_scenario("nominal", "phase2_fixed_nominal_acceptance"),
        controller=fixed_controller,
        estimator=fixed_filter,
        f0_hz=grid_model.params.f0_hz,
        sample_time_s=grid_model.params.control_period_s,
    )
    lqi_rows, lqi_d_hat = _run_episode(
        label="lqi_unavailable_ibr",
        seed=seed,
        simulator=HiddenModeFrequencySimulator(grid_model, known_modes),
        scenario=_scenario("unavailable", "phase2_lqi_acceptance"),
        controller=lqi_controller,
        estimator=lqi_filter,
        f0_hz=grid_model.params.f0_hz,
        sample_time_s=grid_model.params.control_period_s,
    )

    fixed_summary = _summarize(
        fixed_rows,
        final_d_hat_pu=fixed_d_hat,
        command_bounds={
            "u_sg_pu": fixed_bounds.u_min_pu[:1] + fixed_bounds.u_max_pu[:1],
            "u_ibr_pu": fixed_bounds.u_min_pu[1:] + fixed_bounds.u_max_pu[1:],
        },
        rate_bounds={
            "u_sg_pu_per_s": fixed_bounds.ramp_pu_per_s[0],
            "u_ibr_pu_per_s": fixed_bounds.ramp_pu_per_s[1],
        },
        expected_statuses=ACCEPTED_MPC_STATUSES,
        tail_limit_hz=FIXED_TAIL_MAX_ABS_HZ,
        require_mechanical_recovery=False,
    )
    lqi_summary = _summarize(
        lqi_rows,
        final_d_hat_pu=lqi_d_hat,
        command_bounds={
            "u_sg_pu": (lqi_config.u_sg_min_pu, lqi_config.u_sg_max_pu),
            "u_ibr_pu": (
                float(base_config["ibr_command"]["u_min_pu"]),
                float(base_config["ibr_command"]["u_max_pu"]),
            ),
        },
        rate_bounds={
            "u_sg_pu_per_s": lqi_config.u_sg_ramp_pu_per_s,
            "u_ibr_pu_per_s": lqi_config.ibr_withdraw_rate_pu_per_s,
        },
        expected_statuses=frozenset(("fallback_lqi",)),
        tail_limit_hz=LQI_TAIL_MAX_ABS_HZ,
        require_mechanical_recovery=True,
    )

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "baseline_acceptance_trajectories.csv"
    _write_csv([*fixed_rows, *lqi_rows], csv_path)

    project_root = Path(__file__).resolve().parents[1]
    source_manifest = _python_source_manifest(project_root / "src" / "d5freq")
    summary = {
        "schema_version": SCHEMA_VERSION,
        "experiment": "phase2_baseline_acceptance",
        "accepted": fixed_summary["accepted"] and lqi_summary["accepted"],
        "determinism": {
            "seed": seed,
            "measurement_noise_std_pu": 0.0,
            "load_noise_std_pu": 0.0,
        },
        "scenario": {
            "episode_duration_s": EPISODE_DURATION_S,
            "load_step_time_s": LOAD_STEP_TIME_S,
            "load_step_pu": LOAD_STEP_PU,
            "tail_start_time_s": TAIL_START_TIME_S,
            "sg_capacity_feasible": LOAD_STEP_PU
            <= float(base_config["grid"]["u_sg_max_pu"]),
            "sg_positive_capacity_margin_pu": float(
                base_config["grid"]["u_sg_max_pu"]
            )
            - LOAD_STEP_PU,
        },
        "fixed_nominal_mpc": {
            "prediction_mode": "nominal",
            "true_evaluation_mode": "nominal",
            "solver_priority": ["CLARABEL"],
            "horizon_steps": 20,
            **fixed_summary,
        },
        "lqi_fallback": {
            "true_evaluation_mode": "unavailable",
            **lqi_summary,
        },
        "hashes": {
            "config_files_sha256": {
                name: sha256_file(path) for name, path in config_paths.items()
            },
            "resolved_configs_sha256": config_sha256(configs),
            "python_source_manifest_sha256": sha256_json(source_manifest),
            "validation_script_sha256": sha256_file(Path(__file__)),
            "trajectory_csv_sha256": sha256_file(csv_path),
        },
        "python_source_manifest": source_manifest,
        "artifacts": {
            "trajectory_csv": csv_path.name,
            "summary_json": "baseline_acceptance_summary.json",
        },
        "information_boundary": {
            "controller_input": "Measurement only",
            "truth_columns_prefix": "eval_",
            "truth_used_for_control": False,
        },
    }
    json_path = output_dir / "baseline_acceptance_summary.json"
    json_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "accepted": summary["accepted"],
        "csv": str(csv_path),
        "csv_sha256": summary["hashes"]["trajectory_csv_sha256"],
        "json": str(json_path),
    }, indent=2, sort_keys=True))
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
