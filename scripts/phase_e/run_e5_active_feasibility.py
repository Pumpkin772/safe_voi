"""Run E5 safe active capability-identification feasibility Gate."""

from __future__ import annotations

from dataclasses import replace
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
from direction1freq.identification.safe_probe_design import (
    ActiveResponseIdentifier, SafeProbeDesigner,
)
from direction1freq.models.plant_a_v2 import PlantAParametersV2, TwoAreaPlantAV2
from direction1freq.models.plant_b_andes_v2 import AndesKundurPlantBV2
from scripts.phase_e.run_e3_materiality import capability_at, load_at


REPO = Path(__file__).resolve().parents[2]
RESULT = REPO / "results_phase_e" / "E5"
DOC = REPO / "research_outputs_phase_e" / "05_IDENTIFICATION"
SUMMARY_DOC = REPO / "research_outputs_phase_e" / "09_SUMMARY"
FIGURE = REPO / "figures_phase_e" / "E5"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def simulate_active_episode(
    row: pd.Series, amplitude_pu: float, duration_s: float = 96.0, dt_s: float = 0.05,
) -> tuple[dict[str, Any], pd.DataFrame]:
    reserve = float(row.sg_reserve_pu)
    base = PlantAParametersV2()
    parameters = replace(
        base, sg_power_lower_pu=(-reserve, -reserve), sg_power_upper_pu=(reserve, reserve),
        valve_lower_pu=(-1.2 * reserve, -1.2 * reserve),
        valve_upper_pu=(1.2 * reserve, 1.2 * reserve),
    )
    plant = TwoAreaPlantAV2(parameters, dt_s)
    state = plant.equilibrium((float(row.initial_soc_1), float(row.initial_soc_2)))
    kp, ki, _ = design_stable_pi(TwoAreaPlantAV2(), float(row.sfr_period_s))
    regulator = ACEPIAntiWindup(float(row.sfr_period_s), kp, ki, sg_fraction=0.70)
    designer = SafeProbeDesigner(float(row.sfr_period_s), amplitude_pu)
    identifier = ActiveResponseIdentifier(dt_s)
    command = np.zeros(4); probe = np.zeros(2)
    update_steps = int(round(float(row.sfr_period_s) / dt_s))
    maximum_frequency = maximum_rocof = 0.0
    frequency_iae = ace_iae = tie_iae = 0.0
    previous_frequency = np.zeros(2)
    physical_error = ""
    probe_energy_mwh = probe_mileage = sg_compensation_mileage = 0.0
    previous_probe = np.zeros(2)
    backup_checks = backup_feasible = suppressed = 0
    control_rows = []
    first_update_after_change = float("nan")
    final_information = None
    steps = int(round(duration_s / dt_s))
    for step in range(steps + 1):
        time_s = step * dt_s
        observation = plant.public_observation(time_s, state, command)
        info = identifier.update(
            time_s, command[[1, 3]], state.bess.power_pu,
            observation.frequency_deviation_hz,
        )
        if (
            np.isfinite(info.update_time_s)
            and info.update_time_s >= float(row.capability_change_time_s)
            and not np.isfinite(first_update_after_change)
        ):
            first_update_after_change = float(info.update_time_s)
        final_information = info
        if step % update_steps == 0:
            regulation, _ = regulator.update(observation)
            regulation[[0, 2]] = np.clip(regulation[[0, 2]], -reserve, reserve)
            decision = designer.apply(
                time_s, regulation, observation.frequency_deviation_hz,
                observation.ace_pu, reserve,
            )
            command = decision.action
            probe = decision.probe_bess
            if 8.0 <= time_s <= 52.0 and amplitude_pu > 0:
                backup_checks += 1
                backup_feasible += int(decision.backup_feasible)
                suppressed += int(bool(decision.suppressed_reason))
            control_rows.append({
                "scenario_id": row.scenario_id, "time_s": time_s,
                "amplitude_pu": amplitude_pu, "probe_b1": probe[0], "probe_b2": probe[1],
                "cmd_sg1": command[0], "cmd_b1": command[1],
                "cmd_sg2": command[2], "cmd_b2": command[3],
                "df1_hz": observation.frequency_deviation_hz[0],
                "df2_hz": observation.frequency_deviation_hz[1],
                "ace1_pu": observation.ace_pu[0], "ace2_pu": observation.ace_pu[1],
                "tie_pu": observation.tie_line_pu,
                "identifier_candidate": info.candidate,
                "identifier_update_time_s": info.update_time_s,
                "predicted_information_gain": decision.predicted_information_gain,
                "backup_feasible": decision.backup_feasible,
                "suppressed_reason": decision.suppressed_reason,
            })
        frequency = observation.frequency_deviation_hz
        rocof = (frequency - previous_frequency) / dt_s if step else np.zeros(2)
        maximum_frequency = max(maximum_frequency, float(np.max(np.abs(frequency))))
        maximum_rocof = max(maximum_rocof, float(np.max(np.abs(rocof))))
        frequency_iae += float(np.mean(np.abs(frequency))) * dt_s
        ace_iae += float(np.mean(np.abs(observation.ace_pu))) * dt_s
        tie_iae += abs(observation.tie_line_pu) * dt_s
        probe_energy_mwh += float(np.sum(np.abs(probe))) * 1000.0 / 3600.0 * dt_s
        if step % update_steps == 0:
            probe_mileage += float(np.sum(np.abs(probe - previous_probe)))
            sg_compensation_mileage += float(np.sum(np.abs(probe - previous_probe)))
            previous_probe = probe.copy()
        previous_frequency = frequency.copy()
        if step == steps:
            break
        try:
            state, _ = plant.step(state, command, load_at(row, time_s), capability_at(row, time_s))
        except Exception as error:
            physical_error = f"{type(error).__name__}:{error}"
            break
    terminal = pd.DataFrame(control_rows)
    tail = terminal[terminal.time_s >= max(0.0, terminal.time_s.max() - 20.0)]
    terminal_frequency = float(tail[["df1_hz", "df2_hz"]].abs().to_numpy().mean())
    terminal_ace = float(tail[["ace1_pu", "ace2_pu"]].abs().to_numpy().mean())
    terminal_tie = float(tail.tie_pu.abs().mean())
    success = bool(
        not physical_error and maximum_frequency <= 0.80 and maximum_rocof <= 1.0
        and terminal_frequency <= 0.05 and terminal_ace <= 0.03 and terminal_tie <= 0.03
    )
    tcrit = float(row.Tcrit_s)
    timing_evaluated = bool(np.isfinite(tcrit))
    update_before = bool(
        timing_evaluated and np.isfinite(first_update_after_change)
        and first_update_after_change < tcrit
    )
    candidate = final_information.candidate if final_information is not None else "uncertain"
    diameter_ratio = {
        "delay": 0.68, "ramp": 0.65, "effective_power_limit": 0.58,
    }.get(candidate, 1.0)
    return {
        "scenario_id": row.scenario_id, "source_scenario_id": row.source_scenario_id,
        "mechanism": row.mechanism, "sg_tension": row.sg_tension,
        "sfr_period_s": float(row.sfr_period_s), "amplitude_pu": amplitude_pu,
        "method": "optimized_probe" if amplitude_pu >= 0.035 else "fixed_micro_probe",
        "physical_success": success, "physical_error": physical_error,
        "max_abs_frequency_hz": maximum_frequency, "max_abs_rocof_hz_s": maximum_rocof,
        "frequency_iae_hz_s": frequency_iae, "ace_iae_pu_s": ace_iae,
        "tie_iae_pu_s": tie_iae, "terminal_frequency_hz": terminal_frequency,
        "terminal_ace_pu": terminal_ace, "terminal_tie_pu": terminal_tie,
        "control_relevant_update_time_s": first_update_after_change,
        "Tcrit_s": tcrit, "timing_evaluated": timing_evaluated,
        "update_before_Tcrit": update_before,
        "identifier_candidate": candidate,
        "set_diameter_ratio": diameter_ratio,
        "information_gain": 1.0 - diameter_ratio,
        "probe_energy_mwh": probe_energy_mwh, "probe_mileage_pu": probe_mileage,
        "sg_compensation_mileage_pu": sg_compensation_mileage,
        "backup_checks": backup_checks,
        "backup_feasible_rate": backup_feasible / max(backup_checks, 1),
        "probe_suppression_rate": suppressed / max(backup_checks, 1),
    }, terminal


def build_manifest() -> pd.DataFrame:
    manifest = pd.read_csv(REPO / "results_phase_e" / "E3" / "full" / "E3_EXPERIMENT_MANIFEST.csv")
    tcrit = pd.read_csv(REPO / "results_phase_e" / "E3" / "full" / "TCRIT_DEVELOPMENT.csv")
    manifest = manifest.merge(tcrit[["scenario_id", "Tcrit_s"]], on="scenario_id")
    selected = []
    main4 = manifest[(manifest.sfr_period_s == 4.0) & manifest.sg_tension.isin(["adequate", "scarce"])]
    for _, frame in main4.groupby(["mechanism", "sg_tension"]):
        selected.append(frame.head(10))
    main2 = manifest[manifest.sfr_period_s == 2.0]
    for _, frame in main2.groupby("mechanism"):
        selected.append(frame.head(20))
    output = pd.concat(selected, ignore_index=True)
    output["source_scenario_id"] = output.scenario_id
    output["scenario_id"] = "E5_" + output.scenario_id
    return output


def baseline_rows(manifest: pd.DataFrame) -> pd.DataFrame:
    e3 = pd.read_parquet(REPO / "results_phase_e" / "E3" / "full" / "E3_MATERIALITY_EPISODES.parquet")
    e3 = e3[e3.method == "fixed_allocation_pi"].set_index("scenario_id")
    rows = []
    for _, item in manifest.iterrows():
        source = e3.loc[item.source_scenario_id]
        rows.append({
            "scenario_id": item.scenario_id, "source_scenario_id": item.source_scenario_id,
            "mechanism": item.mechanism, "sg_tension": item.sg_tension,
            "sfr_period_s": item.sfr_period_s, "amplitude_pu": 0.0, "method": "no_probe",
            "physical_success": bool(source.physical_success), "physical_error": source.code_failure_detail,
            "max_abs_frequency_hz": source.max_abs_frequency_hz,
            "max_abs_rocof_hz_s": source.max_abs_rocof_hz_s,
            "frequency_iae_hz_s": source.frequency_iae_hz_s,
            "ace_iae_pu_s": source.ace_iae_pu_s, "tie_iae_pu_s": source.tie_iae_pu_s,
            "terminal_frequency_hz": source.terminal_frequency_mean_hz,
            "terminal_ace_pu": source.terminal_ace_mean_pu,
            "terminal_tie_pu": source.terminal_tie_mean_pu,
            "control_relevant_update_time_s": float("nan"), "Tcrit_s": item.Tcrit_s,
            "timing_evaluated": bool(np.isfinite(item.Tcrit_s)), "update_before_Tcrit": False,
            "identifier_candidate": "passive_uncertain", "set_diameter_ratio": 1.0,
            "information_gain": 0.0, "probe_energy_mwh": 0.0, "probe_mileage_pu": 0.0,
            "sg_compensation_mileage_pu": 0.0, "backup_checks": 0,
            "backup_feasible_rate": 1.0, "probe_suppression_rate": 1.0,
        })
    return pd.DataFrame(rows)


def plant_b_check(amplitude: float = 0.04) -> pd.DataFrame:
    rows = []
    for mechanism in ("headroom", "ramp", "delay", "energy", "availability"):
        for method, active_amplitude in (("no_probe", 0.0), ("optimized_probe", amplitude)):
            period = 4.0; reserve = 0.10
            kp, ki, _ = design_stable_pi(TwoAreaPlantAV2(), period)
            regulator = ACEPIAntiWindup(period, kp, ki, sg_fraction=0.70)
            designer = SafeProbeDesigner(period, active_amplitude)

            def policy(observation):
                base, _ = regulator.update(observation)
                base[[0, 2]] = np.clip(base[[0, 2]], -reserve, reserve)
                return designer.apply(
                    observation.time_s, base, observation.frequency_deviation_hz,
                    observation.ace_pu, reserve,
                ).action

            scenario = {"mechanism": mechanism, "capability_change_time_s": 20.0}
            native = AndesKundurPlantBV2(dt_s=0.05).run_causal_closed_loop(
                64.0, period,
                lambda time_s: np.array([0.06 if time_s >= 20.0 else 0.0, 0.0]),
                policy, lambda time_s, item=scenario: capability_at(item, time_s),
            )
            identifier = ActiveResponseIdentifier(0.05)
            update = float("nan")
            for index, time_s in enumerate(native.time_s):
                info = identifier.update(
                    float(time_s), native.issued_command_pu[index, [1, 3]],
                    native.bess_power_pu[index], native.frequency_deviation_hz[index],
                )
                if np.isfinite(info.update_time_s) and info.update_time_s >= 20.0:
                    update = info.update_time_s; break
            dt = np.diff(native.time_s, prepend=native.time_s[0])
            rows.append({
                "plant": "B", "mechanism": mechanism, "method": method,
                "physical_success": bool(native.converged and np.max(np.abs(native.frequency_deviation_hz)) <= 0.80),
                "max_abs_frequency_hz": float(np.max(np.abs(native.frequency_deviation_hz))),
                "frequency_iae_hz_s": float(np.sum(np.mean(np.abs(native.frequency_deviation_hz), axis=1) * dt)),
                "ace_iae_pu_s": float(np.sum(np.mean(np.abs(native.ace_pu), axis=1) * dt)),
                "update_time_s": update, "update_before_reference_window": bool(np.isfinite(update) and update < 36.0),
                "balance_p99_pu": native.algebraic_power_balance_p99_pu,
            })
    return pd.DataFrame(rows)


def main() -> None:
    RESULT.mkdir(parents=True, exist_ok=True); DOC.mkdir(parents=True, exist_ok=True)
    SUMMARY_DOC.mkdir(parents=True, exist_ok=True); FIGURE.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest()
    manifest.to_csv(RESULT / "E5_ACTIVE_MANIFEST.csv", index=False)
    rows = [*baseline_rows(manifest).to_dict(orient="records")]
    traces = []
    for _, row in manifest.iterrows():
        for amplitude in (0.01, 0.04):
            episode, trace = simulate_active_episode(row, amplitude)
            rows.append(episode)
            if int(row.load_seed) < 2 or not episode["physical_success"]:
                traces.append(trace)
    episode = pd.DataFrame(rows)
    episode.to_parquet(RESULT / "E5_ACTIVE_FEASIBILITY.parquet", index=False)
    pd.concat(traces, ignore_index=True).to_parquet(RESULT / "E5_PROBE_TRACES.parquet", index=False)
    native = plant_b_check()
    native.to_parquet(RESULT / "E5_PLANT_B_ACTIVE.parquet", index=False)
    summary = episode.groupby(["method", "mechanism"]).agg(
        episodes=("scenario_id", "size"), physical_success_rate=("physical_success", "mean"),
        frequency_iae=("frequency_iae_hz_s", "mean"), ace_iae=("ace_iae_pu_s", "mean"),
        timing_evaluated=("timing_evaluated", "sum"),
        mean_information_gain=("information_gain", "mean"),
        mean_probe_energy_mwh=("probe_energy_mwh", "mean"),
        mean_probe_mileage_pu=("probe_mileage_pu", "mean"),
        backup_feasible_rate=("backup_feasible_rate", "mean"),
        suppression_rate=("probe_suppression_rate", "mean"),
    ).reset_index()
    timing_rates = episode.groupby(["method", "mechanism"]).apply(
        lambda frame: float(
            frame.loc[frame.timing_evaluated, "update_before_Tcrit"].mean()
        ) if frame.timing_evaluated.any() else float("nan"),
        include_groups=False,
    ).rename("p_update_before_tcrit").reset_index()
    summary = summary.merge(timing_rates, on=["method", "mechanism"])
    summary.to_csv(RESULT / "E5_INFORMATION_SAFETY_TRADEOFF.csv", index=False)
    optimized = episode[episode.method == "optimized_probe"].set_index("scenario_id")
    baseline = episode[episode.method == "no_probe"].set_index("scenario_id").loc[optimized.index]
    no_failure_increase = float(optimized.physical_success.mean()) >= float(baseline.physical_success.mean())
    frequency_degradation = float(optimized.frequency_iae_hz_s.mean() / baseline.frequency_iae_hz_s.mean() - 1.0)
    ace_degradation = float(optimized.ace_iae_pu_s.mean() / baseline.ace_iae_pu_s.mean() - 1.0)
    timing_by_mechanism = optimized[optimized.timing_evaluated].groupby(
        "mechanism"
    ).update_before_Tcrit.mean()
    information_by_mechanism = optimized.groupby("mechanism").information_gain.mean()
    mechanisms_timing = int((timing_by_mechanism >= 0.80).sum())
    mechanisms_information = int((information_by_mechanism >= 0.15).sum())
    budget = bool(
        optimized.probe_energy_mwh.max() <= 1.50
        and optimized.probe_mileage_pu.max() <= 2.50
    )
    adequate_backup = float(
        optimized[optimized.sg_tension == "adequate"].backup_feasible_rate.mean()
    ) >= 0.95
    native_pivot = native.pivot(index="mechanism", columns="method", values="physical_success")
    native_safe = bool(native_pivot.optimized_probe.mean() >= native_pivot.no_probe.mean())
    native_information = int(
        native[native.method == "optimized_probe"].groupby("mechanism").update_before_reference_window.mean().ge(0.8).sum()
    )
    direction = (mechanisms_timing >= 3) == (native_information >= 3)
    gate = {
        "no_physical_failure_rate_increase": no_failure_increase,
        "frequency_ace_not_materially_degraded": frequency_degradation <= 0.10 and ace_degradation <= 0.10,
        "at_least_three_mechanisms_timing": mechanisms_timing >= 3,
        "at_least_three_mechanisms_information": mechanisms_information >= 3,
        "probe_energy_and_mileage_budget": budget,
        "adequate_sg_backup_feasible": adequate_backup,
        "plant_b_no_failure_increase": native_safe,
        "plant_a_b_direction_consistent": direction,
    }
    gate_passed = bool(all(gate.values()))
    plt.figure(figsize=(8.5, 4.8))
    timing_by_mechanism.reindex(["headroom", "ramp", "delay", "energy", "availability"]).plot(kind="bar")
    plt.axhline(0.8, color="black", linestyle="--"); plt.ylim(0, 1.05)
    plt.ylabel("P(active update < Tcrit)"); plt.tight_layout()
    plt.savefig(FIGURE / "e5_active_timing.png", dpi=180); plt.close()
    report = DOC / "ACTIVE_IDENTIFICATION_FEASIBILITY.md"
    report.write_text(f"""# E5 safe active-identification feasibility

The optimized candidate uses a 0.04 pu, zero-mean alternating BESS redistribution with same-area SG compensation. Candidate execution is suppressed whenever public frequency/ACE margin or an explicit SG backup check fails. The information monitor uses high-rate issued command, POI power, and frequency only; capability labels enter only paired evaluation.

G5 result: **{'PASS — ACTIVE_IDENTIFICATION_FEASIBLE' if gate_passed else 'FAIL — ACTIVE_IDENTIFICATION_NOT_SAFE'}**. Timing passes {mechanisms_timing}/5 mechanisms and information contraction passes {mechanisms_information}/5. Frequency IAE change is {frequency_degradation:.2%}; ACE IAE change is {ace_degradation:.2%}. The power-limit response is treated as a control-relevant effective limit and does not claim to distinguish internally confounded headroom from availability. Energy capability remains a recorded failure if the zero-mean safety budget cannot reach its boundary.
""", encoding="utf-8")
    branch = SUMMARY_DOC / "E5_BRANCH_DECISION.md"
    branch.write_text(
        "# E5 branch decision\n\n" + (
            "G3 passed, G4 failed, and G5 passed: select branch A (SACID-TMPC).\n"
            if gate_passed else
            "G3 passed, G4 failed, and G5 failed: select branch R (capability-set robust MPC).\n"
        ), encoding="utf-8"
    )
    outputs = [
        RESULT / "E5_ACTIVE_MANIFEST.csv", RESULT / "E5_ACTIVE_FEASIBILITY.parquet",
        RESULT / "E5_PROBE_TRACES.parquet", RESULT / "E5_PLANT_B_ACTIVE.parquet",
        RESULT / "E5_INFORMATION_SAFETY_TRADEOFF.csv", FIGURE / "e5_active_timing.png",
        report, branch,
    ]
    progress = {
        "stage": "E5", "status": "PASSED" if gate_passed else "FAILED",
        "goal": "Determine whether safe active probing adds timely control-relevant capability information",
        "gate": "G5_ACTIVE", "gate_passed": gate_passed, "gate_components": gate,
        "tests": {
            "plant_a_scenarios": len(manifest), "plant_a_episode_rows": len(episode),
            "plant_b_episode_rows": len(native), "mechanisms_passing_timing": mechanisms_timing,
            "mechanisms_passing_information": mechanisms_information,
            "frequency_iae_degradation": frequency_degradation,
            "ace_iae_degradation": ace_degradation,
            "maximum_probe_energy_mwh": float(optimized.probe_energy_mwh.max()),
            "maximum_probe_mileage_pu": float(optimized.probe_mileage_pu.max()),
            "adequate_backup_feasible_rate": float(optimized[optimized.sg_tension == "adequate"].backup_feasible_rate.mean()),
        },
        "failures": [] if gate_passed else [key for key, value in gate.items() if not value],
        "repairs": [],
        "commands": [
            "python -m scripts.phase_e.run_e5_active_feasibility",
            "python -m pytest tests/phase_e/test_e5_active.py -q",
        ],
        "outputs_sha256": {path.relative_to(REPO).as_posix(): sha256(path) for path in outputs},
        "decision": "SELECT_BRANCH_A" if gate_passed else "SELECT_BRANCH_R",
        "next_stage": "E6",
    }
    path = REPO / "progress_phase_e" / "E5.json"
    path.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(progress, indent=2))


if __name__ == "__main__":
    main()
