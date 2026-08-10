"""Run the preregistered Direction5 ACCR A0 platform qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import pandas as pd
import yaml


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.accr.platform import (
    A0BaselinePolicy,
    NORMAL_PROFILE_PROVENANCE,
    interpolate_profile,
    normal_capability,
    normal_load_profile,
)
from direction5freq.evaluation.final_protocol import plant_parameters
from direction5freq.models.plant_a_full import PlantAFull
from direction5freq.models.plant_b_andes_full import PlantBAndesFull


LOCK_PATH = REPO / "configs/direction5_accr/a0_platform_lock.yaml"
RESULTS = REPO / "results_accr/A0"
OUTPUTS = REPO / "research_outputs_accr/03_MODEL"
PROGRESS = REPO / "progress_accr"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_lock() -> dict:
    lock = yaml.safe_load(LOCK_PATH.read_text("utf-8"))
    if not lock["registered_before_execution"] or lock["final_seeds_consumed"]:
        raise RuntimeError("A0 platform lock is invalid")
    return lock


def simulate_normal(seed: int, method: str, dt_s: float) -> dict:
    lock = _load_lock()
    parameters = plant_parameters("low")
    plant = PlantAFull(parameters, dt_s=dt_s)
    state = plant.equilibrium()
    policy = A0BaselinePolicy(method, lock["normal_control_period_s"], parameters)
    profile = normal_load_profile(seed, int(lock["normal_duration_s"]))
    command = np.zeros(4)
    reserve = np.zeros(2)
    next_control = 0.0
    frequency_peak = 0.0
    frequency_square = 0.0
    terminal_frequency = []
    terminal_ace = []
    terminal_tie = []
    hard_violation = False
    reserve_peak = 0.0
    count = 0
    duration_s = float(lock["normal_duration_s"])
    for step in range(int(round(duration_s / dt_s)) + 1):
        time_s = step * dt_s
        observation = plant.public_observation(time_s, state, command)
        if time_s + 1e-10 >= next_control:
            command, reserve = policy.update(observation)
            next_control += float(lock["normal_control_period_s"])
        frequency_peak = max(frequency_peak, float(np.max(np.abs(observation.frequency_deviation_hz))))
        frequency_square += float(np.sum(observation.frequency_deviation_hz ** 2))
        reserve_peak = max(reserve_peak, float(np.max(np.abs(state.slow_reserve.power_pu))))
        count += 1
        if time_s >= duration_s - 60.0:
            terminal_frequency.append(float(np.max(np.abs(observation.frequency_deviation_hz))))
            terminal_ace.append(float(np.max(np.abs(observation.ace_pu))))
            terminal_tie.append(abs(float(observation.tie_line_pu)))
        if step < int(round(duration_s / dt_s)):
            state, diagnostics = plant.step(
                state,
                command,
                interpolate_profile(profile, time_s),
                normal_capability(seed, time_s),
                reserve,
            )
            soc = state.bess.measured_soc(parameters.bess)
            hard_violation |= bool(
                np.any(soc < parameters.bess.soc_min - 1e-9)
                or np.any(soc > parameters.bess.soc_max + 1e-9)
                or np.any(state.mechanical_power_pu < np.asarray(parameters.sg_power_lower_pu) - 1e-9)
                or np.any(state.mechanical_power_pu > np.asarray(parameters.sg_power_upper_pu) + 1e-9)
                or np.max(np.abs(diagnostics.power_balance_residual_pu)) > 1e-8
            )
    calls = pd.DataFrame(policy.calls)
    return {
        "seed": seed,
        "method": method,
        "plant": "A_full_nonlinear",
        "dt_s": dt_s,
        "duration_s": duration_s,
        "profile_provenance": NORMAL_PROFILE_PROVENANCE,
        "profile_peak_pu": float(np.max(np.abs(profile))),
        "profile_rms_pu": float(np.sqrt(np.mean(profile ** 2))),
        "profile_mean_abs_pu": float(np.max(np.abs(np.mean(profile, axis=0)))),
        "frequency_peak_hz": frequency_peak,
        "frequency_rms_hz": float(np.sqrt(frequency_square / max(2 * count, 1))),
        "terminal_frequency_peak_hz": max(terminal_frequency),
        "terminal_ace_peak_pu": max(terminal_ace),
        "terminal_tie_peak_pu": max(terminal_tie),
        "hard_violation": hard_violation,
        "slow_reserve_peak_pu": reserve_peak,
        "final_soc_min": float(np.min(state.bess.measured_soc(parameters.bess))),
        "controller_calls": len(calls),
        "attempted_solver_calls": int(calls.attempted_solver_calls.sum()),
        "fallback_calls": int(calls.fallback_used.sum()),
        "p99_solve_time_s": float(calls.solve_time_s.quantile(0.99)),
    }


def plant_a_dt_check(seed: int = 200) -> pd.DataFrame:
    # A 300 s physical cross-check is sufficient for integration-step
    # convergence; the full one-hour registered rows use dt=0.05 s.
    lock = _load_lock()
    original = lock["normal_duration_s"]
    lock["normal_duration_s"] = 300.0
    temporary = RESULTS / "_a0_dt_lock.yaml"
    # Avoid mutating the preregistered lock: run the loop through local helper.
    rows = []
    for dt_s in (float(lock["plant_a_dt_s"]), float(lock["plant_a_convergence_dt_s"])):
        parameters = plant_parameters("low")
        plant = PlantAFull(parameters, dt_s=dt_s)
        state = plant.equilibrium()
        policy = A0BaselinePolicy("fixed_allocation_anti_windup_pi", 4.0, parameters)
        profile = normal_load_profile(seed, 300)
        command = np.zeros(4); reserve = np.zeros(2); next_control = 0.0; peak = 0.0
        for step in range(int(round(300.0 / dt_s)) + 1):
            time_s = step * dt_s
            observation = plant.public_observation(time_s, state, command)
            if time_s + 1e-10 >= next_control:
                command, reserve = policy.update(observation); next_control += 4.0
            peak = max(peak, float(np.max(np.abs(observation.frequency_deviation_hz))))
            if step < int(round(300.0 / dt_s)):
                state, _ = plant.step(state, command, interpolate_profile(profile, time_s), normal_capability(seed, time_s), reserve)
        rows.append({"plant": "A_full_nonlinear", "dt_s": dt_s, "frequency_peak_hz": peak})
    frame = pd.DataFrame(rows)
    frame["peak_difference_hz"] = abs(frame.frequency_peak_hz.iloc[0] - frame.frequency_peak_hz.iloc[1])
    return frame


def plant_b_check(seed: int = 200) -> dict:
    lock = _load_lock()
    duration_s = 120.0
    profile = normal_load_profile(seed, int(duration_s))
    parameters = plant_parameters("low", nominal_frequency_hz=60.0)
    policy = A0BaselinePolicy("fixed_allocation_anti_windup_pi", 4.0, parameters)

    def public_policy(observation):
        action, _ = policy.update(observation)
        return action

    plant = PlantBAndesFull(dt_s=float(lock["native_plant_b_dt_s"]))
    trace = plant.run_causal_closed_loop(
        duration_s=duration_s,
        control_period_s=4.0,
        load_profile=lambda value: interpolate_profile(profile, value),
        policy=public_policy,
        capability_profile=lambda value: normal_capability(seed, value),
        slow_reserve_profile=lambda _time, _observation: policy.reserve_request,
    )
    return {
        "plant": "B_native_ANDES_Kundur",
        "duration_s": duration_s,
        "dt_s": float(lock["native_plant_b_dt_s"]),
        "frequency_peak_hz": float(np.max(np.abs(trace.frequency_deviation_hz))),
        "frequency_rms_hz": float(np.sqrt(np.mean(trace.frequency_deviation_hz ** 2))),
        "converged": trace.converged,
        "native_network": trace.native_network,
        "initialization_diagnostic_enabled": trace.initialization_diagnostic_enabled,
        "algebraic_power_balance_p99_pu": trace.algebraic_power_balance_p99_pu,
    }


def run_plant_b_isolated() -> dict:
    """Run native ANDES in a fresh process, never after a Python process pool."""

    output_path = RESULTS / "PLANT_B_WORKER_RESULT.json"
    environment = os.environ.copy()
    environment.update({
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "DIRECTION5_ANDES_AUTOGEN": "FORBIDDEN",
    })
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--workers", "1",
            "--plant-b-worker-output", str(output_path),
        ],
        cwd=REPO,
        env=environment,
        check=False,
        timeout=1800.0,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"isolated native Plant-B worker failed with exit code {completed.returncode}"
        )
    if not output_path.is_file():
        raise RuntimeError("isolated native Plant-B worker produced no result")
    return json.loads(output_path.read_text("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workers",
        type=int,
        choices=(1,),
        default=1,
        help="A0 is intentionally single-process; values above 1 are refused.",
    )
    parser.add_argument("--plant-b-worker-output", type=Path, default=None)
    args = parser.parse_args()
    if os.environ.get("DIRECTION5_RESOURCE_GUARDED") != "1":
        raise SystemExit(
            "Refusing unguarded A0 execution. Use scripts/direction5_accr/"
            "run_a0_guarded.py; no simulation was started."
        )
    if args.plant_b_worker_output is not None:
        worker_result = plant_b_check()
        args.plant_b_worker_output.parent.mkdir(parents=True, exist_ok=True)
        args.plant_b_worker_output.write_text(
            json.dumps(worker_result, indent=2) + "\n", encoding="utf-8"
        )
        return
    started = time.perf_counter()
    lock = _load_lock()
    RESULTS.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    PROGRESS.mkdir(parents=True, exist_ok=True)
    tasks = [
        (int(seed), method, float(lock["plant_a_dt_s"]))
        for seed in lock["normal_profile_seeds"]
        for method in lock["normal_methods"]
    ]
    # Deliberately sequential. Native ANDES code generation uses the
    # ``multiprocess`` package internally; combining it with a Python process
    # pool on Windows caused nested spawn and catastrophic commit exhaustion.
    rows = [simulate_normal(*task) for task in tasks]
    normal = pd.DataFrame(rows).sort_values(["seed", "method"]).reset_index(drop=True)
    normal.to_csv(RESULTS / "NORMAL1H_BASELINE_VALIDATION.csv", index=False)
    normal.to_parquet(RESULTS / "NORMAL1H_BASELINE_VALIDATION.parquet", index=False)
    dt_check = plant_a_dt_check()
    dt_check.to_csv(RESULTS / "PLANT_A_DT_CONVERGENCE.csv", index=False)
    plant_b = run_plant_b_isolated()
    pd.DataFrame([plant_b]).to_csv(RESULTS / "PLANT_A_B_CROSSCHECK.csv", index=False)
    gates = {
        "all_registered_normal_rows_present": len(normal) == len(tasks),
        "frequency_peak": bool(normal.frequency_peak_hz.le(lock["gates"]["frequency_peak_hz_max"]).all()),
        "frequency_rms": bool(normal.frequency_rms_hz.le(lock["gates"]["frequency_rms_hz_max"]).all()),
        "terminal_frequency": bool(normal.terminal_frequency_peak_hz.le(lock["gates"]["terminal_frequency_hz_max"]).all()),
        "terminal_ace": bool(normal.terminal_ace_peak_pu.le(lock["gates"]["terminal_ace_pu_max"]).all()),
        "hard_violations_zero": not bool(normal.hard_violation.any()),
        "profile_scale_and_zero_mean": bool(normal.profile_peak_pu.le(0.0120001).all() and normal.profile_mean_abs_pu.le(1e-12).all()),
        "plant_a_dt_converged": bool(dt_check.peak_difference_hz.max() <= lock["gates"]["plant_a_dt_peak_difference_hz_max"]),
        "plant_b_native_converged": bool(plant_b["native_network"] and plant_b["converged"] and plant_b["initialization_diagnostic_enabled"]),
        "plant_b_frequency_quality": bool(plant_b["frequency_peak_hz"] <= lock["gates"]["native_plant_b_frequency_peak_hz_max"]),
        "mpc_realtime": bool(normal.loc[normal.attempted_solver_calls.gt(0), "p99_solve_time_s"].le(0.5 * lock["normal_control_period_s"]).all()),
        "historical_result_frozen": lock["historical_closure_commit"] == "011fab97ef8f46dfc2eb0438cd7595ba46e3e0b7",
        "fresh_final_seeds_unconsumed": not lock["final_seeds_consumed"],
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    result = {
        "schema": "direction5.accr.progress.v1",
        "stage": "A0",
        "status": status,
        "gate": "BENCHMARK_PLATFORM_VALID" if status == "PASS" else "BENCHMARK_PLATFORM_NOT_VALID",
        "lock_sha256": _sha256(LOCK_PATH),
        "normal_rows": len(normal),
        "normal_methods": list(lock["normal_methods"]),
        "normal_seeds": list(lock["normal_profile_seeds"]),
        "plant_b": plant_b,
        "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
        "final_seeds_consumed": False,
        "elapsed_s": time.perf_counter() - started,
        "next_stage": "A1" if status == "PASS" else "A8_NEGATIVE_PACKAGE",
    }
    (RESULTS / "A0_SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (PROGRESS / "A0.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    report = f"""# Normal1h platform rebuild\n\nA0 status: **{status}**.\n\nThe decisive repair separates local PFR from the remote SFR command-delay pipeline.\nAll historical results remain frozen. The new normal profile is synthetic, bounded,\nzero-mean and detrended; it is not represented as public measured data.\n\n- registered one-hour rows: {len(normal)}\n- worst frequency peak: {normal.frequency_peak_hz.max():.6f} Hz\n- worst frequency RMS: {normal.frequency_rms_hz.max():.6f} Hz\n- hard violations: {int(normal.hard_violation.sum())}\n- Plant-A dt peak difference: {dt_check.peak_difference_hz.max():.6g} Hz\n- native Plant-B peak: {plant_b['frequency_peak_hz']:.6f} Hz\n- native Plant-B converged: {plant_b['converged']}\n- failed Gates: {result['failed_gates']}\n"""
    (OUTPUTS / "NORMAL1H_PLATFORM_REBUILD.md").write_text(report, encoding="utf-8")
    print(json.dumps(result, indent=2))
    if status != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
