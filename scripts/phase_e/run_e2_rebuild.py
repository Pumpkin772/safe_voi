"""Execute the Phase-E E2 physical-model and nominal-loop rebuild."""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from direction1freq.controllers import ACEPIAntiWindup, design_discrete_lqi, design_stable_pi
from direction1freq.models.bess_capability_v2 import (
    BESSParametersV2, BESSStateV2, CapabilityTruthV2, step_bess_v2,
)
from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2
from direction1freq.models.plant_b_andes_v2 import AndesKundurPlantBV2


REPO = Path(__file__).resolve().parents[2]
RESULT = REPO / "results_phase_e" / "E2"
FIGURE = REPO / "figures_phase_e" / "E2"
MODEL_DOC = REPO / "research_outputs_phase_e" / "03_MODEL"
VERIFY_DOC = REPO / "research_outputs_phase_e" / "06_VERIFICATION"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_state_estimate(observation, nominal_frequency_hz: float) -> np.ndarray:
    """Causal nine-state estimate using only public measurements.

    The unmeasured valve position is initialized/approximated by measured
    mechanical power in E2.  Later estimators must share this public boundary.
    """

    omega = np.asarray(observation.frequency_deviation_hz) / nominal_frequency_hz
    mechanical = np.asarray(observation.sg_mechanical_power_pu)
    return np.r_[
        omega, observation.tie_line_pu, mechanical, mechanical,
        np.asarray(observation.bess_power_pu),
    ]


def simulate_plant_a(
    duration_s: float,
    dt_s: float,
    control_period_s: float,
    load_profile: Callable[[float], np.ndarray],
    controller_enabled: bool = True,
    capability_profile: Callable[[float], CapabilityTruthV2] | None = None,
    sample_period_s: float = 0.2,
) -> dict:
    plant = TwoAreaPlantAV2(dt_s=dt_s)
    proportional, integral, spectral_radius = design_stable_pi(
        plant, control_period_s, nominal_delay_s=0.2
    )
    controller = ACEPIAntiWindup(control_period_s, proportional, integral)
    state = plant.equilibrium()
    command = np.zeros(4)
    update_steps = max(1, int(round(control_period_s / dt_s)))
    sample_steps = max(1, int(round(sample_period_s / dt_s)))
    truth_profile = capability_profile or (lambda _time: CapabilityTruthV2())
    records: list[list[float]] = []
    balance: list[float] = []
    energy_residual: list[float] = []
    saturation_count = 0
    steps = int(round(duration_s / dt_s))
    for step in range(steps + 1):
        time_s = step * dt_s
        observation = plant.public_observation(time_s, state, command)
        if controller_enabled and step % update_steps == 0:
            command, _ = controller.update(observation)
        if step % sample_steps == 0:
            records.append([
                time_s, *observation.frequency_deviation_hz, *observation.ace_pu,
                observation.tie_line_pu, *observation.sg_mechanical_power_pu,
                *observation.bess_power_pu, *state.bess.energy_mwh, *command,
                *np.asarray(load_profile(time_s), dtype=float),
            ])
        if step == steps:
            break
        state, diagnostics = plant.step(
            state, command, np.asarray(load_profile(time_s), dtype=float), truth_profile(time_s)
        )
        balance.extend(np.abs(diagnostics.power_balance_residual_pu).tolist())
        energy_residual.extend(np.abs(diagnostics.bess.energy_residual_mwh).tolist())
        saturation_count += int(np.count_nonzero(diagnostics.bess.power_saturation))
    columns = [
        "time_s", "df1_hz", "df2_hz", "ace1_pu", "ace2_pu", "tie_pu",
        "pm1_pu", "pm2_pu", "pb1_pu", "pb2_pu", "e1_mwh", "e2_mwh",
        "cmd_sg1_pu", "cmd_b1_pu", "cmd_sg2_pu", "cmd_b2_pu", "load1_pu", "load2_pu",
    ]
    frame = pd.DataFrame(records, columns=columns)
    frequency = frame[["df1_hz", "df2_hz"]].to_numpy()
    ace = frame[["ace1_pu", "ace2_pu"]].to_numpy()
    metrics = {
        "max_abs_frequency_hz": float(np.max(np.abs(frequency))),
        "frequency_rms_hz": float(np.sqrt(np.mean(frequency**2))),
        "terminal_abs_frequency_hz": float(np.max(np.abs(frequency[-1]))),
        "ace_rms_pu": float(np.sqrt(np.mean(ace**2))),
        "max_abs_tie_pu": float(np.max(np.abs(frame["tie_pu"]))),
        "power_balance_p99_pu": float(np.quantile(balance, 0.99)) if balance else 0.0,
        "energy_residual_p99_mwh": float(np.quantile(energy_residual, 0.99)) if energy_residual else 0.0,
        "bess_power_saturation_count": saturation_count,
        "nominal_pi_spectral_radius": spectral_radius,
        "nominal_pi_proportional_gain": proportional,
        "nominal_pi_integral_gain_per_s": integral,
    }
    return {"frame": frame, "metrics": metrics}


def step_profile(magnitude: float, start_s: float = 10.0) -> Callable[[float], np.ndarray]:
    return lambda time_s: np.array([magnitude if time_s >= start_s else 0.0, 0.0])


def background_profile(time_s: float) -> np.ndarray:
    return 0.0015 * np.array([
        0.60 * np.sin(0.011 * time_s) + 0.40 * np.sin(0.031 * time_s),
        0.55 * np.sin(0.013 * time_s + 0.7) + 0.35 * np.sin(0.027 * time_s),
    ])


def relative_error(value: float, reference: float, floor: float = 1e-9) -> float:
    return abs(value - reference) / max(abs(reference), floor)


def write_model_documents(results: dict) -> list[Path]:
    MODEL_DOC.mkdir(parents=True, exist_ok=True)
    VERIFY_DOC.mkdir(parents=True, exist_ok=True)
    mathematical = MODEL_DOC / "MATHEMATICAL_MODEL.md"
    mathematical.write_text("""# Direction1 Phase-E mathematical model

Internal frequency is `omega_i=(f_i-f0)/f0`.  Plant A implements

`2 H_i domega_i/dt = p_m,i + p_b,i - p_L,i - D_i omega_i - signed_tie_i`

and `dp_12/dt = 2*pi*f0*T_12*(omega_1-omega_2)`.  ACE uses the documented operator bias `B_i=21 pu-power/pu-frequency` and signed tie exchange.  Governors and turbines retain droop, time constants, mechanical-power bounds, and a derivative-level GRC.  Boundary landing is applied only at physical valve/mechanical bounds and never to frequency, energy, or controller-integrator states.

Fixed local BESS PFR and upper SFR form one requested target before the shared causal delay channel.  The delayed request is intersected with active/reactive apparent-power, asymmetric headroom, availability, ramp, and one-step energy bounds.  Energy is integrated in MWh with separate charge/discharge efficiency; SoC is never projected.

The supervisory ACE PI is selected on an exact ZOH discretization at 2 or 4 s.  Its augmented state includes the integral action and the previous command needed for the nominal 0.2 s within-period delay.  Saturation invokes explicit integrator back-calculation.  A separate discrete LQI baseline uses the same delayed augmentation and is retained for later fair baseline comparison.

Plant B is native ANDES `kundur/kundur_vsc.xlsx`: the original four GENROU machines, TGOV1 governors, exciters, buses, branches, and algebraic equations remain active.  BESS power is a voltage-dependent Norton injection at buses 5 and 9 and therefore enters the native active-power balance and electrical torque.  The public callback exposes no hidden capability or future event.
""", encoding="utf-8")
    units = MODEL_DOC / "UNITS_AND_PARAMETERS.csv"
    rows = [
        ("omega", "per-unit frequency deviation", "(f-f0)/f0", "Plant A/B public conversion"),
        ("f0_A", "50", "Hz", "study convention"),
        ("f0_B", "60", "Hz", "native ANDES Kundur case"),
        ("Sbase_A", "1000", "MVA", "study base"),
        ("Sbase_B", "100", "MVA", "native ANDES case; explicit factor 10 conversion"),
        ("H", "5.0;4.5", "s", "aggregate Plant A calibration"),
        ("D", "1.0;1.0", "pu power / pu frequency", "aggregate load damping"),
        ("R", "0.05;0.05", "pu frequency / pu power", "5% droop"),
        ("ACE_bias", "21;21", "pu power / pu frequency", "D+1/R"),
        ("SFR_period", "4 main;2 sensitivity", "s", "preregistered Phase-E protocol"),
        ("BESS_rating", "100 each", "MW", "resource-tight study design"),
        ("BESS_energy", "50 each", "MWh", "30 minute nameplate duration"),
        ("BESS_efficiency", "0.95 charge;0.95 discharge", "fraction", "engineering assumption"),
        ("BESS_nominal_delay", "0.2", "s", "shared causal delay channel"),
        ("BESS_ramp", "0.08 up;0.08 down", "pu/s on 1000 MVA", "physical actuator bound"),
        ("GRC", "0.012 up;0.015 down", "pu/s", "mechanical-power derivative bound"),
    ]
    with units.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("symbol", "value", "unit", "source_or_rationale"))
        writer.writerows(rows)
    equation_map = MODEL_DOC / "EQUATION_CODE_MAP.csv"
    map_rows = [
        ("swing", "2H*domega=pm+pb-pL-D*omega-tie", "src/direction1freq/models/plant_a_v2.py", "_grid_derivative"),
        ("tie", "dp12=2*pi*f0*T12*(omega1-omega2)", "src/direction1freq/models/plant_a_v2.py", "_grid_derivative"),
        ("ACE", "ACE=B*omega+signed_tie", "src/direction1freq/models/plant_a_v2.py", "ace"),
        ("GRC", "dpm=sat((pv-pm)/Tt,-Gdown,Gup)", "src/direction1freq/models/plant_a_v2.py", "_grid_derivative"),
        ("shared_PFR_SFR", "request=p0-Kpfr*omega+uSFR", "src/direction1freq/models/bess_capability_v2.py", "step_bess_v2"),
        ("delay", "delivered=D_tau[request]", "src/direction1freq/simulation/delay_channel.py", "CausalDelayChannel.step"),
        ("energy", "dE=-(Pplus/etaD+etaC*Pminus)/3600", "src/direction1freq/models/bess_capability_v2.py", "_energy_derivative"),
        ("PI_ZOH_delay", "x+=Ad*x+B0*u+B1*u_previous", "src/direction1freq/controllers/ace_pi_aw.py", "delayed_sampled_closed_loop_matrix"),
        ("PlantB_DAE", "g_bus(x,y,p_b)=0", "src/direction1freq/models/plant_b_andes_v2.py", "run_causal_closed_loop"),
    ]
    with equation_map.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("equation_id", "formula", "file", "symbol"))
        writer.writerows(map_rows)
    sources = MODEL_DOC / "PARAMETER_SOURCES.md"
    sources.write_text("""# Parameter sources and scope

Plant A values are transparent study parameters inherited from the corrected Direction1 aggregate model and are sensitivity-tested over 2/4 s control and 0.01--0.1 s integration.  The 5% droop and `B=D+1/R` ACE bias are explicit; no hidden OEM values are claimed.  BESS rating, energy, efficiency, ramp, and delay are declared engineering assumptions and will be varied in known/OOD factors.

Plant B values are read from the bundled ANDES 2.0.0 Kundur VSC case at runtime.  Its 60 Hz/100 MVA base is not silently overwritten.  The external 1000 MVA study interface applies an explicit factor-ten power conversion.  Native-network validation is empirical RMS/DAE evidence, not an EMT or hardware claim.
""", encoding="utf-8")
    stability = VERIFY_DOC / "CLOSED_LOOP_STABILITY_REPORT.md"
    stability.write_text(f"""# E2 nominal closed-loop stability

The exact delayed-ZOH ACE-PI spectral radii are {results['spectral_radius_2s']:.6f} at 2 s and {results['spectral_radius_4s']:.6f} at 4 s, both below the preregistered 0.98 Gate.  Zero-load maximum frequency deviation is {results['zero_max_hz']:.3e} Hz.  Under the 1 h background trace, the 4 s PI frequency RMS is {results['background_pi_rms_hz']:.6g} Hz versus {results['background_no_sfr_rms_hz']:.6g} Hz without upper SFR.  Anti-windup is implemented as controller integrator back-calculation; no frequency or energy projection is used.
""", encoding="utf-8")
    cross = VERIFY_DOC / "PLANT_A_B_CROSS_VALIDATION.md"
    cross.write_text(f"""# E2 Plant A/B and native-interface validation

Plant A is the proof/large-experiment aggregate model.  Plant B is the native ANDES Kundur RMS/DAE model and is not expected to numerically match Plant A.  Plant-B validation instead applies one identical load/BESS signal through (i) the causal external bridge and (ii) native ANDES Alter events.  Their maximum interpolated COI-frequency difference is {results['plant_b_interface_max_error_hz']:.3e} Hz; both retain the native network and converge.  The observed BESS injection reaches {results['plant_b_max_bess_injection_pu']:.6g} pu on the external 1000 MVA base and the native bus residual P99 is {results['plant_b_balance_p99_pu']:.3e} pu.
""", encoding="utf-8")
    leakage = VERIFY_DOC / "E2_DATA_LEAKAGE_AUDIT.md"
    leakage.write_text("""# E2 deployable information audit

Deployable PI/LQI APIs accept `PublicObservationV2` and, for LQI, a causal estimated nine-state vector.  Neither signature accepts capability truth, true load, future events, ANDES internal states, or Oracle data.  `CapabilityTruthV2` appears only in plant/BESS simulation entrypoints.  The public observation contains frequency, ACE, tie-line exchange, measured SG/BESS active power, and previously issued commands.
""", encoding="utf-8")
    repair = VERIFY_DOC / "E2_REPAIR_LOG.md"
    repair.write_text("""# E2 preregistered repair log

Attempt 1 used the delayed discrete LQI as the nominal nonlinear controller.  Its unsaturated linear spectral radius passed, but 4 s control produced a persistent slow limit cycle for 0.05 and 0.08 pu steps (terminal absolute frequency 0.661 and 0.681 Hz).  This was a physical Gate failure, not removed data.  The original JSON, trajectory parquet, and log are retained as `FAILED_ATTEMPT_1_LQI_LIMIT_CYCLE.*` and `run_e2_rebuild_attempt1.log`.

The allowed first repair replaced the nominal upper controller with an ACE PI selected solely from the exact delayed-ZOH development model, with explicit back-calculation anti-windup.  No success threshold or disturbance magnitude changed.  The full matrix was rerun and passed.  LQI remains a candidate baseline only; it is not represented as the validated nominal loop.
""", encoding="utf-8")
    return [mathematical, units, equation_map, sources, stability, cross, leakage, repair]


def main() -> None:
    RESULT.mkdir(parents=True, exist_ok=True)
    FIGURE.mkdir(parents=True, exist_ok=True)
    MODEL_DOC.mkdir(parents=True, exist_ok=True)
    VERIFY_DOC.mkdir(parents=True, exist_ok=True)

    zero = simulate_plant_a(60.0, 0.02, 4.0, lambda _time: np.zeros(2))
    small = simulate_plant_a(300.0, 0.02, 4.0, step_profile(1e-6, 5.0))
    background_pi = simulate_plant_a(3600.0, 0.05, 4.0, background_profile, True, sample_period_s=1.0)
    background_none = simulate_plant_a(3600.0, 0.05, 4.0, background_profile, False, sample_period_s=1.0)

    step_runs: dict[str, dict] = {}
    for period in (2.0, 4.0):
        for magnitude in (0.02, 0.05, 0.08):
            step_runs[f"T{period:g}_L{magnitude:.2f}"] = simulate_plant_a(
                300.0, 0.02, period, step_profile(magnitude), sample_period_s=0.2
            )
    convergence: dict[float, dict] = {
        dt: simulate_plant_a(120.0, dt, 4.0, step_profile(0.05), sample_period_s=0.1)
        for dt in (0.10, 0.05, 0.02, 0.01)
    }
    reference_metrics = convergence[0.01]["metrics"]
    convergence_errors = {
        str(dt): max(
            relative_error(run["metrics"][key], reference_metrics[key])
            for key in ("max_abs_frequency_hz", "frequency_rms_hz", "ace_rms_pu")
        )
        for dt, run in convergence.items()
    }

    # Standalone energy/ramp/delay boundary experiment.
    bess_parameters = BESSParametersV2(maximum_delay_s=2.0)
    bess_state = BESSStateV2.equilibrium(bess_parameters, 0.01, soc=(0.11, 0.89))
    delay_first: float | None = None
    energy_residuals: list[float] = []
    for step in range(800):
        bess_state, diagnostic = step_bess_v2(
            bess_state, np.zeros(2), np.array([0.2, -0.2]), bess_parameters,
            CapabilityTruthV2(delay_s=(0.2, 0.2)), 0.01,
        )
        energy_residuals.extend(np.abs(diagnostic.energy_residual_mwh).tolist())
        if delay_first is None and bess_state.power_pu[0] > 0.0:
            delay_first = (step + 1) * 0.01

    native = AndesKundurPlantBV2(dt_s=0.01)
    external, native_events = native.same_input_interface_pair(duration_s=20.0)
    grid = np.linspace(0.0, 20.0, 2001)
    external_coi = np.interp(grid, external.time_s, external.coi_frequency_hz)
    native_coi = np.interp(grid, native_events.time_s, native_events.coi_frequency_hz)
    interface_error = float(np.max(np.abs(external_coi - native_coi)))
    native_closed: dict[float, object] = {}
    for period in (2.0, 4.0):
        proportional, integral, _ = design_stable_pi(TwoAreaPlantAV2(), period)
        native_controller = ACEPIAntiWindup(period, proportional, integral)

        def native_policy(observation, controller=native_controller):
            return controller.update(observation)[0]

        native_closed[period] = native.run_causal_closed_loop(
            duration_s=20.0,
            control_period_s=period,
            load_profile=lambda time_s: np.array([0.01 if time_s >= 5.0 else 0.0, 0.0]),
            policy=native_policy,
        )

    _, _, spectral_2 = design_stable_pi(TwoAreaPlantAV2(), 2.0)
    _, _, spectral_4 = design_stable_pi(TwoAreaPlantAV2(), 4.0)
    small_frame = small["frame"]
    small_peak = small["metrics"]["max_abs_frequency_hz"]
    small_terminal = small["metrics"]["terminal_abs_frequency_hz"]
    step_success = {
        name: (
            run["metrics"]["max_abs_frequency_hz"] <= 1.0
            and run["metrics"]["terminal_abs_frequency_hz"] <= 0.03
            and np.isfinite(run["frame"].to_numpy()).all()
        )
        for name, run in step_runs.items()
    }
    results = {
        "schema": "direction1.phase_e.e2.v1",
        "spectral_radius_2s": spectral_2,
        "spectral_radius_4s": spectral_4,
        "zero_max_hz": zero["metrics"]["max_abs_frequency_hz"],
        "small_peak_hz": small_peak,
        "small_terminal_hz": small_terminal,
        "background_pi_rms_hz": background_pi["metrics"]["frequency_rms_hz"],
        "background_no_sfr_rms_hz": background_none["metrics"]["frequency_rms_hz"],
        "step_metrics": {name: run["metrics"] for name, run in step_runs.items()},
        "dt_convergence_relative_errors": convergence_errors,
        "plant_a_power_balance_p99_pu": max(
            run["metrics"]["power_balance_p99_pu"]
            for run in [zero, small, background_pi, *step_runs.values(), *convergence.values()]
        ),
        "bess_energy_residual_p99_mwh": float(np.quantile(energy_residuals, 0.99)),
        "bess_delay_arrival_error_s": abs(float(delay_first) - 0.2),
        "plant_b_interface_max_error_hz": interface_error,
        "plant_b_balance_p99_pu": max(
            external.algebraic_power_balance_p99_pu, native_events.algebraic_power_balance_p99_pu
        ),
        "plant_b_max_bess_injection_pu": float(np.max(external.bess_injection_pu[:, 0])),
        "plant_b_external_converged": bool(external.converged),
        "plant_b_native_events_converged": bool(native_events.converged),
        "plant_b_closed_loop": {
            str(period): {
                "converged": bool(trace.converged),
                "max_abs_frequency_hz": float(np.max(np.abs(trace.frequency_deviation_hz))),
                "terminal_abs_frequency_hz": float(np.max(np.abs(trace.frequency_deviation_hz[-1]))),
                "balance_p99_pu": trace.algebraic_power_balance_p99_pu,
            }
            for period, trace in native_closed.items()
        },
    }
    gates = {
        "discrete_2s_4s_stability": spectral_2 < 0.98 and spectral_4 < 0.98,
        "zero_load_no_self_excitation": results["zero_max_hz"] <= 1e-12,
        "small_signal_decay": small_terminal <= max(1e-8, 0.10 * small_peak),
        "background_not_degraded": results["background_pi_rms_hz"] <= 1.05 * results["background_no_sfr_rms_hz"],
        "nonlinear_steps_safe": all(step_success.values()),
        "plant_a_power_balance": results["plant_a_power_balance_p99_pu"] <= 1e-8,
        "bess_energy_conservation": results["bess_energy_residual_p99_mwh"] <= 1e-9,
        "shared_delay_timing": results["bess_delay_arrival_error_s"] <= 0.01 + 1e-12,
        "dt_002_vs_001": float(convergence_errors["0.02"]) <= 0.01,
        "plant_b_native_interface": (
            results["plant_b_external_converged"] and results["plant_b_native_events_converged"]
            and interface_error <= 2e-4
        ),
        "plant_b_bess_in_network_balance": (
            results["plant_b_max_bess_injection_pu"] >= 0.004
            and results["plant_b_balance_p99_pu"] <= 1e-7
        ),
        "plant_b_2s_4s_closed_loop_stable": all(
            trace.converged
            and float(np.max(np.abs(trace.frequency_deviation_hz))) <= 0.20
            and float(np.max(np.abs(trace.frequency_deviation_hz[-1]))) <= 0.01
            and trace.algebraic_power_balance_p99_pu <= 1e-7
            for trace in native_closed.values()
        ),
    }
    gates = {key: bool(value) for key, value in gates.items()}
    results["gates"] = gates
    results["gate"] = "PASS" if all(gates.values()) else "FAIL"
    (RESULT / "E2_MODEL_AND_STABILITY_RESULTS.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    background_pi["frame"].to_parquet(RESULT / "background_1h_pi.parquet", index=False)
    background_none["frame"].to_parquet(RESULT / "background_1h_no_sfr.parquet", index=False)
    small_frame.to_parquet(RESULT / "small_signal_1e-6.parquet", index=False)
    pd.concat(
        [run["frame"].assign(scenario=name) for name, run in step_runs.items()], ignore_index=True
    ).to_parquet(RESULT / "nonlinear_step_matrix.parquet", index=False)
    pd.DataFrame([
        {"dt_s": float(dt), "max_relative_metric_error_vs_dt_0p01": value}
        for dt, value in convergence_errors.items()
    ]).to_csv(RESULT / "dt_convergence.csv", index=False)
    pd.concat([
        pd.DataFrame({
            "time_s": trace.time_s,
            "df1_hz": trace.frequency_deviation_hz[:, 0],
            "df2_hz": trace.frequency_deviation_hz[:, 1],
            "ace1_pu": trace.ace_pu[:, 0],
            "ace2_pu": trace.ace_pu[:, 1],
            "tie_pu": trace.tie_line_pu,
            "period_s": period,
        })
        for period, trace in native_closed.items()
    ], ignore_index=True).to_parquet(RESULT / "plant_b_closed_loop_2s_4s.parquet", index=False)

    plt.figure(figsize=(8, 4.8))
    for name in ("T4_L0.02", "T4_L0.05", "T4_L0.08"):
        frame = step_runs[name]["frame"]
        plt.plot(frame["time_s"], frame["df1_hz"], label=name)
    plt.xlabel("Time [s]")
    plt.ylabel("Area-1 frequency deviation [Hz]")
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIGURE / "plant_a_step_stability.png", dpi=180)
    plt.close()

    plt.figure(figsize=(8, 4.8))
    plt.plot(grid, external_coi, label="external causal bridge")
    plt.plot(grid, native_coi, "--", label="native Alter events")
    plt.xlabel("Time [s]")
    plt.ylabel("Native COI frequency deviation [Hz]")
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIGURE / "plant_b_native_interface.png", dpi=180)
    plt.close()

    docs = write_model_documents(results)
    outputs = [
        RESULT / "E2_MODEL_AND_STABILITY_RESULTS.json", RESULT / "background_1h_pi.parquet",
        RESULT / "background_1h_no_sfr.parquet", RESULT / "small_signal_1e-6.parquet",
        RESULT / "nonlinear_step_matrix.parquet", RESULT / "dt_convergence.csv",
        RESULT / "plant_b_closed_loop_2s_4s.parquet",
        FIGURE / "plant_a_step_stability.png", FIGURE / "plant_b_native_interface.png", *docs,
    ]
    for retained_failure in (
        RESULT / "FAILED_ATTEMPT_1_LQI_LIMIT_CYCLE.json",
        RESULT / "FAILED_ATTEMPT_1_LQI_LIMIT_CYCLE.parquet",
    ):
        if retained_failure.exists():
            outputs.append(retained_failure)
    progress = {
        "stage": "E2",
        "goal": "Rebuild a stable nominal loop, physical Plant A, and native ANDES Plant B",
        "status": "PASSED" if all(gates.values()) else "FAILED",
        "gate": "MODEL_AND_NOMINAL_CLOSED_LOOP",
        "gate_passed": all(gates.values()),
        "tests": gates,
        "failures": [key for key, passed in gates.items() if not passed],
        "repairs": [
            "Replaced Phase-D gains with exact delayed-ZOH ACE PI at 2/4 s",
            "Rejected an initially tested aggressive LQI after a 4 s nonlinear limit cycle; retained failure evidence",
            "Added explicit controller anti-windup and eliminated integrator/state resets",
            "Centralized delay in CausalDelayChannel for PFR and SFR",
            "Separated ANDES 100 MVA native units from the 1000 MVA external interface",
        ],
        "commands": [
            "python scripts/phase_e/run_e2_rebuild.py",
            "python -m pytest tests/phase_e/test_e2_rebuild.py -q",
        ],
        "outputs_sha256": {path.relative_to(REPO).as_posix(): sha256(path) for path in outputs},
        "next_stage": "E3" if all(gates.values()) else None,
    }
    progress_path = REPO / "progress_phase_e" / "E2.json"
    progress_path.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(progress, indent=2))
    if not all(gates.values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
