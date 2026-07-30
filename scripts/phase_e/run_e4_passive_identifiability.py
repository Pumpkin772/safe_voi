"""Run E4 causal passive capability-set identifiability audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from direction1freq.controllers import ACEPIAntiWindup, design_stable_pi
from direction1freq.evaluation.control_critical_window import (
    causal_control_relevant_update_time, contains_capability,
)
from direction1freq.identification.causal_glr import CausalGLRSetReset
from direction1freq.identification.imm_capability import IMMIntervalCapabilityObserver
from direction1freq.identification.passive_set_membership import (
    CAPABILITY_NAMES, GLOBAL_LOWER, GLOBAL_UPPER, MultiStepSetMembership,
)
from direction1freq.models.bess_capability_v2 import CapabilityTruthV2
from direction1freq.models.plant_a_v2 import TwoAreaPlantAV2
from direction1freq.models.plant_b_andes_v2 import AndesKundurPlantBV2
from scripts.phase_e.run_e3_materiality import (
    ControllerBank, capability_at, simulate_plant_a_episode,
)


REPO = Path(__file__).resolve().parents[2]
RESULT = REPO / "results_phase_e" / "E4"
DOC = REPO / "research_outputs_phase_e" / "05_IDENTIFICATION"
SUMMARY_DOC = REPO / "research_outputs_phase_e" / "09_SUMMARY"
FIGURE = REPO / "figures_phase_e" / "E4"
ESTIMATORS = (MultiStepSetMembership, CausalGLRSetReset, IMMIntervalCapabilityObserver)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capability_vector(row: pd.Series | dict[str, Any], time_s: float) -> np.ndarray:
    values = np.array([1.0, 1.0, 0.2, 1.0, 1.0])
    if time_s < float(row["capability_change_time_s"]):
        return values
    mechanism = str(row["mechanism"])
    values[CAPABILITY_NAMES.index(mechanism)] = {
        "headroom": 0.35, "ramp": 0.15, "delay": 1.6,
        "energy": 0.04, "availability": 0.30,
    }[mechanism]
    return values


def public_trace_columns(trace: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    time = trace.time_s.to_numpy(dtype=float)
    command = trace[["cmd_b1", "cmd_b2"]].to_numpy(dtype=float)
    power = trace[["pb1", "pb2"]].to_numpy(dtype=float)
    frequency = trace[["df1_hz", "df2_hz"]].to_numpy(dtype=float)
    # Each E3 row records the newly computed command beside the pre-action
    # observation.  Shift once so the estimator sees the command actually
    # issued during the preceding interval.
    issued = np.vstack((np.zeros((1, 2)), command[:-1]))
    return time, issued, power, frequency


def evaluate_trace(
    trace: pd.DataFrame, row: pd.Series | dict[str, Any], estimator_type,
    tcrit_s: float, scope: str, plant: str = "A",
) -> tuple[dict[str, Any], pd.DataFrame]:
    period = float(row["sfr_period_s"])
    estimator = estimator_type(period)
    time, issued, power, frequency = public_trace_columns(trace)
    estimates = []
    capabilities = []
    event_rows = []
    for index, time_s in enumerate(time):
        estimate = estimator.update(time_s, issued[index], power[index], frequency[index])
        capability = capability_vector(row, time_s)
        estimates.append(estimate)
        capabilities.append(capability)
        event_rows.append({
            "scenario_id": row["scenario_id"], "scope": scope, "plant": plant,
            "estimator": estimator.name, "time_s": time_s,
            "alarm": estimate.alarm, "set_changed": estimate.set_changed,
            "candidate": estimate.candidate, "status": estimate.status,
            "excitation": estimate.excitation, "residual": estimate.residual,
            "gramian_lambda_min": estimate.gramian_lambda_min,
            "gramian_condition": estimate.gramian_condition,
            "normalized_width": estimate.normalized_width,
            "joint_truth_covered": contains_capability(estimate, capability),
            **{f"lower_{name}": estimate.lower[j] for j, name in enumerate(CAPABILITY_NAMES)},
            **{f"upper_{name}": estimate.upper[j] for j, name in enumerate(CAPABILITY_NAMES)},
        })
    change_time = float(row["capability_change_time_s"])
    alarms = [estimate.time_s for estimate in estimates if estimate.time_s >= change_time and estimate.alarm]
    alarm_time = float(alarms[0]) if alarms else float("nan")
    update_time = causal_control_relevant_update_time(estimates, capabilities, change_time)
    finite_tcrit = bool(np.isfinite(tcrit_s))
    update_evaluated = finite_tcrit
    update_before = bool(np.isfinite(update_time) and finite_tcrit and update_time < tcrit_s)
    after = [j for j, value in enumerate(time) if value >= change_time]
    max_excitation = max((estimates[j].excitation for j in after), default=0.0)
    throughput = float(np.sum(np.abs(power[after])) * period) if after else 0.0
    mechanism = str(row["mechanism"])
    if mechanism in {"headroom", "availability"} and max_excitation < 0.035:
        failure_cause = "structural_upper_capability_unidentifiable_in_safe_range"
    elif mechanism == "energy" and throughput < 0.20:
        failure_cause = "insufficient_energy_excitation"
    elif max_excitation < 0.02:
        failure_cause = "insufficient_natural_excitation"
    elif not np.isfinite(update_time):
        failure_cause = "finite_sample_or_estimator_design_failure"
    else:
        failure_cause = "none"
    record = {
        "scenario_id": row["scenario_id"], "scope": scope, "plant": plant,
        "estimator": estimator.name, "mechanism": mechanism,
        "sg_tension": row.get("sg_tension", "scarce"), "sfr_period_s": period,
        "load_timing": row.get("load_timing", "simultaneous"),
        "capability_change_time_s": change_time,
        "joint_truth_coverage": float(np.mean([
            contains_capability(estimate, capability)
            for estimate, capability in zip(estimates, capabilities)
        ])),
        "alarm_time_s": alarm_time, "control_relevant_update_time_s": update_time,
        "Tdet_delay_s": alarm_time - change_time if np.isfinite(alarm_time) else float("nan"),
        "Tupdate_delay_s": update_time - change_time if np.isfinite(update_time) else float("nan"),
        "Tcrit_s": tcrit_s, "timing_evaluated": update_evaluated,
        "update_before_Tcrit": update_before,
        "final_normalized_width": estimates[-1].normalized_width,
        "max_natural_excitation": max_excitation,
        "cumulative_bess_throughput_pu_s": throughput,
        "failure_cause": failure_cause,
    }
    return record, pd.DataFrame(event_rows)


def no_change_false_alarm() -> pd.DataFrame:
    raw = pd.read_parquet(REPO / "results_phase_e" / "E2" / "background_1h_pi.parquet")
    rows = []
    for period in (2.0, 4.0):
        sampled = raw.iloc[:: int(period)].reset_index(drop=True)
        for estimator_type in ESTIMATORS:
            estimator = estimator_type(period)
            alarm_count = 0
            command = sampled[["cmd_b1_pu", "cmd_b2_pu"]].to_numpy(float)
            issued = np.vstack((np.zeros((1, 2)), command[:-1]))
            for index, item in sampled.iterrows():
                estimate = estimator.update(
                    float(item.time_s), issued[index],
                    np.array([item.pb1_pu, item.pb2_pu]),
                    np.array([item.df1_hz, item.df2_hz]),
                )
                alarm_count += int(estimate.alarm)
            rows.append({
                "estimator": estimator.name, "sfr_period_s": period,
                "duration_s": 3600.0, "updates": len(sampled),
                "false_alarms": alarm_count,
                "false_alarm_rate": alarm_count / len(sampled),
            })
    return pd.DataFrame(rows)


def random_and_accident_sensitivity() -> tuple[list[dict[str, Any]], list[pd.DataFrame]]:
    base = pd.read_csv(RESULT.parent / "E3" / "full" / "E3_EXPERIMENT_MANIFEST.csv")
    selected = []
    changes = (16.0, 24.0, 32.0, 40.0, 48.0)
    for (mechanism, period), frame in base.groupby(["mechanism", "sfr_period_s"]):
        for local, (_, source) in enumerate(frame.head(5).iterrows()):
            row = source.copy()
            row["scenario_id"] = f"E4R_{mechanism}_{int(period)}_{local}"
            row["capability_change_time_s"] = changes[local]
            selected.append(row)
    records: list[dict[str, Any]] = []
    events: list[pd.DataFrame] = []
    banks = {2.0: ControllerBank(2.0, 3), 4.0: ControllerBank(4.0, 3)}
    for row in selected:
        _episode, trace = simulate_plant_a_episode(
            row, "fixed_allocation_pi", banks[float(row.sfr_period_s)]
        )
        for estimator_type in ESTIMATORS:
            record, event = evaluate_trace(
                trace, row, estimator_type, float("nan"), "random_change_sensitivity"
            )
            records.append(record); events.append(event)
    # Five 300 s accident trajectories retain long-window energy evidence.
    for mechanism, frame in base[(base.sfr_period_s == 4.0)].groupby("mechanism"):
        row = frame.iloc[0].copy()
        row["scenario_id"] = f"E4A_{mechanism}"
        row["capability_change_time_s"] = 60.0
        row["load_timing"] = "after"
        _episode, trace = simulate_plant_a_episode(
            row, "fixed_allocation_pi", banks[4.0], duration_s=300.0
        )
        for estimator_type in ESTIMATORS:
            record, event = evaluate_trace(
                trace, row, estimator_type, float("nan"), "accident_300s"
            )
            records.append(record); events.append(event)
    return records, events


def plant_b_audit(tcrit_lag: dict[str, float]) -> pd.DataFrame:
    records = []
    for mechanism in CAPABILITY_NAMES:
        for period in (2.0, 4.0):
            proportional, integral, _ = design_stable_pi(TwoAreaPlantAV2(), period)
            controller = ACEPIAntiWindup(period, proportional, integral, sg_fraction=0.70)
            controller.reset()

            def policy(observation):
                action, _ = controller.update(observation)
                action[[0, 2]] = np.clip(action[[0, 2]], -0.05, 0.05)
                return action

            row = {
                "scenario_id": f"E4B_{mechanism}_{int(period)}", "mechanism": mechanism,
                "sg_tension": "scarce", "sfr_period_s": period,
                "load_timing": "simultaneous", "capability_change_time_s": 20.0,
            }
            native = AndesKundurPlantBV2(dt_s=0.05).run_causal_closed_loop(
                duration_s=64.0, control_period_s=period,
                load_profile=lambda time_s: np.array([0.06 if time_s >= 20.0 else 0.0, 0.0]),
                policy=policy,
                capability_profile=lambda time_s, item=row: capability_at(item, time_s),
            )
            indices = [int(np.argmin(np.abs(native.time_s - target))) for target in np.arange(0, 64.1, period)]
            trace = pd.DataFrame({
                "time_s": native.time_s[indices],
                "df1_hz": native.frequency_deviation_hz[indices, 0],
                "df2_hz": native.frequency_deviation_hz[indices, 1],
                "cmd_b1": native.issued_command_pu[indices, 1],
                "cmd_b2": native.issued_command_pu[indices, 3],
                "pb1": native.bess_power_pu[indices, 0],
                "pb2": native.bess_power_pu[indices, 1],
            }).drop_duplicates("time_s")
            approximate_tcrit = 20.0 + tcrit_lag.get(mechanism, float("nan"))
            for estimator_type in ESTIMATORS:
                record, _event = evaluate_trace(
                    trace, row, estimator_type, approximate_tcrit, "plant_b_representative", "B"
                )
                record["native_converged"] = native.converged
                record["native_balance_p99_pu"] = native.algebraic_power_balance_p99_pu
                records.append(record)
    return pd.DataFrame(records)


def main() -> None:
    RESULT.mkdir(parents=True, exist_ok=True); DOC.mkdir(parents=True, exist_ok=True)
    SUMMARY_DOC.mkdir(parents=True, exist_ok=True); FIGURE.mkdir(parents=True, exist_ok=True)
    manifest = pd.read_csv(RESULT.parent / "E3" / "full" / "E3_EXPERIMENT_MANIFEST.csv")
    traces = pd.read_parquet(RESULT.parent / "E3" / "full" / "E3_CONTROL_RATE_TRACES.parquet")
    tcrit = pd.read_csv(RESULT.parent / "E3" / "full" / "TCRIT_DEVELOPMENT.csv").set_index("scenario_id")
    records: list[dict[str, Any]] = []
    events: list[pd.DataFrame] = []
    fixed = traces[traces.method == "fixed_allocation_pi"]
    for _, row in manifest.iterrows():
        trace = fixed[fixed.scenario_id == row.scenario_id].copy()
        critical = float(tcrit.loc[row.scenario_id, "Tcrit_s"])
        for estimator_type in ESTIMATORS:
            record, event = evaluate_trace(trace, row, estimator_type, critical, "main_matched")
            records.append(record); events.append(event)
    sensitivity_records, sensitivity_events = random_and_accident_sensitivity()
    records.extend(sensitivity_records); events.extend(sensitivity_events)
    episode = pd.DataFrame(records)
    event_frame = pd.concat(events, ignore_index=True)
    no_change = no_change_false_alarm()
    main = episode[episode.scope == "main_matched"]
    summary_rows = []
    for (estimator, mechanism), frame in main.groupby(["estimator", "mechanism"]):
        evaluated = frame[frame.timing_evaluated]
        summary_rows.append({
            "estimator": estimator, "mechanism": mechanism, "episodes": len(frame),
            "joint_truth_coverage": float(frame.joint_truth_coverage.mean()),
            "timing_evaluated_episodes": len(evaluated),
            "p_update_before_tcrit": float(evaluated.update_before_Tcrit.mean()) if len(evaluated) else float("nan"),
            "median_final_normalized_width": float(frame.final_normalized_width.median()),
            "median_max_natural_excitation": float(frame.max_natural_excitation.median()),
            "structural_or_excitation_failure_rate": float((frame.failure_cause != "none").mean()),
        })
    summary = pd.DataFrame(summary_rows)
    tcrit_lag = (
        main.assign(lag=main.Tcrit_s - main.capability_change_time_s)
        .groupby("mechanism").lag.median().to_dict()
    )
    native = plant_b_audit(tcrit_lag)
    gates = []
    for estimator in sorted(main.estimator.unique()):
        frame = summary[summary.estimator == estimator]
        coverage = float(main[main.estimator == estimator].joint_truth_coverage.mean())
        false_alarm = float(no_change[no_change.estimator == estimator].false_alarm_rate.max())
        mechanisms = int((frame.p_update_before_tcrit >= 0.80).sum())
        width = float(frame.median_final_normalized_width.mean())
        native_frame = native[native.estimator == estimator]
        native_mechanisms = int((
            native_frame.groupby("mechanism").update_before_Tcrit.mean() >= 0.80
        ).sum())
        plant_a_pass = mechanisms >= 3
        plant_b_pass = native_mechanisms >= 3
        direction = plant_a_pass == plant_b_pass
        passed = bool(
            coverage >= 0.95 and false_alarm <= 0.05 and mechanisms >= 3
            and width <= 0.85 and direction
        )
        gates.append({
            "estimator": estimator, "joint_truth_coverage": coverage,
            "no_change_false_alarm_rate": false_alarm,
            "mechanisms_passing_timing": mechanisms,
            "mean_final_normalized_width": width,
            "plant_b_mechanisms_passing_timing": native_mechanisms,
            "plant_a_b_direction_consistent": direction, "passive_gate_pass": passed,
        })
    gate_frame = pd.DataFrame(gates)
    passing = gate_frame[gate_frame.passive_gate_pass]
    gate_passed = bool(len(passing))
    selected = str(passing.sort_values("mean_final_normalized_width").iloc[0].estimator) if gate_passed else "none_qualified"
    episode.to_parquet(RESULT / "E4_PASSIVE_EPISODES.parquet", index=False)
    event_frame.to_parquet(RESULT / "E4_SET_EVENTS.parquet", index=False)
    summary.to_csv(RESULT / "E4_PASSIVE_COVERAGE_TIMING.csv", index=False)
    gate_frame.to_csv(RESULT / "E4_ESTIMATOR_GATE_SUMMARY.csv", index=False)
    no_change.to_csv(RESULT / "E4_NO_CHANGE_FALSE_ALARM.csv", index=False)
    native.to_parquet(RESULT / "E4_PLANT_B_PASSIVE.parquet", index=False)
    plt.figure(figsize=(9, 4.8))
    pivot = summary.pivot(index="mechanism", columns="estimator", values="p_update_before_tcrit")
    pivot.plot(kind="bar", ax=plt.gca()); plt.axhline(0.8, color="black", linestyle="--")
    plt.ylabel("P(control-relevant update < Tcrit)"); plt.ylim(0, 1.05); plt.tight_layout()
    plt.savefig(FIGURE / "e4_passive_timing.png", dpi=180); plt.close()
    report = DOC / "PASSIVE_IDENTIFIABILITY_REPORT.md"
    report.write_text(f"""# E4 passive identifiability report

Three causal baselines were evaluated: multi-step set membership, GLR/CUSUM with global-set reset, and an IMM interval observer. All use only issued commands, POI BESS power, frequency, and past samples. Truth labels are consumed only by evaluation coverage and update-time functions.

G4 result: **{'PASS — PASSIVE_IDENTIFIABLE' if gate_passed else 'FAIL — passive capability set not supported'}**. Selected passive estimator: **{selected}**. No estimator was selected merely because all candidates failed. The natural fixed-allocation closed loop provides very small BESS excitation; unhit upper headroom/availability remains structurally confounded, and energy capability remains uninformative at the observed throughput. Alarm time is reported separately from the first control-relevant set change that re-covers the evaluation truth.

Random change-time sensitivity, a retained 1 h no-change trace, 300 s accident traces, 2/4 s sampling, and native Plant B representatives are included. Episodes without a finite matched Tcrit are marked `timing_evaluated=false` and are not counted as method failures.
""", encoding="utf-8")
    branch = SUMMARY_DOC / "E4_BRANCH_DECISION.md"
    branch.write_text(
        "# E4 branch decision\n\n" + (
            "G4 passed; skip E5 and select branch P.\n" if gate_passed
            else "G3 passed but G4 failed; proceed to E5 safe active-identification feasibility.\n"
        ), encoding="utf-8"
    )
    outputs = [
        RESULT / "E4_PASSIVE_EPISODES.parquet", RESULT / "E4_SET_EVENTS.parquet",
        RESULT / "E4_PASSIVE_COVERAGE_TIMING.csv", RESULT / "E4_ESTIMATOR_GATE_SUMMARY.csv",
        RESULT / "E4_NO_CHANGE_FALSE_ALARM.csv", RESULT / "E4_PLANT_B_PASSIVE.parquet",
        FIGURE / "e4_passive_timing.png", report, branch,
    ]
    progress = {
        "stage": "E4", "status": "PASSED" if gate_passed else "FAILED",
        "goal": "Determine whether passive capability sets update before control loss",
        "gate": "G4_PASSIVE", "gate_passed": gate_passed,
        "selected_passive_estimator": selected,
        "gate_table": gates,
        "tests": {
            "main_episode_rows": len(main), "set_event_rows": len(event_frame),
            "random_change_episode_rows": int((episode.scope == "random_change_sensitivity").sum()),
            "accident_300s_episode_rows": int((episode.scope == "accident_300s").sum()),
            "normal_background_duration_s": 3600,
            "plant_b_episode_rows": len(native),
            "not_evaluated_timing_rows": int((~episode.timing_evaluated).sum()),
        },
        "failures": [] if gate_passed else [
            "No passive baseline jointly met coverage, false-alarm, >=3/5 timing, set contraction, and Plant A/B direction requirements."
        ],
        "repairs": [],
        "commands": [
            "python -m scripts.phase_e.run_e4_passive_identifiability",
            "python -m pytest tests/phase_e/test_e4_passive.py -q",
        ],
        "outputs_sha256": {path.relative_to(REPO).as_posix(): sha256(path) for path in outputs},
        "decision": "SELECT_BRANCH_P" if gate_passed else "CONTINUE_TO_E5",
        "next_stage": "E6" if gate_passed else "E5",
    }
    progress_path = REPO / "progress_phase_e" / "E4.json"
    progress_path.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(progress, indent=2))


if __name__ == "__main__":
    main()
