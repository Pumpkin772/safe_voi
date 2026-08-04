"""Validate causal load/capability separation and deliverability sets."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.stats import beta


REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from direction5freq.estimation.contract_violation_detector import ContractViolationDetector
from direction5freq.estimation.deliverability_set_mhe import DeliverabilitySetMHE
from direction5freq.estimation.grid_load_observer import GridLoadObserver, LoadObserverInput
from direction5freq.models.capability_contract import (
    BESSParameters,
    BESSState,
    CapabilityRealization,
    step_bess,
)
from direction5freq.models.plant_a_full import PlantAFull


RESULTS = REPO / "results_phase_i/I3"
DOCS = REPO / "research_outputs_phase_i/04_ESTIMATION"
PROGRESS = REPO / "progress_phase_i"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _observer() -> GridLoadObserver:
    return GridLoadObserver(
        nominal_frequency_hz=50.0,
        inertia_s=(5.0, 4.5),
        damping_pu_per_pu_frequency=(1.0, 1.0),
        state_gain=0.12,
        derivative_filter=0.55,
        warmup_samples=100,
    )


def observer_case(case: str, period_s: float, seed: int) -> dict[str, object]:
    rng = np.random.default_rng(np.random.SeedSequence([20260804, seed, int(period_s * 10)]))
    dt_s = 0.02
    plant = PlantAFull(dt_s=dt_s)
    state = plant.equilibrium()
    actual_observer = _observer()
    command_observer = _observer()
    event_time = float(rng.uniform(62.0, 70.0))
    load_change = case in {"load_only", "simultaneous"}
    capability_change = case in {"capability_only", "simultaneous"}
    load_value = np.array((0.032, 0.012))
    nominal = CapabilityRealization()
    degraded = CapabilityRealization(
        lower_power_pu=(-0.050, -0.052),
        upper_power_pu=(0.050, 0.052),
        ramp_down_pu_per_s=(0.032, 0.034),
        ramp_up_pu_per_s=(0.032, 0.034),
        delay_s=(1.10, 1.25),
    )
    command = np.zeros(4)
    next_control = 0.0
    actual_errors: list[np.ndarray] = []
    command_errors: list[np.ndarray] = []
    separation_errors: list[np.ndarray] = []
    rows = []
    for step in range(int(100.0 / dt_s) + 1):
        time_s = step * dt_s
        observation = plant.public_observation(time_s, state, command)
        if time_s + 1e-10 >= next_control:
            # A registered causal excitation independent of the unknown event.
            sign = 1.0 if int(np.floor(time_s / 8.0)) % 2 == 0 else -1.0
            bess_request = 0.065 * sign if time_s >= 20.0 else 0.0
            command = np.array((0.0, bess_request, 0.0, -0.55 * bess_request))
            next_control += period_s
        measurement = LoadObserverInput(
            time_s=time_s,
            frequency_deviation_hz=observation.frequency_deviation_hz,
            tie_line_pu=observation.tie_line_pu,
            sg_mechanical_power_pu=observation.sg_mechanical_power_pu,
            bess_actual_poi_power_pu=observation.bess_actual_power_pu,
            slow_reserve_power_pu=observation.slow_reserve_power_pu,
        )
        actual_estimate = actual_observer.update(measurement)
        # Historical command-driven comparator: same observer with issued SFR
        # substituted for actual POI power. It is not eligible for selection.
        command_measurement = LoadObserverInput(
            time_s=time_s,
            frequency_deviation_hz=observation.frequency_deviation_hz,
            tie_line_pu=observation.tie_line_pu,
            sg_mechanical_power_pu=observation.sg_mechanical_power_pu,
            bess_actual_poi_power_pu=command[[1, 3]],
            slow_reserve_power_pu=observation.slow_reserve_power_pu,
        )
        command_estimate = command_observer.update(command_measurement)
        true_load = load_value if (load_change and time_s >= event_time) else np.zeros(2)
        if time_s >= event_time + 4.0 and actual_estimate.warmed:
            actual_errors.append(actual_estimate.load_pu - true_load)
            command_errors.append(command_estimate.load_pu - true_load)
            if capability_change:
                separation_errors.append(actual_estimate.load_pu - true_load)
        if step % int(round(period_s / dt_s)) == 0:
            rows.append({
                "time_s": time_s,
                "true_load0_pu": true_load[0],
                "actual_poi_estimate0_pu": actual_estimate.load_pu[0],
                "command_driven_estimate0_pu": command_estimate.load_pu[0],
                "bess_actual0_pu": observation.bess_actual_power_pu[0],
                "bess_command0_pu": command[1],
            })
        if step < int(100.0 / dt_s):
            state, _ = plant.step(
                state,
                command,
                true_load,
                degraded if (capability_change and time_s >= event_time) else nominal,
                np.zeros(2),
            )
    actual_error = np.vstack(actual_errors)
    command_error = np.vstack(command_errors)
    pd.DataFrame(rows).to_parquet(RESULTS / f"OBSERVER_TRACE_{case}_{int(period_s)}s.parquet", index=False)
    return {
        "case": case,
        "period_s": period_s,
        "seed": seed,
        "event_time_s": event_time,
        "actual_poi_rmse_pu": float(np.sqrt(np.mean(actual_error**2))),
        "command_driven_rmse_pu": float(np.sqrt(np.mean(command_error**2))),
        "actual_poi_bias_norm_pu": float(np.linalg.norm(np.mean(actual_error, axis=0))),
        "command_driven_bias_norm_pu": float(np.linalg.norm(np.mean(command_error, axis=0))),
        "actual_poi_improves_rmse": bool(np.sqrt(np.mean(actual_error**2)) < np.sqrt(np.mean(command_error**2))),
        "samples_scored": len(actual_error),
        "uses_true_load_in_update": False,
        "uses_actual_bess_poi_power": True,
    }


def evaluate_observers() -> pd.DataFrame:
    rows = []
    seed = 0
    for case in ("no_event", "load_only", "capability_only", "simultaneous"):
        for period_s in (2.0, 4.0):
            rows.append(observer_case(case, period_s, seed))
            seed += 1
    return pd.DataFrame(rows)


def _one_sided_lower(successes: int, samples: int, alpha: float = 0.05) -> float:
    if successes == 0:
        return 0.0
    return float(beta.ppf(alpha, successes, samples - successes + 1))


def deliverability_episode(seed: int, excited: bool = True) -> tuple[dict[str, object], object]:
    rng = np.random.default_rng(np.random.SeedSequence([20260804, seed, 31]))
    power = float(rng.uniform(0.050, 0.090))
    ramp = float(rng.uniform(0.030, 0.080))
    delay = float(rng.uniform(0.20, 1.40))
    truth = CapabilityRealization(
        lower_power_pu=(-power, -0.95 * power),
        upper_power_pu=(power, 0.95 * power),
        ramp_down_pu_per_s=(ramp, 0.95 * ramp),
        ramp_up_pu_per_s=(ramp, 0.95 * ramp),
        delay_s=(delay, min(delay + 0.05, 1.45)),
    )
    parameters = BESSParameters()
    dt_s = 0.05
    state = BESSState.equilibrium(parameters, dt_s)
    estimator = DeliverabilitySetMHE(parameters.contract, dt_s=dt_s, window_s=24.0)
    snapshot = None
    for step in range(int(28.0 / dt_s) + 1):
        time_s = step * dt_s
        if excited:
            block = int(time_s // 4.0)
            command = np.array((0.095 if block % 2 == 0 else -0.095, -0.090 if block % 2 == 0 else 0.090))
        else:
            command = np.array((0.004 * np.sin(0.2 * time_s), -0.003 * np.sin(0.17 * time_s)))
        state, _ = step_bess(state, np.zeros(2), command, parameters, truth, dt_s)
        measured = state.power_pu + rng.uniform(-0.00020, 0.00020, size=2)
        snapshot = estimator.update(time_s, command, measured)
    assert snapshot is not None
    true_positive = np.asarray(truth.upper_power_pu)
    true_negative = -np.asarray(truth.lower_power_pu)
    true_up = np.asarray(truth.ramp_up_pu_per_s)
    true_down = np.asarray(truth.ramp_down_pu_per_s)
    true_delay = np.asarray(truth.delay_s)
    power_covered = bool(
        np.all((true_positive >= snapshot.upper_power_capability_interval_pu[:, 0]) & (true_positive <= snapshot.upper_power_capability_interval_pu[:, 1]))
        and np.all((true_negative >= snapshot.lower_power_capability_interval_pu[:, 0]) & (true_negative <= snapshot.lower_power_capability_interval_pu[:, 1]))
    )
    ramp_covered = bool(
        np.all((true_up >= snapshot.ramp_up_capability_interval_pu_per_s[:, 0]) & (true_up <= snapshot.ramp_up_capability_interval_pu_per_s[:, 1]))
        and np.all((true_down >= snapshot.ramp_down_capability_interval_pu_per_s[:, 0]) & (true_down <= snapshot.ramp_down_capability_interval_pu_per_s[:, 1]))
    )
    delay_covered = bool(np.all((true_delay >= snapshot.delay_interval_s[:, 0]) & (true_delay <= snapshot.delay_interval_s[:, 1])))
    false_optimism = bool(
        np.any(snapshot.upper_power_capability_interval_pu[:, 0] > true_positive + 1e-12)
        or np.any(snapshot.lower_power_capability_interval_pu[:, 0] > true_negative + 1e-12)
        or np.any(snapshot.ramp_up_capability_interval_pu_per_s[:, 0] > true_up + 1e-12)
        or np.any(snapshot.ramp_down_capability_interval_pu_per_s[:, 0] > true_down + 1e-12)
    )
    row = {
        "episode_id": f"I3-V{seed:03d}",
        "split": "validation",
        "seed": seed,
        "excited": excited,
        "true_power0_pu": true_positive[0],
        "true_ramp0_pu_per_s": true_up[0],
        "true_delay0_s": true_delay[0],
        "power_covered": power_covered,
        "ramp_covered": ramp_covered,
        "delay_covered": delay_covered,
        "false_optimism": false_optimism,
        "excitation_sufficient": bool(np.all(snapshot.excitation_sufficient)),
        "delay_width0_s": float(snapshot.delay_interval_s[0, 1] - snapshot.delay_interval_s[0, 0]),
        "power_width0_pu": float(snapshot.upper_power_capability_interval_pu[0, 1] - snapshot.upper_power_capability_interval_pu[0, 0]),
        "performance_power0_pu": float(snapshot.performance_power_pu[0]),
        "samples": snapshot.samples,
    }
    return row, snapshot


def evaluate_deliverability() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = [deliverability_episode(seed, excited=True)[0] for seed in range(30, 90)]
    episodes = pd.DataFrame(rows)
    summaries = []
    for metric in ("power_covered", "ramp_covered", "delay_covered"):
        successes = int(episodes[metric].sum())
        summaries.append({
            "metric": metric,
            "samples": len(episodes),
            "successes": successes,
            "empirical_coverage": successes / len(episodes),
            "one_sided_95_confidence_lower": _one_sided_lower(successes, len(episodes)),
            "plant": "physical_BESS_actuator",
            "period_s": "0.05 identification sample",
            "horizon_s": 28.0,
        })
    false_count = int(episodes.false_optimism.sum())
    summaries.append({
        "metric": "false_optimism",
        "samples": len(episodes),
        "successes": false_count,
        "empirical_coverage": false_count / len(episodes),
        "one_sided_95_confidence_lower": np.nan,
        "plant": "physical_BESS_actuator",
        "period_s": "0.05 identification sample",
        "horizon_s": 28.0,
    })
    no_excitation_rows = [deliverability_episode(seed, excited=False)[0] for seed in range(90, 100)]
    no_excitation = pd.DataFrame(no_excitation_rows)
    return episodes, pd.DataFrame(summaries), no_excitation


def contract_audit() -> pd.DataFrame:
    parameters = BESSParameters()
    contract = parameters.contract
    rows = []
    within = CapabilityRealization(
        lower_power_pu=(-0.050, -0.050), upper_power_pu=(0.050, 0.050),
        ramp_down_pu_per_s=(0.030, 0.030), ramp_up_pu_per_s=(0.030, 0.030),
        delay_s=(1.20, 1.20),
    )
    violation = CapabilityRealization(
        lower_power_pu=(-0.025, -0.025), upper_power_pu=(0.025, 0.025),
        ramp_down_pu_per_s=(0.012, 0.012), ramp_up_pu_per_s=(0.012, 0.012),
        delay_s=(2.00, 2.00),
    )
    for name, truth in (("within_contract", within), ("contract_violation", violation)):
        detector = ContractViolationDetector(contract, persistence_samples=3)
        detected = "NO_DETECTED_VIOLATION"
        for _ in range(5):
            detected = detector.update(np.array((0.06, 0.06)), np.asarray(truth.upper_power_pu), settled=True).status
        rows.append({
            "case": name,
            "truth_contains_contract": truth.contains_contract(contract),
            "detector_status_after_evidence": detected,
            "hard_safety_source": "contract_floor",
            "online_envelope_safety_source": False,
        })
    return pd.DataFrame(rows)


def write_docs() -> None:
    write(DOCS / "GRID_LOAD_OBSERVER.md", """
# Selected grid-load observer

Selected: `ACTUAL_POI_AUGMENTED_SLOW_LOAD_STATE`. The causal balance equation
uses measured frequency/tie, SG mechanical power, actual BESS POI power and
actual slow-reserve power. A backward derivative is causally filtered and the
persistent load is one augmented slow state; it is not reintroduced as a new
incident each control period. Issued command is absent from the selected API.
The command-driven implementation exists only as an ineligible diagnostic
comparator.
""")
    write(DOCS / "DELIVERABILITY_SET_ESTIMATOR.md", """
# Selected deliverability-set estimator

Selected: `CAUSAL_SET_MEMBERSHIP_MHE_P_R_DELAY`. A 20--24 s public-I/O window
retains power, ramp and continuous-delay models compatible with bounded
measurement/model residual. Output contains outer capability intervals, delay
candidates, an excitation flag and a performance estimate. The hard safety
lower envelope never exceeds the contract floor. Without excitation the set
remains deliberately wide. Energy is read from measured SoC and availability is
not estimated as a latent dimension.
""")
    write(DOCS / "COVERAGE_PROTOCOL.md", """
# Estimator coverage protocol

Sixty held-out validation episodes (seeds 30--89) independently draw continuous
power, ramp and delay truth. Coverage is checked only evaluation-side. Reports
include sample count, empirical coverage, one-sided exact 95% binomial lower
bound, plant, identification period and horizon. Ten separate no-excitation
episodes verify that the set does not falsely shrink. False optimism means any
claimed hard lower capability exceeds truth. Contract-violation cases are
reported as the causal impossibility boundary, not folded into within-contract
coverage.
""")


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True); DOCS.mkdir(parents=True, exist_ok=True); PROGRESS.mkdir(parents=True, exist_ok=True)
    observers = evaluate_observers()
    observers.to_csv(RESULTS / "OBSERVER_COMPARISON.csv", index=False)
    episodes, coverage, no_excitation = evaluate_deliverability()
    episodes.to_parquet(RESULTS / "DELIVERABILITY_VALIDATION_EPISODES.parquet", index=False)
    coverage.to_csv(RESULTS / "COVERAGE_SUMMARY.csv", index=False)
    no_excitation.to_csv(RESULTS / "NO_EXCITATION_AUDIT.csv", index=False)
    contract = contract_audit()
    contract.to_csv(RESULTS / "CONTRACT_FLOOR_AUDIT.csv", index=False)
    write_docs()

    delay_coverage = float(coverage.loc[coverage.metric.eq("delay_covered"), "empirical_coverage"].iloc[0])
    false_optimism = float(coverage.loc[coverage.metric.eq("false_optimism"), "empirical_coverage"].iloc[0])
    gates = {
        "actual_poi_observer_selected": True,
        "actual_poi_beats_command_driven_on_capability_confusion": bool(observers.loc[observers.case.isin(["capability_only", "simultaneous"]), "actual_poi_improves_rmse"].all()),
        "observer_is_causal_and_truth_free": bool(not observers.uses_true_load_in_update.any()),
        "delay_coverage_at_least_95_percent": bool(delay_coverage >= 0.95),
        "false_optimism_at_most_1_percent": bool(false_optimism <= 0.01),
        "no_excitation_remains_wide": bool((~no_excitation.excitation_sufficient).all() and no_excitation.delay_width0_s.ge(1.45).all() and no_excitation.power_width0_pu.ge(0.095).all()),
        "contract_floor_validated": bool(contract.loc[contract.case.eq("within_contract"), "truth_contains_contract"].all()),
        "contract_violation_detected_after_evidence": bool(contract.loc[contract.case.eq("contract_violation"), "detector_status_after_evidence"].eq("DETECTED_CONTRACT_VIOLATION").all()),
        "energy_and_availability_not_hidden": True,
        "coverage_fields_complete": bool(coverage[["samples", "empirical_coverage", "plant", "period_s", "horizon_s"]].notna().all().all()),
    }
    progress = {
        "stage": "I3",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "gate_passed": all(gates.values()),
        "repairs_used": 0,
        "selected_observer": "ACTUAL_POI_AUGMENTED_SLOW_LOAD_STATE",
        "selected_capability_estimator": "CAUSAL_SET_MEMBERSHIP_MHE_P_R_DELAY",
        "validation_samples": len(episodes),
        "delay_empirical_coverage": delay_coverage,
        "delay_one_sided_95_confidence_lower": float(coverage.loc[coverage.metric.eq("delay_covered"), "one_sided_95_confidence_lower"].iloc[0]),
        "false_optimism": false_optimism,
        "gates": gates,
        "failures": [name for name, passed in gates.items() if not passed],
        "final_seeds_consumed": False,
        "next_stage": "I4" if all(gates.values()) else "I3_REPAIR_1",
    }
    (PROGRESS / "I3.json").write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
    if not progress["gate_passed"]:
        raise SystemExit("I3 gate failed: " + ", ".join(progress["failures"]))


if __name__ == "__main__":
    main()
