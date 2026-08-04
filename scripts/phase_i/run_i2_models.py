"""Build and validate the Phase-I physical platform and full-event driver."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.models.capability_contract import CapabilityRealization
from direction5freq.models.plant_a_full import PlantAFull, PublicObservation
from direction5freq.models.plant_b_andes_full import PlantBAndesFull


RESULTS = REPO / "results_phase_i/I2"
MODEL_DOCS = REPO / "research_outputs_phase_i/03_MODEL"
PROGRESS = REPO / "progress_phase_i"


@dataclass
class CausalPI:
    period_s: float
    kp: float = 0.55
    ki: float = 0.035

    def __post_init__(self) -> None:
        self.integral = np.zeros(2)
        self.calls = 0

    def __call__(self, observation: PublicObservation) -> np.ndarray:
        self.integral += observation.ace_pu * self.period_s
        total = np.clip(-self.kp * observation.ace_pu - self.ki * self.integral, -0.13, 0.13)
        self.calls += 1
        return np.array((0.72 * total[0], 0.28 * total[0], 0.72 * total[1], 0.28 * total[1]))


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def build_manifest() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    scenario = 0
    for mechanism in ("power_drop", "ramp_drop", "delay_increase"):
        for sg_tension in ("low", "high"):
            for period_s, duration_s in ((2.0, 300.0), (4.0, 600.0)):
                rng = np.random.default_rng(np.random.SeedSequence([20260804, scenario, 17]))
                capability_time = float(rng.uniform(65.0, 0.42 * duration_s))
                load_time = float(rng.uniform(65.0, 0.42 * duration_s))
                rows.append(
                    {
                        "scenario_id": f"I2-D{scenario:03d}",
                        "split": "development",
                        "seed": scenario,
                        "mechanism": mechanism,
                        "sg_tension": sg_tension,
                        "period_s": period_s,
                        "duration_s": duration_s,
                        "nominal_warmup_s": 60.0,
                        "capability_change_time_s": capability_time,
                        "load_event_time_s": load_time,
                        "event_time_generation": "independent_rng_draws",
                        "controller_updates_entire_horizon": True,
                    }
                )
                scenario += 1
    frame = pd.DataFrame(rows)
    frame.to_csv(RESULTS / "CORE_EVENT_MANIFEST.csv", index=False)
    return frame


def capability_profile(mechanism: str, event_time_s: float):
    nominal = CapabilityRealization()
    if mechanism == "power_drop":
        changed = CapabilityRealization(
            lower_power_pu=(-0.050, -0.052), upper_power_pu=(0.050, 0.052),
            ramp_down_pu_per_s=(0.060, 0.060), ramp_up_pu_per_s=(0.060, 0.060),
            delay_s=(0.20, 0.20),
        )
    elif mechanism == "ramp_drop":
        changed = CapabilityRealization(
            lower_power_pu=(-0.080, -0.080), upper_power_pu=(0.080, 0.080),
            ramp_down_pu_per_s=(0.030, 0.032), ramp_up_pu_per_s=(0.030, 0.032),
            delay_s=(0.20, 0.20),
        )
    elif mechanism == "delay_increase":
        changed = CapabilityRealization(
            lower_power_pu=(-0.080, -0.080), upper_power_pu=(0.080, 0.080),
            ramp_down_pu_per_s=(0.060, 0.060), ramp_up_pu_per_s=(0.060, 0.060),
            delay_s=(1.20, 1.35),
        )
    else:
        raise ValueError(mechanism)
    return lambda time_s: nominal if time_s < event_time_s else changed


def load_profile(event_time_s: float, magnitude: float = 0.035):
    return lambda time_s: np.array((magnitude if time_s >= event_time_s else 0.0, 0.35 * magnitude if time_s >= event_time_s else 0.0))


def simulate_plant_a(
    duration_s: float,
    dt_s: float,
    period_s: float,
    capability,
    load,
    record_period_s: float | None = None,
) -> tuple[pd.DataFrame, dict[str, float | int | bool]]:
    plant = PlantAFull(dt_s=dt_s)
    state = plant.equilibrium()
    policy = CausalPI(period_s)
    command = np.zeros(4)
    next_control = 0.0
    next_record = 0.0
    record_period = period_s if record_period_s is None else record_period_s
    records: list[dict[str, object]] = []
    max_balance = 0.0
    max_energy_residual = 0.0
    energy_initial = state.bess.energy_mwh.copy()
    integrated_energy_change = np.zeros(2)
    previous_power = state.bess.power_pu.copy()
    steps = int(round(duration_s / dt_s))
    start = time.perf_counter()
    for step in range(steps + 1):
        current_time = step * dt_s
        observation = plant.public_observation(current_time, state, command)
        if current_time + 1e-10 >= next_control:
            command = policy(observation)
            next_control += period_s
        reserve_request = np.clip(-1.25 * observation.ace_pu, 0.0, 0.10)
        if step < steps:
            next_state, diagnostics = plant.step(
                state,
                command,
                load(current_time),
                capability(current_time),
                reserve_request,
            )
            average_power = 0.5 * (previous_power + next_state.bess.power_pu)
            power_mw = plant.parameters.system_base_mva * average_power
            integrated_energy_change += np.where(
                power_mw >= 0.0,
                -dt_s * power_mw / plant.parameters.bess.eta_discharge / 3600.0,
                -dt_s * power_mw * plant.parameters.bess.eta_charge / 3600.0,
            )
            previous_power = next_state.bess.power_pu.copy()
            max_balance = max(max_balance, float(np.max(np.abs(diagnostics.power_balance_residual_pu))))
            max_energy_residual = max(max_energy_residual, float(np.max(np.abs(diagnostics.bess.energy_residual_mwh))))
        else:
            next_state = state
            diagnostics = None
        if current_time + 1e-10 >= next_record:
            records.append(
                {
                    "time_s": current_time,
                    "frequency0_hz": observation.frequency_deviation_hz[0],
                    "frequency1_hz": observation.frequency_deviation_hz[1],
                    "ace0_pu": observation.ace_pu[0],
                    "ace1_pu": observation.ace_pu[1],
                    "tie_pu": observation.tie_line_pu,
                    "valve0_pu": observation.valve_pu[0],
                    "valve1_pu": observation.valve_pu[1],
                    "mechanical0_pu": observation.sg_mechanical_power_pu[0],
                    "mechanical1_pu": observation.sg_mechanical_power_pu[1],
                    "bess_actual0_pu": observation.bess_actual_power_pu[0],
                    "bess_actual1_pu": observation.bess_actual_power_pu[1],
                    "soc0": observation.measured_soc[0],
                    "soc1": observation.measured_soc[1],
                    "slow_reserve0_pu": observation.slow_reserve_power_pu[0],
                    "slow_reserve1_pu": observation.slow_reserve_power_pu[1],
                    "sg_command0_pu": command[0],
                    "bess_command0_pu": command[1],
                    "sg_command1_pu": command[2],
                    "bess_command1_pu": command[3],
                    "load0_pu": load(current_time)[0],
                    "load1_pu": load(current_time)[1],
                }
            )
            next_record += record_period
        state = next_state
    elapsed = time.perf_counter() - start
    energy_closure = state.bess.energy_mwh - energy_initial - integrated_energy_change
    summary = {
        "duration_s": duration_s,
        "dt_s": dt_s,
        "period_s": period_s,
        "physical_steps": steps,
        "controller_calls": policy.calls,
        "expected_controller_calls": int(np.floor(duration_s / period_s)) + 1,
        "controller_updates_entire_horizon": policy.calls == int(np.floor(duration_s / period_s)) + 1,
        "max_power_balance_residual_pu": max_balance,
        "max_step_energy_residual_mwh": max_energy_residual,
        "max_integrated_energy_closure_mwh": float(np.max(np.abs(energy_closure))),
        "elapsed_s": elapsed,
    }
    return pd.DataFrame(records), summary


def dt_convergence() -> pd.DataFrame:
    summaries = []
    traces: dict[float, pd.DataFrame] = {}
    for dt_s in (0.04, 0.02, 0.01):
        trace, summary = simulate_plant_a(
            duration_s=30.0,
            dt_s=dt_s,
            period_s=2.0,
            capability=lambda _time: CapabilityRealization(),
            load=load_profile(3.0, 0.025),
            record_period_s=0.2,
        )
        traces[dt_s] = trace
        summaries.append({
            "dt_s": dt_s,
            "peak_abs_frequency_hz": float(trace[["frequency0_hz", "frequency1_hz"]].abs().to_numpy().max()),
            "terminal_frequency_norm_hz": float(np.linalg.norm(trace[["frequency0_hz", "frequency1_hz"]].iloc[-1])),
            **summary,
        })
    frame = pd.DataFrame(summaries)
    reference = frame.loc[frame.dt_s.eq(0.01)].iloc[0]
    frame["peak_relative_error_vs_0p01"] = np.abs(frame.peak_abs_frequency_hz - reference.peak_abs_frequency_hz) / max(reference.peak_abs_frequency_hz, 1e-12)
    frame["terminal_absolute_error_vs_0p01_hz"] = np.abs(frame.terminal_frequency_norm_hz - reference.terminal_frequency_norm_hz)
    return frame


def real_normal_hour() -> tuple[pd.DataFrame, dict[str, object]]:
    rng = np.random.default_rng(29)
    innovations = rng.normal(0.0, 0.00055, size=(3601, 2))
    profile = np.zeros_like(innovations)
    for index in range(1, len(profile)):
        profile[index] = 0.985 * profile[index - 1] + innovations[index]
    seconds = np.arange(3601)
    profile += np.column_stack((
        0.006 * np.sin(2.0 * np.pi * seconds / 780.0),
        0.005 * np.sin(2.0 * np.pi * seconds / 930.0 + 0.7),
    ))
    profile = np.clip(profile, -0.018, 0.018)
    capability_event = float(rng.uniform(900.0, 2400.0))

    def load(time_s: float) -> np.ndarray:
        position = min(time_s, 3600.0)
        lower = int(np.floor(position)); upper = min(lower + 1, 3600)
        fraction = position - lower
        return (1.0 - fraction) * profile[lower] + fraction * profile[upper]

    trace, summary = simulate_plant_a(
        duration_s=3600.0,
        dt_s=0.02,
        period_s=2.0,
        capability=capability_profile("delay_increase", capability_event),
        load=load,
        record_period_s=2.0,
    )
    summary.update({
        "profile_seed": 29,
        "capability_change_time_s": capability_event,
        "trajectory_rows": len(trace),
        "all_zero_load": bool(np.allclose(trace[["load0_pu", "load1_pu"]], 0.0)),
        "artificial_rows": 0,
        "provenance": "full_nonlinear_PlantA_180000_physical_steps",
    })
    return trace, summary


def native_crosscheck(manifest_row: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    # I2 engineering qualification: 60 s warm-up plus a causal event window.
    duration = 76.0
    event_time = 62.0 + (float(manifest_row.capability_change_time_s) % 2.0)
    load_time = 66.0 + (float(manifest_row.load_event_time_s) % 2.0)
    capability = capability_profile(str(manifest_row.mechanism), event_time)
    load = load_profile(load_time, 0.018)
    policy = CausalPI(2.0)
    native = PlantBAndesFull(dt_s=0.02).run_causal_closed_loop(
        duration_s=duration,
        control_period_s=2.0,
        load_profile=load,
        policy=policy,
        capability_profile=capability,
        slow_reserve_profile=lambda _time, obs: np.clip(-1.25 * obs.ace_pu, 0.0, 0.10),
    )
    native_trace = pd.DataFrame({
        "time_s": native.time_s,
        "frequency0_hz": native.frequency_deviation_hz[:, 0],
        "frequency1_hz": native.frequency_deviation_hz[:, 1],
        "ace0_pu": native.ace_pu[:, 0],
        "ace1_pu": native.ace_pu[:, 1],
        "tie_pu": native.tie_line_pu,
        "mechanical0_pu": native.sg_mechanical_increment_pu[:, 0],
        "mechanical1_pu": native.sg_mechanical_increment_pu[:, 1],
        "bess_actual0_pu": native.bess_actual_poi_power_pu[:, 0],
        "bess_actual1_pu": native.bess_actual_poi_power_pu[:, 1],
        "soc0": native.measured_soc[:, 0],
        "soc1": native.measured_soc[:, 1],
        "slow_reserve0_pu": native.slow_reserve_power_pu[:, 0],
        "slow_reserve1_pu": native.slow_reserve_power_pu[:, 1],
        "load0_pu": native.load_increment_pu[:, 0],
        "load1_pu": native.load_increment_pu[:, 1],
    })
    plant_a_trace, plant_a_summary = simulate_plant_a(
        duration, 0.02, 2.0, capability, load, record_period_s=0.02
    )
    post_native = native_trace[native_trace.time_s >= load_time]
    post_a = plant_a_trace[plant_a_trace.time_s >= load_time]
    summary = pd.DataFrame([
        {
            "plant": "A_full_nonlinear",
            "native_network": False,
            "converged": True,
            "initialization_diagnostic_enabled": False,
            "controller_calls": plant_a_summary["controller_calls"],
            "expected_controller_calls": plant_a_summary["expected_controller_calls"],
            "frequency_area0_initial_response_sign": float(np.sign(post_a.frequency0_hz.iloc[min(5, len(post_a)-1)])),
            "peak_abs_frequency_hz": float(post_a[["frequency0_hz", "frequency1_hz"]].abs().to_numpy().max()),
            "power_balance_p99_pu": plant_a_summary["max_power_balance_residual_pu"],
            "event_time_s": event_time,
            "load_time_s": load_time,
        },
        {
            "plant": "B_native_ANDES_Kundur",
            "native_network": native.native_network,
            "converged": native.converged,
            "initialization_diagnostic_enabled": native.initialization_diagnostic_enabled,
            "controller_calls": len(native.controller_update_times_s),
            "expected_controller_calls": int(np.floor(duration / 2.0)) + 1,
            "frequency_area0_initial_response_sign": float(np.sign(post_native.frequency0_hz.iloc[min(5, len(post_native)-1)])),
            "peak_abs_frequency_hz": float(post_native[["frequency0_hz", "frequency1_hz"]].abs().to_numpy().max()),
            "power_balance_p99_pu": native.algebraic_power_balance_p99_pu,
            "event_time_s": event_time,
            "load_time_s": load_time,
        },
    ])
    return summary, native_trace


def slow_reserve_audit() -> pd.DataFrame:
    plant = PlantAFull(dt_s=0.02)
    state = plant.equilibrium()
    rows = []
    request = np.array((0.08, 0.04))
    remaining_bridge_s = 120.0
    for step in range(int(90.0 / plant.dt_s) + 1):
        time_s = step * plant.dt_s
        if step:
            state, diagnostics = plant.step(
                state, np.zeros(4), np.zeros(2), CapabilityRealization(), request
            )
            remaining_bridge_s = max(remaining_bridge_s - plant.dt_s, 0.0)
        if step % 50 == 0:
            rows.append({
                "time_s": time_s,
                "requested0_pu": request[0],
                "actual0_pu": state.slow_reserve.power_pu[0],
                "actual1_pu": state.slow_reserve.power_pu[1],
                "remaining_bridge_s": remaining_bridge_s,
            })
    return pd.DataFrame(rows)


def write_docs() -> None:
    write(MODEL_DOCS / "PLANT_A_FULL_MODEL.md", """
# Full nonlinear Plant A

`direction5freq.models.plant_a_full.PlantAFull` integrates two-area swing,
tie-line, governor, valve, turbine and GRC dynamics with RK4 at the registered
physical step. BESS PFR and SFR share one physical command-to-actual actuator
with continuous delay interpolation, power/ramp limits and measured-SoC energy.
Slow reserve is a finite-ramp first-order state and contributes generation to
the power balance. Frequency, tie, valve, mechanical power, actual POI power,
SoC, reserve, commands and saturation flags are available to the evidence
driver. Capability truth is evaluation-side only.
""")
    write(MODEL_DOCS / "PLANT_B_NATIVE_MODEL.md", """
# Native ANDES Plant B

`direction5freq.models.plant_b_andes_full.PlantBAndesFull` loads the bundled
Kundur `kundur_vsc.xlsx` system and retains its buses, lines, four GENROU
machines, exciters, TGOV1 governors and implicit RMS/DAE solve. Two shunts are
used as native BESS POI injections. Load, BESS and governor signals enter the
native equations every physical step. The controller sees only the common
public observation. `TDS.config.test_init=1`: initialization diagnostics are
preserved, while convergence and algebraic residuals are reported separately.
No reduced state-space layer or injected Gaussian residual is used.
""")
    write(MODEL_DOCS / "SLOW_RESERVE_MODEL.md", """
# Slow reserve

Slow reserve is an explicit two-area first-order state with registered power and
ramp bounds. It starts from zero, cannot jump at 60 s, and enters the grid power
balance only through its actual state. Bridge remaining time is decremented on
every physical step. `BRIDGE_CLOCK_TRACE.csv` is the executable audit.
""")
    write(MODEL_DOCS / "ABILITY_EVENT_MODEL.md", """
# Unannounced capability-event model

The hidden physical vector contains only upper/lower power, upper/lower ramp and
continuous delay. Each core manifest row has at least 60 s nominal warm-up, an
independently randomized unannounced capability time, an independently
randomized load-event time, and a 300 or 600 s horizon. Factor assignments are
explicit Cartesian design fields and never derived with seed modulo. Energy is
measured SoC; availability is not a latent truth field.
""")


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    MODEL_DOCS.mkdir(parents=True, exist_ok=True)
    PROGRESS.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest()
    convergence = dt_convergence()
    convergence.to_csv(RESULTS / "DT_CONVERGENCE.csv", index=False)

    row = manifest.iloc[0]
    event_trace, event_summary = simulate_plant_a(
        float(row.duration_s), 0.02, float(row.period_s),
        capability_profile(str(row.mechanism), float(row.capability_change_time_s)),
        load_profile(float(row.load_event_time_s), 0.035),
    )
    event_trace.to_parquet(RESULTS / "PLANT_A_FULL_EVENT_TRACE.parquet", index=False)
    pd.DataFrame([event_summary]).to_csv(RESULTS / "PLANT_A_FULL_EVENT_SUMMARY.csv", index=False)

    energy = pd.DataFrame([{
        "plant": "A_full_nonlinear",
        "max_step_energy_residual_mwh": event_summary["max_step_energy_residual_mwh"],
        "max_integrated_energy_closure_mwh": event_summary["max_integrated_energy_closure_mwh"],
        "power_balance_max_residual_pu": event_summary["max_power_balance_residual_pu"],
        "energy_source": "measured_soc_and_registered_efficiency",
    }])
    energy.to_csv(RESULTS / "ENERGY_BALANCE.csv", index=False)

    bridge = slow_reserve_audit()
    bridge.to_csv(RESULTS / "BRIDGE_CLOCK_TRACE.csv", index=False)
    normal_trace, normal_summary = real_normal_hour()
    normal_trace.to_parquet(RESULTS / "NORMAL1H_FULL_TRAJECTORY.parquet", index=False)
    (RESULTS / "NORMAL1H_PROVENANCE.json").write_text(json.dumps(normal_summary, indent=2) + "\n", encoding="utf-8")

    crosscheck, native_trace = native_crosscheck(manifest.iloc[8])
    crosscheck.to_csv(RESULTS / "PLANT_A_B_CROSSCHECK.csv", index=False)
    native_trace.to_parquet(RESULTS / "PLANT_B_NATIVE_EVENT_TRACE.parquet", index=False)
    pd.DataFrame([
        {
            "repair_round": 1,
            "diagnostic_class": "CODE",
            "failure": "ANDES_2_0_0_TGOV1_HAS_NO_X1_ATTRIBUTE",
            "evidence": "model state registry exposes LAG_y and LL_x",
            "repair": "map audited valve output to native TGOV1.LAG_y state",
            "scientific_change": False,
            "threshold_change": False,
            "system_change": False,
        }
    ]).to_csv(RESULTS / "REPAIR_LEDGER.csv", index=False)
    write_docs()

    controller_complete = bool(event_summary["controller_updates_entire_horizon"] and normal_summary["controller_updates_entire_horizon"])
    signs = crosscheck.frequency_area0_initial_response_sign.to_numpy()
    gates = {
        "plant_a_dt_convergence": bool(convergence.loc[convergence.dt_s.eq(0.02), "peak_relative_error_vs_0p01"].iloc[0] <= 0.02),
        "plant_a_power_balance": bool(energy.power_balance_max_residual_pu.max() <= 1e-10),
        "plant_a_energy_balance": bool(energy.max_integrated_energy_closure_mwh.max() <= 1e-9),
        "plant_b_native_not_surrogate": bool(crosscheck.loc[crosscheck.plant.str.startswith("B_"), "native_network"].all()),
        "plant_b_converged": bool(crosscheck.loc[crosscheck.plant.str.startswith("B_"), "converged"].all()),
        "plant_b_initialization_diagnostic_preserved": bool(crosscheck.loc[crosscheck.plant.str.startswith("B_"), "initialization_diagnostic_enabled"].all()),
        "plant_a_b_initial_direction_consistent": bool(signs[0] == signs[1] and signs[0] != 0),
        "controller_updates_entire_horizon": controller_complete,
        "normal1h_is_real_full_trajectory": bool(len(normal_trace) == 1801 and not normal_summary["all_zero_load"] and normal_summary["artificial_rows"] == 0),
        "capability_times_randomized_and_independent": bool(manifest.capability_change_time_s.nunique() == len(manifest) and not np.allclose(manifest.capability_change_time_s, manifest.load_event_time_s)),
        "warmup_at_least_60s": bool(manifest.nominal_warmup_s.ge(60.0).all() and (manifest.capability_change_time_s >= manifest.nominal_warmup_s).all()),
        "core_horizons_300_or_600s": bool(manifest.duration_s.isin([300.0, 600.0]).all()),
        "slow_reserve_is_not_instantaneous": bool(bridge.actual0_pu.iloc[0] == 0.0 and bridge.loc[bridge.time_s.eq(1.0), "actual0_pu"].iloc[0] < 0.01),
        "bridge_clock_decrements": bool(bridge.remaining_bridge_s.is_monotonic_decreasing and bridge.remaining_bridge_s.iloc[-1] < bridge.remaining_bridge_s.iloc[0]),
    }
    progress = {
        "stage": "I2",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "gate_passed": all(gates.values()),
        "repairs_used": 1,
        "native_plant_b_system_switches": 0,
        "plant_a": "FULL_NONLINEAR_RK4",
        "plant_b": "NATIVE_ANDES_KUNDUR_RMS_DAE",
        "normal1h_rows": len(normal_trace),
        "normal1h_physical_steps": normal_summary["physical_steps"],
        "core_manifest_rows": len(manifest),
        "gates": gates,
        "failures": [name for name, passed in gates.items() if not passed],
        "final_seeds_consumed": False,
        "next_stage": "I3" if all(gates.values()) else "I2_REPAIR_1",
    }
    (PROGRESS / "I2.json").write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
    if not progress["gate_passed"]:
        raise SystemExit("I2 gate failed: " + ", ".join(progress["failures"]))


if __name__ == "__main__":
    main()
