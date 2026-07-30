"""Preregistered causal passive-capability H2 experiment."""

from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor
import hashlib
import inspect
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from direction1freq.estimation import AugmentedLoadKalman
from direction1freq.identification import CausalCapabilitySetEstimator
from direction1freq.models import CapabilityRegime, TwoAreaPlantA


REPO = Path(__file__).resolve().parents[2]
RESULT = REPO / "results_phase_d" / "D3"
REPORT = REPO / "research_outputs_phase_d" / "identification"
FIGURE = REPO / "figures_phase_d" / "D3"
DT = 0.05
CHANGE_TIME = 45.0
DURATION = 120.0
CONTROL_PERIOD = 2.0


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    mechanism: str
    load_time_s: float | None
    noise_power_std: float
    jitter_probability: float = 0.0
    physical_change: bool = True


SCENARIOS = (
    Scenario("nominal_no_change", "nominal", 50.0, 0.0002, physical_change=False),
    Scenario("load_only", "nominal", 45.0, 0.0006, physical_change=False),
    Scenario("oem_label_only", "nominal", None, 0.0002, physical_change=False),
    Scenario("no_change_jitter", "nominal", 50.0, 0.0006, jitter_probability=0.015, physical_change=False),
    Scenario("headroom_after_load", "headroom", 50.0, 0.0002),
    Scenario("ramp_same_load", "ramp", 45.0, 0.0006),
    Scenario("delay_after_load", "delay", 50.0, 0.0010),
    Scenario("simultaneous_change", "simultaneous", 45.0, 0.0006),
    Scenario("headroom_no_excitation", "headroom", None, 0.0002),
    Scenario("headroom_load_before", "headroom", 35.0, 0.0006),
)

ESTIMATOR_CANDIDATES = (
    {"noise_bound_pu": 0.0015, "cusum_drift": 1.0, "cusum_threshold": 8.0},
    {"noise_bound_pu": 0.0020, "cusum_drift": 1.2, "cusum_threshold": 10.0},
    {"noise_bound_pu": 0.0025, "cusum_drift": 1.5, "cusum_threshold": 12.0},
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regime_at(time_s: float, scenario: Scenario) -> CapabilityRegime:
    if not scenario.physical_change or time_s < CHANGE_TIME:
        return CapabilityRegime()
    if scenario.mechanism == "headroom":
        return CapabilityRegime(headroom_fraction=(0.25, 1.0))
    if scenario.mechanism == "ramp":
        return CapabilityRegime(ramp_fraction=(0.10, 1.0))
    if scenario.mechanism == "delay":
        return CapabilityRegime(delay_s=(1.0, 0.2))
    if scenario.mechanism == "simultaneous":
        return CapabilityRegime(headroom_fraction=(0.30, 1.0), ramp_fraction=(0.15, 1.0), delay_s=(1.0, 0.2))
    return CapabilityRegime()


def true_capability(state, regime: CapabilityRegime) -> tuple[float, float, float, float]:
    power = 0.1 * regime.headroom_fraction[0] * regime.availability[0] * regime.service_fraction[0]
    ramp = 0.08 * regime.ramp_fraction[0] * regime.availability[0] * regime.service_fraction[0]
    return power, ramp, regime.delay_s[0], float(state.bess.energy_mwh[0])


def run_episode(seed: int, scenario: Scenario, estimator_parameters: dict[str, float], retain_trace: bool) -> tuple[dict[str, object], list[dict[str, object]]]:
    rng = np.random.default_rng(seed)
    plant = TwoAreaPlantA(dt_s=DT); state = plant.equilibrium(soc=(float(rng.uniform(0.4, 0.6)), 0.5))
    capability = CausalCapabilitySetEstimator(dt_s=DT, **estimator_parameters)
    load_filter = AugmentedLoadKalman(dt_s=DT, measurement_std=(3e-5, 3e-5, 3e-4))
    command = np.zeros(4); integral = np.zeros(2); last_measured_power = 0.0
    update_time = float("inf"); control_loss_time = float("inf"); deficit_area = 0.0
    alarm_times: list[float] = []; coverage: list[bool] = []; power_coverage: list[bool] = []
    ramp_coverage: list[bool] = []; delay_coverage: list[bool] = []; energy_coverage: list[bool] = []
    load_errors: list[float] = []; traces: list[dict[str, object]] = []
    load_size = float(rng.uniform(0.045, 0.060)); phases = rng.uniform(0, 2 * np.pi, size=2)
    next_control = 0.0
    for step in range(int(round(DURATION / DT))):
        time_s = step * DT
        background = 0.0015 * np.array([np.sin(2 * np.pi * time_s / 27 + phases[0]), np.sin(2 * np.pi * time_s / 31 + phases[1])])
        event = np.array([load_size if scenario.load_time_s is not None and time_s >= scenario.load_time_s else 0.0, 0.0])
        load = background + event
        if time_s + 1e-12 >= next_control:
            measured_ace = plant.ace(state) + rng.normal(0.0, 2e-4, size=2)
            integral = np.clip(integral + CONTROL_PERIOD * measured_ace, -0.12, 0.12)
            request = np.clip(-1.4 * measured_ace - 0.18 * integral, -0.10, 0.10)
            command = np.array([0.35 * request[0], 0.65 * request[0], 0.35 * request[1], 0.65 * request[1]])
            next_control += CONTROL_PERIOD
        active_regime = regime_at(time_s, scenario)
        issued_total = float(-plant.params.bess.pfr_gain_pu_power_per_pu_frequency * state.omega_pu[0] + command[1])
        next_state, _ = plant.step(state, command, load, active_regime)
        observation = plant.observation(next_state, command)
        measured_frequency = observation[:2] + rng.normal(0.0, 0.0015, size=2)
        measured_tie = float(observation[4] + rng.normal(0.0, 1e-4))
        measured_pm = observation[5:7] + rng.normal(0.0, 2e-4, size=2)
        measured_pb = observation[7:9] + rng.normal(0.0, scenario.noise_power_std, size=2)
        if rng.random() < scenario.jitter_probability:
            measured_pb[0] = last_measured_power
        last_measured_power = float(measured_pb[0])
        load_estimate = load_filter.update(measured_frequency, measured_tie, np.array([measured_pm[0], measured_pb[0], measured_pm[1], measured_pb[1]]))
        estimate = capability.update(issued_total, measured_pb[0])
        if estimate.alarm:
            alarm_times.append(time_s)
            if time_s >= CHANGE_TIME and not np.isfinite(update_time):
                update_time = time_s
        truth_power, truth_ramp, truth_delay, truth_energy = true_capability(next_state, active_regime)
        power_ok = estimate.power_magnitude_interval_pu[0] - 1e-12 <= truth_power <= estimate.power_magnitude_interval_pu[1] + 1e-12
        ramp_ok = estimate.ramp_interval_pu_per_s[0] - 1e-12 <= truth_ramp <= estimate.ramp_interval_pu_per_s[1] + 1e-12
        delay_ok = any(abs(candidate - truth_delay) <= DT / 2 for candidate in estimate.delay_candidates_s)
        energy_ok = estimate.energy_interval_mwh[0] - 1e-9 <= truth_energy <= estimate.energy_interval_mwh[1] + 1e-9
        power_coverage.append(power_ok); ramp_coverage.append(ramp_ok); delay_coverage.append(delay_ok); energy_coverage.append(energy_ok)
        coverage.append(power_ok and ramp_ok and delay_ok and energy_ok)
        if time_s >= 5.0:
            load_errors.append(float(load_estimate.load_pu[0] - load[0]))
        if scenario.physical_change and time_s >= CHANGE_TIME:
            deficit_area += max(abs(issued_total) - abs(next_state.bess.power_pu[0]) - 0.004, 0.0) * DT
            if not np.isfinite(control_loss_time) and deficit_area >= 0.015:
                control_loss_time = time_s
        if retain_trace:
            traces.append({
                "seed": seed, "scenario": scenario.name, "time_s": time_s, "issued_total_pu": issued_total,
                "measured_power_pu": float(measured_pb[0]), "true_power_capability_pu": truth_power,
                "estimated_power_lower_pu": estimate.power_magnitude_interval_pu[0], "estimated_power_upper_pu": estimate.power_magnitude_interval_pu[1],
                "true_ramp_pu_s": truth_ramp, "estimated_ramp_lower_pu_s": estimate.ramp_interval_pu_per_s[0],
                "true_delay_s": truth_delay, "delay_candidate_count": len(estimate.delay_candidates_s),
                "true_energy_mwh": truth_energy, "energy_lower_mwh": estimate.energy_interval_mwh[0], "energy_upper_mwh": estimate.energy_interval_mwh[1],
                "alarm": estimate.alarm, "joint_covered": coverage[-1], "load_true_pu": float(load[0]), "load_estimate_pu": float(load_estimate.load_pu[0]),
            })
        state = next_state
    prechange_alarm = any(value < CHANGE_TIME for value in alarm_times)
    no_change = not scenario.physical_change
    finite_loss = np.isfinite(control_loss_time)
    evaluated_timing = scenario.mechanism in {"headroom", "ramp", "delay"} and scenario.load_time_s is not None and scenario.load_time_s >= CHANGE_TIME
    row: dict[str, object] = {
        "seed": seed, "scenario": scenario.name, "mechanism": scenario.mechanism,
        "physical_change": scenario.physical_change, "load_time_s": scenario.load_time_s,
        "noise_power_std": scenario.noise_power_std, "jitter_probability": scenario.jitter_probability,
        "joint_coverage": float(np.mean(coverage)), "power_coverage": float(np.mean(power_coverage)),
        "ramp_coverage": float(np.mean(ramp_coverage)), "delay_coverage": float(np.mean(delay_coverage)), "energy_coverage": float(np.mean(energy_coverage)),
        "any_alarm": bool(alarm_times), "prechange_alarm": prechange_alarm,
        "false_alarm": bool(no_change and alarm_times), "update_time_s": update_time,
        "control_loss_time_s": control_loss_time, "timing_evaluated": evaluated_timing and finite_loss,
        "update_before_control_loss": bool(evaluated_timing and finite_loss and update_time < control_loss_time),
        "load_rmse_pu": float(np.sqrt(np.mean(np.square(load_errors)))),
        "alarm_count": len(alarm_times),
    }
    return row, traces


def run_split(seeds: range, parameters: dict[str, float], retain_representatives: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []; traces: list[dict[str, object]] = []
    tasks: list[tuple[int, Scenario, dict[str, float], bool]] = []
    for scenario in SCENARIOS:
        for index, seed in enumerate(seeds):
            tasks.append((seed, scenario, parameters, retain_representatives and index == 0))
    with ProcessPoolExecutor(max_workers=4) as pool:
        for row, episode_trace in pool.map(_run_episode_task, tasks, chunksize=1):
            rows.append(row); traces.extend(episode_trace)
    return pd.DataFrame(rows), pd.DataFrame(traces)


def _run_episode_task(task: tuple[int, Scenario, dict[str, float], bool]) -> tuple[dict[str, object], list[dict[str, object]]]:
    return run_episode(*task)


def summarize(frame: pd.DataFrame) -> dict[str, object]:
    no_change = frame[~frame.physical_change]
    core = frame[(frame.mechanism.isin(["headroom", "ramp", "delay"])) & frame.timing_evaluated]
    mechanisms = {name: float(group.update_before_control_loss.mean()) for name, group in core.groupby("mechanism")}
    summary: dict[str, object] = {
        "joint_coverage": float(frame.joint_coverage.mean()),
        "power_coverage": float(frame.power_coverage.mean()), "ramp_coverage": float(frame.ramp_coverage.mean()),
        "delay_coverage": float(frame.delay_coverage.mean()), "energy_coverage": float(frame.energy_coverage.mean()),
        "false_alarm_rate": float(no_change.false_alarm.mean()), "prechange_alarm_rate": float(frame.prechange_alarm.mean()),
        "mechanism_update_before_loss": mechanisms,
        "mechanisms_passing": sum(value >= 0.8 for value in mechanisms.values()),
        "load_rmse_pu": float(np.sqrt(np.mean(np.square(frame.load_rmse_pu)))),
        "timing_evaluated_episodes": int(frame.timing_evaluated.sum()),
        "not_evaluated_timing_episodes": int((~frame.timing_evaluated).sum()),
    }
    summary["h2_passed"] = bool(
        summary["joint_coverage"] >= 0.95 and summary["false_alarm_rate"] <= 0.05
        and summary["prechange_alarm_rate"] == 0.0 and summary["mechanisms_passing"] >= 2
        and summary["load_rmse_pu"] <= 0.02
    )
    return summary


def main() -> None:
    RESULT.mkdir(parents=True, exist_ok=True); REPORT.mkdir(parents=True, exist_ok=True); FIGURE.mkdir(parents=True, exist_ok=True)
    repair_records: list[dict[str, object]] = []; selected = None; development = None
    for round_index, candidate in enumerate(ESTIMATOR_CANDIDATES):
        candidate_frame, _ = run_split(range(0, 12), candidate, False)
        candidate_summary = summarize(candidate_frame)
        repair_records.append({"round": round_index, "parameters": candidate, "development": candidate_summary})
        candidate_frame.to_parquet(RESULT / f"development_round_{round_index}.parquet", index=False)
        if candidate_summary["h2_passed"]:
            selected = candidate; development = candidate_frame; break
        if round_index >= 2: break
    if selected is None:
        selected = ESTIMATOR_CANDIDATES[min(2, len(repair_records) - 1)]
        development = pd.read_parquet(RESULT / f"development_round_{len(repair_records)-1}.parquet")
    validation, representative = run_split(range(100, 112), selected, True)
    validation_summary = summarize(validation); development_summary = summarize(development)
    # A validation-only repair is allowed by the protocol, but never uses final seeds.
    if not validation_summary["h2_passed"] and selected != ESTIMATOR_CANDIDATES[-1] and len(repair_records) < 3:
        next_index = ESTIMATOR_CANDIDATES.index(selected) + 1; selected = ESTIMATOR_CANDIDATES[next_index]
        validation, representative = run_split(range(100, 112), selected, True)
        validation_summary = summarize(validation)
        repair_records.append({"round": next_index, "parameters": selected, "validation": validation_summary})

    validation.to_parquet(RESULT / "validation_episode_summary.parquet", index=False)
    representative.to_parquet(RESULT / "representative_causal_traces.parquet", index=False)
    pd.DataFrame([{"split": "development", **{k: v for k, v in development_summary.items() if not isinstance(v, dict)}}, {"split": "validation", **{k: v for k, v in validation_summary.items() if not isinstance(v, dict)}}]).to_csv(RESULT / "capability_coverage_summary.csv", index=False)
    pd.DataFrame([{"mechanism": key, "probability": value} for key, value in validation_summary["mechanism_update_before_loss"].items()]).to_csv(RESULT / "update_before_loss.csv", index=False)
    pd.DataFrame([
        {"case": "headroom_no_excitation", "identifiable": False, "reason": "no natural command reaches changed boundary", "disposition": "structurally_not_evaluated_not_failure"},
        {"case": "simultaneous_change", "identifiable": "set_expansion_only", "reason": "multiple mechanisms share compatible external trajectories", "disposition": "source label not claimed"},
        {"case": "oem_label_only", "identifiable": False, "reason": "no external feasible-set or optimal-action change", "disposition": "negative control"},
    ]).to_csv(RESULT / "structural_nonidentifiability.csv", index=False)
    final = {
        "schema": "direction1.phase_d.d3.h2.v1", "gate": "PASS" if validation_summary["h2_passed"] else "FAIL",
        "selected_estimator_parameters": selected, "development_summary": development_summary,
        "validation_summary": validation_summary, "repair_rounds": repair_records,
        "final_seeds_used": False, "true_source_labels_used_by_estimator": False,
        "centered_convolution_used": False, "post_alarm_future_window_used": False,
        "decision_if_failed": "PASSIVE_CAPABILITY_SET_NOT_SUPPORTED",
    }
    (RESULT / "h2_gate.json").write_text(json.dumps(final, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")

    plt.figure(figsize=(8, 4)); keys = ["power_coverage", "ramp_coverage", "delay_coverage", "energy_coverage", "joint_coverage"]
    plt.bar(keys, [validation_summary[key] for key in keys]); plt.axhline(0.95, color="k", linestyle="--"); plt.ylim(0.85, 1.005); plt.xticks(rotation=20); plt.tight_layout(); plt.savefig(FIGURE / "capability_coverage.png", dpi=180); plt.close()
    timing = pd.read_csv(RESULT / "update_before_loss.csv"); plt.figure(figsize=(6, 4)); plt.bar(timing.mechanism, timing.probability); plt.axhline(0.8, color="k", linestyle="--"); plt.ylim(0, 1.02); plt.ylabel("P(update before control loss)"); plt.tight_layout(); plt.savefig(FIGURE / "causal_update_timing.png", dpi=180); plt.close()

    REPORT.joinpath("CAPABILITY_SET_MODEL.md").write_text("""# Causal control-relevant capability-set model

The deployable estimator accepts only the issued total BESS command and measured POI active power. A delayed one-step actuator model is evaluated over the registered delay candidates. Achieved command/output pairs raise guaranteed lower power/ramp capability; registered physical ratings remain upper bounds. Energy starts from an operator-declared interval and is propagated with measured POI power and efficiency bounds. A one-sided recursion `g_k=max(0,g_{k-1}+|e_k|/epsilon-nu)` uses only sample `k` and prior state. An alarm expands the set to the global physical set; it never selects an OEM/source label.

The paired augmented Kalman filter estimates unknown area loads from measured frequency, tie-line, SG mechanical power and BESS POI power. True load is accepted only by the evaluation scorer.
""", encoding="utf-8")
    REPORT.joinpath("CAUSALITY_AUDIT.md").write_text(f"""# D3 causality audit

- `CausalCapabilitySetEstimator.update` parameters: `{', '.join(inspect.signature(CausalCapabilitySetEstimator.update).parameters)}`.
- No centered convolution or symmetric filter exists.
- Every update is called after the current measurement and before any later sample is generated.
- Alarm handling uses no post-alarm window and emits no source label.
- Development seeds 0–11 and validation seeds 100–111 were used; no final seed was used.
- Timing not evaluated due to absent excitation is stored separately and is not counted as method failure.
""", encoding="utf-8")
    REPORT.joinpath("H2_GATE_REPORT.md").write_text(f"""# H2 passive capability-set Gate

Validation joint coverage is {validation_summary['joint_coverage']:.3f}; power/ramp/delay/energy coverages are {validation_summary['power_coverage']:.3f}/{validation_summary['ramp_coverage']:.3f}/{validation_summary['delay_coverage']:.3f}/{validation_summary['energy_coverage']:.3f}. The no-change false-alarm rate is {validation_summary['false_alarm_rate']:.3f}, and no pre-change alarm rate is {validation_summary['prechange_alarm_rate']:.3f}. Per-mechanism probabilities are `{validation_summary['mechanism_update_before_loss']}`; {validation_summary['mechanisms_passing']} mechanisms pass 0.8. Load-estimator RMSE is {validation_summary['load_rmse_pu']:.4f} pu.

Decision: **{'H2 PASS' if validation_summary['h2_passed'] else 'PASSIVE_CAPABILITY_SET_NOT_SUPPORTED'}**.
""", encoding="utf-8")
    REPORT.joinpath("STRUCTURAL_NONIDENTIFIABILITY_CERTIFICATES.md").write_text("""# Structural non-identifiability certificates

1. A headroom change with no natural command near the changed boundary produces the same external trajectory as nominal operation; no passive estimator can certify the smaller headroom from that trajectory.
2. Simultaneous headroom/ramp/delay changes can share compatible finite I/O histories. H2 requires safe set expansion, not exact source recovery.
3. An OEM label change that leaves the external feasible set and optimal action unchanged is intentionally control-irrelevant.

These cases remain in `structural_nonidentifiability.csv`. They delimit the claim and are not deleted failures.
""", encoding="utf-8")

    outputs = [RESULT / "h2_gate.json", RESULT / "validation_episode_summary.parquet", RESULT / "representative_causal_traces.parquet", RESULT / "capability_coverage_summary.csv", RESULT / "update_before_loss.csv", RESULT / "structural_nonidentifiability.csv", FIGURE / "capability_coverage.png", FIGURE / "causal_update_timing.png", *REPORT.glob("*.md")]
    passed = bool(validation_summary["h2_passed"])
    progress = {
        "stage": "D3", "goal": "Establish causal passive current-capability set coverage", "status": "PASSED" if passed else "FAILED",
        "gate": "H2_PASSIVE_CAPABILITY_SET", "gate_passed": passed,
        "inputs_sha256": {"plant_model": sha256(REPO / "src" / "direction1freq" / "models" / "plant_a.py")},
        "commands": ["python scripts/phase_d/d3_capability_gate.py", "python -m pytest tests/phase_d/test_d3_causal_estimation.py -q"],
        "tests": validation_summary, "failures": [] if passed else ["H2 evidence threshold not met"],
        "repairs": repair_records, "outputs_sha256": {path.relative_to(REPO).as_posix(): sha256(path) for path in outputs},
        "next_stage": "D4" if passed else "D7_NEGATIVE_PACKAGE",
    }
    (REPO / "progress_phase_d" / "D3.json").write_text(json.dumps(progress, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(progress, indent=2))
    if not passed: raise SystemExit(3)


if __name__ == "__main__":
    main()
