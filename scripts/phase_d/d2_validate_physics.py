"""Validate corrected Plant A and native ANDES Kundur Plant B."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from direction1freq.models import (
    AndesKundurPlantB, BESSFleetState, BESSParameters, CapabilityRegime,
    NativeTrace, TwoAreaPlantA, step_bess_fleet,
)


REPO = Path(__file__).resolve().parents[2]
RESULT = REPO / "results_phase_d" / "D2"
REPORT = REPO / "research_outputs_phase_d"
FIGURE = REPO / "figures_phase_d" / "D2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def simulate_plant_a(dt_s: float, duration_s: float = 60.0, disturbed: bool = True) -> dict[str, np.ndarray | float]:
    plant = TwoAreaPlantA(dt_s=dt_s)
    state = plant.equilibrium()
    rows: list[list[float]] = []
    balance: list[float] = []
    energy: list[float] = []
    grc: list[float] = []
    steps = int(round(duration_s / dt_s))
    for index in range(steps + 1):
        time_s = index * dt_s
        rows.append([
            time_s, *(plant.params.nominal_frequency_hz * state.omega_pu), state.tie_pu,
            *state.mechanical_power_pu, *state.bess.power_pu, *state.bess.energy_mwh,
        ])
        if index == steps:
            break
        load = np.array([0.06 if disturbed and time_s >= 1.0 else 0.0, 0.0])
        command = np.zeros(4)
        if disturbed and 2.0 <= time_s < 12.0:
            command[1] = 0.04
        state, diagnostics = plant.step(state, command, load, CapabilityRegime())
        balance.append(float(np.max(np.abs(diagnostics.power_balance_residual_pu))))
        energy.append(float(np.max(np.abs(diagnostics.bess.energy_residual_mwh))))
        grc.append(float(np.max(np.abs(diagnostics.mechanical_rate_pu_per_s))))
    array = np.asarray(rows)
    coi = np.mean(array[:, 1:3], axis=1)
    return {
        "table": array, "coi": coi,
        "balance_p99": float(np.quantile(balance, 0.99)) if balance else 0.0,
        "energy_p99": float(np.quantile(energy, 0.99)) if energy else 0.0,
        "grc_max": max(grc, default=0.0),
    }


def metrics(time: np.ndarray, signal: np.ndarray, area_difference: np.ndarray | None = None) -> dict[str, float]:
    mask = time >= 1.0
    t = time[mask]; y = signal[mask]
    out = {
        "nadir_hz": float(np.min(y)), "peak_hz": float(np.max(y)),
        "iae_hz_s": float(np.trapezoid(np.abs(y), t)),
        "f_10s_hz": float(np.interp(10.0, time, signal)),
        "f_30s_hz": float(np.interp(30.0, time, signal)),
        "f_60s_hz": float(np.interp(60.0, time, signal)),
    }
    if area_difference is None:
        out.update({"mode_frequency_hz": 0.0, "mode_damping_ratio": 1.0})
        return out
    modal_mask = (time >= 1.0) & (time <= min(20.0, time[-1]))
    modal = area_difference[modal_mask]
    modal = modal - np.mean(modal)
    if len(modal) < 10 or np.std(modal) < 1e-10:
        out.update({"mode_frequency_hz": 0.0, "mode_damping_ratio": 1.0})
        return out
    design = np.column_stack((modal[1:-1], modal[:-2]))
    coeff, *_ = np.linalg.lstsq(design, modal[2:], rcond=None)
    roots = np.roots([1.0, -coeff[0], -coeff[1]])
    root = roots[int(np.argmax(np.abs(np.imag(roots))))]
    sample = float(np.median(np.diff(time[modal_mask])))
    angle = abs(float(np.angle(root))); decay = -float(np.log(max(abs(root), 1e-12)))
    out["mode_frequency_hz"] = angle / (2.0 * np.pi * sample)
    out["mode_damping_ratio"] = decay / np.sqrt(decay**2 + angle**2) if angle > 0 else 1.0
    return out


def trace_metrics(trace: NativeTrace, max_time: float | None = None) -> dict[str, float]:
    mask = np.ones(len(trace.time_s), dtype=bool) if max_time is None else trace.time_s <= max_time + 1e-9
    return metrics(trace.time_s[mask], trace.coi_frequency_hz[mask], trace.area_frequency_hz[mask, 0] - trace.area_frequency_hz[mask, 1])


def relative_error(left: float, right: float, floor: float = 1e-8) -> float:
    return abs(left - right) / max(abs(right), floor)


def write_parameter_sources() -> Path:
    path = REPORT / "model" / "PARAMETER_SOURCES.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("f0_A", "50", "Hz", "A", "launch benchmark", "03_CORRECTED_PLANT_MODELS.md", "European/Asian nominal-frequency study", "50-60"),
        ("Sbase_A", "1000", "MVA", "A", "study base", "config master", "transparent engineering base", "500-2000"),
        ("H1", "5.0", "s", "A", "benchmark", "config master", "aggregate SG area inertia", "3-7"),
        ("H2", "4.5", "s", "A", "benchmark", "config master", "asymmetric area inertia", "3-7"),
        ("D1", "1.0", "pu/pu", "A", "benchmark", "config master", "load damping", "0.5-2"),
        ("D2", "1.0", "pu/pu", "A", "benchmark", "config master", "load damping", "0.5-2"),
        ("R1", "0.05", "pu/pu", "A", "governor benchmark", "Kundur/AGC convention", "5 percent droop", "0.04-0.06"),
        ("R2", "0.05", "pu/pu", "A", "governor benchmark", "Kundur/AGC convention", "5 percent droop", "0.04-0.06"),
        ("T12", "0.07", "pu/rad", "A", "benchmark", "config master", "visible inter-area dynamics", "0.04-0.10"),
        ("Tg1", "0.20", "s", "A", "benchmark", "config master", "governor lag", "0.1-0.5"),
        ("Tg2", "0.25", "s", "A", "benchmark", "config master", "governor lag", "0.1-0.5"),
        ("Tt1", "0.50", "s", "A", "benchmark", "config master", "turbine lag", "0.3-1.0"),
        ("Tt2", "0.60", "s", "A", "benchmark", "config master", "turbine lag", "0.3-1.0"),
        ("GRC_up", "0.012", "pu/s", "A", "engineering assumption", "config master", "mechanical-layer ramp", "0.006-0.02"),
        ("GRC_down", "0.015", "pu/s", "A", "engineering assumption", "config master", "asymmetric mechanical ramp", "0.008-0.025"),
        ("BESS_rating", "100", "MW", "A/B", "study design", "config master", "resource-tight relative to 1 GW base", "50-150"),
        ("BESS_energy", "50", "MWh", "A/B", "study design", "config master", "30 minute duration at rating", "25-100"),
        ("SOC_min", "0.10", "fraction", "A/B", "device assumption", "config master", "reserve boundary", "0.05-0.20"),
        ("SOC_max", "0.90", "fraction", "A/B", "device assumption", "config master", "charge headroom", "0.80-0.95"),
        ("eta_charge", "0.95", "fraction", "A/B", "device assumption", "config master", "one-way efficiency", "0.93-0.97"),
        ("eta_discharge", "0.95", "fraction", "A/B", "device assumption", "config master", "one-way efficiency", "0.93-0.97"),
        ("BESS_tau", "0.15", "s", "A/B", "device assumption", "source code", "fast active-power actuator", "0.05-0.30"),
        ("BESS_ramp", "0.08", "pu/s", "A/B", "device assumption", "source code", "explicit ramp capability", "0.01-0.15"),
        ("BESS_PFR_gain", "2.5", "pu/pu", "A/B", "fixed controller design", "config master", "shared PFR/SFR capability", "1-5"),
        ("delay_candidates", "0,0.2,0.5,1,2", "s", "A/B", "preregistered uncertainty", "config master", "communication/actuator range", "listed"),
        ("PlantB_case", "kundur_vsc.xlsx", "file", "B", "native standard case", "ANDES 2.0.0 bundled case", "stable native Kundur VSC qualification", "fixed"),
        ("PlantB_f0", "60", "Hz", "B", "native case", "ANDES Bus/GENROU data", "case-native frequency", "fixed"),
        ("PlantB_bess_bus_A", "5", "bus", "B", "study interface", "source code", "area-1 network interface", "5-7"),
        ("PlantB_bess_bus_B", "9", "bus", "B", "study interface", "source code", "area-2 network interface", "8-10"),
        ("PlantB_machine_M", "117,117,111.15,111.15", "s on system conversion", "B", "native case", "ANDES GENROU data", "unmodified machine inertia", "fixed"),
        ("PlantB_network", "15 native branches", "count", "B", "native case", "ANDES Line data", "full native algebraic network retained", "fixed"),
        ("PlantB_governors", "4 TGOV1", "count", "B", "native case", "ANDES TGOV1 data", "native governor/turbine dynamics", "fixed"),
        ("PlantB_injection", "controlled negative shunt g", "Norton interface", "B", "external-user-model interface", "source code", "active injection enters Bus P DAE", "voltage-compensated later"),
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("parameter", "value_or_range", "unit", "plant", "source_type", "source", "rationale", "sensitivity_range")); writer.writerows(rows)
    return path


def write_formula_map() -> Path:
    path = REPORT / "model" / "FORMULA_CODE_MAP.csv"; path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("A-omega", "2H*omega_dot=pm+pb-pL-D*omega-s*tie", "src/direction1freq/models/plant_a.py", "_grid_derivative", "tests/phase_d/test_d2_physics.py"),
        ("A-tie", "tie_dot=2*pi*f0*T12*(omega1-omega2)", "src/direction1freq/models/plant_a.py", "_grid_derivative", "tests/phase_d/test_d2_physics.py"),
        ("A-ACE", "ACE=B*omega+signed_tie", "src/direction1freq/models/plant_a.py", "ace", "tests/phase_d/test_d2_physics.py"),
        ("SG-GRC", "pm_dot=sat((pv-pm)/Tt,-Gdown,Gup)", "src/direction1freq/models/plant_a.py", "_grid_derivative", "tests/phase_d/test_d2_physics.py"),
        ("BESS-share", "utot=-Kpfr*omega+uSFR in U(E,c)", "src/direction1freq/models/bess.py", "step_bess_fleet", "tests/phase_d/test_d2_physics.py"),
        ("BESS-delay", "ubar_k=u_tot,k-d", "src/direction1freq/models/bess.py", "step_bess_fleet", "tests/phase_d/test_d2_physics.py"),
        ("BESS-energy", "E+=-dt/3600*(Pplus/etaD+etaC*Pminus)", "src/direction1freq/models/bess.py", "_energy_derivative_mwh_s", "tests/phase_d/test_d2_physics.py"),
        ("B-network", "g_bus(x,y,p)=0", "src/direction1freq/models/plant_b_andes.py", "AndesKundurPlantB", "tests/phase_d/test_d2_physics.py"),
        ("B-injection", "P_b=-g_b*V_b^2", "src/direction1freq/models/plant_b_andes.py", "callback", "tests/phase_d/test_d2_physics.py"),
        ("B-swing", "M*omega_dot=tm-te-D*(omega-1)", "ANDES GENROU", "native DAE", "scripts/phase_d/d2_validate_physics.py"),
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n"); writer.writerow(("formula_id", "equation", "file", "symbol", "test")); writer.writerows(rows)
    return path


def main() -> None:
    RESULT.mkdir(parents=True, exist_ok=True); FIGURE.mkdir(parents=True, exist_ok=True)
    plant_a_runs = {dt: simulate_plant_a(dt) for dt in (0.005, 0.01, 0.02)}
    plant_a_long = simulate_plant_a(0.01, 300.0, disturbed=False)
    a_metrics = {dt: metrics(run["table"][:, 0], run["coi"]) for dt, run in plant_a_runs.items()}
    a_conv_005_01 = max(relative_error(a_metrics[0.005][key], a_metrics[0.01][key]) for key in ("nadir_hz", "iae_hz_s"))
    a_conv_020_01 = max(relative_error(a_metrics[0.02][key], a_metrics[0.01][key]) for key in ("nadir_hz", "iae_hz_s"))
    plant_a = TwoAreaPlantA(dt_s=1e-5); initial = plant_a.equilibrium(); next_state, _ = plant_a.step(initial, np.zeros(4), np.array([0.06, 0.0]))
    expected_rocof = plant_a.initial_rocof_hz_s(np.array([0.06, 0.0]))[0]
    numeric_rocof = plant_a.params.nominal_frequency_hz * (next_state.omega_pu[0] - initial.omega_pu[0]) / plant_a.dt_s
    rocof_error = relative_error(numeric_rocof, expected_rocof)

    params = BESSParameters(); state = BESSFleetState.equilibrium(params, 0.01); delay_first = None; energy_residuals = []
    for step in range(250):
        state, diagnostic = step_bess_fleet(state, np.zeros(2), np.array([0.2, 0.0]), params, CapabilityRegime(delay_s=(0.2, 0.2)), 0.01)
        energy_residuals.extend(np.abs(diagnostic.energy_residual_mwh).tolist())
        if delay_first is None and state.power_pu[0] > 0: delay_first = (step + 1) * 0.01

    native_external = AndesKundurPlantB(0.01).run_validation_profile(60.0, "external")
    native_events = AndesKundurPlantB(0.01).run_validation_profile(60.0, "native_events")
    native_005 = AndesKundurPlantB(0.005).run_validation_profile(20.0, "native_events")
    native_020 = AndesKundurPlantB(0.02).run_validation_profile(20.0, "native_events")
    native_long = AndesKundurPlantB(0.02).run_no_disturbance(300.0)
    b_ext_metrics = trace_metrics(native_external); b_evt_metrics = trace_metrics(native_events)
    b_005_metrics = trace_metrics(native_005, 20.0); b_010_20_metrics = trace_metrics(native_events, 20.0); b_020_metrics = trace_metrics(native_020, 20.0)
    cross = {key: relative_error(b_ext_metrics[key], b_evt_metrics[key], 1e-6) for key in ("nadir_hz", "iae_hz_s", "mode_frequency_hz", "mode_damping_ratio")}
    b_conv_005_01 = max(relative_error(b_005_metrics[key], b_010_20_metrics[key], 1e-6) for key in ("nadir_hz", "iae_hz_s"))
    b_conv_020_01 = max(relative_error(b_020_metrics[key], b_010_20_metrics[key], 1e-6) for key in ("nadir_hz", "iae_hz_s"))
    tail_mask = native_long.time_s >= 240.0
    tail_slope = float(np.polyfit(native_long.time_s[tail_mask], native_long.coi_frequency_hz[tail_mask], 1)[0])
    long_final = float(abs(native_long.coi_frequency_hz[-1]))

    checks = {
        "plant_a_initial_rocof_relative_error": rocof_error,
        "plant_a_power_balance_p99_pu": plant_a_runs[0.01]["balance_p99"],
        "bess_energy_residual_p99_mwh": float(np.quantile(energy_residuals, 0.99)),
        "delay_arrival_error_s": abs(float(delay_first) - 0.2),
        "plant_a_dt_005_vs_010": a_conv_005_01, "plant_a_dt_020_vs_010": a_conv_020_01,
        "plant_b_dt_005_vs_010": b_conv_005_01, "plant_b_dt_020_vs_010": b_conv_020_01,
        "plant_b_power_balance_p99_pu": max(native_external.algebraic_power_balance_p99_pu, native_events.algebraic_power_balance_p99_pu),
        "plant_b_long_tail_slope_hz_s": abs(tail_slope), "plant_b_long_final_hz": long_final,
        "cross_nadir_relative_error": cross["nadir_hz"], "cross_iae_relative_error": cross["iae_hz_s"],
        "cross_mode_frequency_relative_error": cross["mode_frequency_hz"], "cross_mode_damping_relative_error": cross["mode_damping_ratio"],
    }
    gates = {
        "initial_rocof": rocof_error <= 0.01,
        "power_balance": checks["plant_a_power_balance_p99_pu"] <= 1e-7 and checks["plant_b_power_balance_p99_pu"] <= 1e-7,
        "energy_balance": checks["bess_energy_residual_p99_mwh"] <= 1e-8,
        "delay": checks["delay_arrival_error_s"] <= 0.01 + 1e-12,
        "dt_convergence": a_conv_005_01 <= 0.01 and a_conv_020_01 <= 0.02 and b_conv_005_01 <= 0.01 and b_conv_020_01 <= 0.02,
        "native_cross_validation": cross["nadir_hz"] <= 0.10 and cross["iae_hz_s"] <= 0.10 and cross["mode_frequency_hz"] <= 0.10 and cross["mode_damping_ratio"] <= 0.20,
        "long_run_no_drift": abs(tail_slope) <= 1e-5 and long_final <= 1e-3 and float(np.max(np.abs(plant_a_long["coi"]))) <= 1e-12,
        "bess_native_injection": float(np.max(native_external.bess_injection_pu[:, 0])) >= 0.004,
    }
    gates = {key: bool(value) for key, value in gates.items()}
    passed = all(gates.values())

    columns = ["time_s", "df1_hz", "df2_hz", "tie_pu", "pm1_pu", "pm2_pu", "pb1_pu", "pb2_pu", "e1_mwh", "e2_mwh"]
    pd.DataFrame(plant_a_runs[0.01]["table"], columns=columns).to_parquet(RESULT / "plant_a_validation_trace.parquet", index=False)
    native_df = pd.DataFrame({
        "time_s": native_external.time_s, "df_area1_hz": native_external.area_frequency_hz[:, 0], "df_area2_hz": native_external.area_frequency_hz[:, 1],
        "df_coi_hz": native_external.coi_frequency_hz, "tie_pu": native_external.tie_line_pu,
        "pm_area1_pu": native_external.sg_mechanical_power_pu[:, 0], "pm_area2_pu": native_external.sg_mechanical_power_pu[:, 1],
        "pb_area1_pu": native_external.bess_injection_pu[:, 0], "pb_area2_pu": native_external.bess_injection_pu[:, 1],
    })
    native_df.to_parquet(RESULT / "plant_b_native_validation_trace.parquet", index=False)
    pd.DataFrame([{"check": key, "value": value} for key, value in checks.items()]).to_csv(RESULT / "physical_validation_checks.csv", index=False)
    result = {
        "schema": "direction1.phase_d.d2.v1", "gate": "PASS" if passed else "FAIL", "checks": checks, "gates": gates,
        "plant_b": {"engine": "ANDES", "version": "2.0.0", "case": AndesKundurPlantB.native_case, "native_buses": 10, "native_lines": 15, "native_generators": 4, "bess_buses": list(AndesKundurPlantB.bess_bus_ids), "interface": "causal external BESS actuator to native Norton injection", "separate_surrogate_used": False},
        "cross_metrics_external": b_ext_metrics, "cross_metrics_native_events": b_evt_metrics,
        "known_initialization_limitation": "Bundled Kundur VSC case has a sub-0.013 Hz initialization transient which decays; 240-300 s tail drift Gate is applied.",
    }
    (RESULT / "model_validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    plt.figure(figsize=(8, 5)); plt.plot(native_external.time_s, native_external.coi_frequency_hz, label="external causal bridge")
    plt.plot(native_events.time_s, native_events.coi_frequency_hz, "--", label="native Alter schedule", alpha=0.8)
    plt.xlabel("Time [s]"); plt.ylabel("COI frequency deviation [Hz]"); plt.legend(); plt.tight_layout(); plt.savefig(FIGURE / "native_cross_validation.png", dpi=180); plt.close()

    parameter_path = write_parameter_sources(); formula_path = write_formula_map()
    model_dir = REPORT / "model"; validation_dir = REPORT / "validation"; validation_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "FULL_MATHEMATICAL_MODEL.md").write_text("""# Direction1 corrected physical model

Plant A uses the exact per-unit/Hz convention `omega=(f-f0)/f0`, `df=f0*omega`, two area swing equations, signed tie-line exchange, common ACE, fixed droop/PFR, held upper SFR, and a governor/turbine whose derivative is saturated at the mechanical-power layer. BESS PFR and SFR enter one shared feasible set containing headroom, apparent-current, ramp, delay, availability and one-step energy constraints. Energy is integrated in MWh with charge/discharge efficiency and is never repaired by SoC projection.

Plant B is the native ANDES 2.0.0 `kundur_vsc.xlsx` case: 10 buses, 15 branches, four GENROU machines, native TGOV1 governors/exciters, and native algebraic network equations. The external physical BESS actuator is connected at buses 5 and 9 through a controllable Norton active injection `P_b=-g_b V_b^2`; its negative conductance is solved inside the bus active-power balance and therefore changes native generator electrical torque and swing dynamics. The independent direct-native Alter schedule and the causal external bridge receive the same load and BESS control signals.
""", encoding="utf-8")
    (model_dir / "ASSUMPTIONS_AND_LIMITATIONS.md").write_text("""# Model assumptions and limitations

- Plant A is an aggregate electromechanical benchmark; its proof scope does not extend to Plant B.
- Plant B is native phasor-domain RMS/DAE, not EMT. The bundled Kundur VSC case has a small initialization transient; the 300 s tail-slope/final-offset test distinguishes this from numerical drift.
- The BESS device dynamics, energy and hidden capability are external physical states coupled through a Norton injection. Reactive power is represented in the shared capability calculation but fixed during D2 validation.
- ANDES uses its native 60 Hz/100 MVA case base; the public study interface converts power to the 1000 MVA Direction1 base explicitly.
- The D2 cross-validation is an interface-equivalence qualification, not a claim that Plant A and Plant B trajectories should match.
""", encoding="utf-8")
    (validation_dir / "MODEL_VALIDATION_REPORT.md").write_text(f"""# D2 model validation report

Overall Gate: **{'PASS' if passed else 'FAIL'}**. Plant A initial RoCoF relative error is {rocof_error:.3e}; Plant A/Plant B power-balance P99 values are {checks['plant_a_power_balance_p99_pu']:.3e}/{checks['plant_b_power_balance_p99_pu']:.3e} pu. BESS energy residual P99 is {checks['bess_energy_residual_p99_mwh']:.3e} MWh and delay arrival error is {checks['delay_arrival_error_s']:.3e} s.

Native external-vs-event errors are nadir {cross['nadir_hz']:.2%}, IAE {cross['iae_hz_s']:.2%}, modal frequency {cross['mode_frequency_hz']:.2%}, and modal damping {cross['mode_damping_ratio']:.2%}. The native 240–300 s COI tail slope is {tail_slope:.3e} Hz/s and final absolute offset {long_final:.3e} Hz.
""", encoding="utf-8")
    (validation_dir / "CROSS_MODEL_COMPARISON.md").write_text("""# Cross-model and native-interface comparison

Plant A and Plant B share disturbance sign, public measurement contract, SG/BESS SFR ordering and engineering power conversion. They intentionally retain different frequency bases and physics. Plant B comparison is between (i) a causal external controller bridge and (ii) preregistered native ANDES Alter events, both applied to the same Kundur VSC network. This directly tests that the bridge injects BESS active power into the native bus equation rather than evolving a disconnected surrogate.
""", encoding="utf-8")
    (validation_dir / "DATA_LEAKAGE_AUDIT.md").write_text("""# D2 information-boundary audit

The plant simulator owns true load, capability, energy and native internal states. The future deployable controller interface is limited to measured frequency/ACE/tie-line, SG mechanical power, BESS POI power, issued commands and a shared causal estimator. Plant B's external bridge is simulator infrastructure; it does not expose ANDES GENROU states, future events, true load or BESS capability to deployable controllers.
""", encoding="utf-8")

    outputs = [RESULT / "model_validation.json", RESULT / "physical_validation_checks.csv", RESULT / "plant_a_validation_trace.parquet", RESULT / "plant_b_native_validation_trace.parquet", FIGURE / "native_cross_validation.png", parameter_path, formula_path, model_dir / "FULL_MATHEMATICAL_MODEL.md", model_dir / "ASSUMPTIONS_AND_LIMITATIONS.md", validation_dir / "MODEL_VALIDATION_REPORT.md", validation_dir / "CROSS_MODEL_COMPARISON.md", validation_dir / "DATA_LEAKAGE_AUDIT.md"]
    progress = {
        "stage": "D2", "goal": "Build and validate corrected Plant A and native networked Plant B", "status": "PASSED" if passed else "FAILED",
        "gate": "PHYSICAL_MODEL_VALIDITY", "gate_passed": passed, "inputs_sha256": {"master_config": sha256(REPO / "configs" / "phase_d" / "master.yaml")},
        "commands": ["python scripts/phase_d/d2_validate_physics.py", "python -m pytest tests/phase_d/test_d2_physics.py -q"],
        "tests": gates, "failures": [] if passed else [key for key, value in gates.items() if not value],
        "repairs": ["Rejected drifting kundur_full.xlsx", "Qualified native kundur_vsc.xlsx", "Replaced disconnected six-bus surrogate with native Norton-coupled ANDES bridge"],
        "outputs_sha256": {path.relative_to(REPO).as_posix(): sha256(path) for path in outputs}, "next_stage": "D3" if passed else None,
    }
    progress_path = REPO / "progress_phase_d" / "D2.json"; progress_path.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(progress, indent=2))
    if not passed: raise SystemExit(2)


if __name__ == "__main__":
    main()
