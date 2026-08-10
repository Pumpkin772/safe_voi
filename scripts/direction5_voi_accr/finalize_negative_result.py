"""Lock and summarize the decisive negative Direction5 VOI-ACCR result."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
M2 = REPO / "results_direction5_voi_accr" / "M2"
FINAL = REPO / "results_direction5_voi_accr" / "final"
FIGURES = REPO / "research_outputs_direction5_voi_accr" / "figures"
PAPER = REPO / "research_outputs_direction5_voi_accr" / "paper"
FAILURES = REPO / "research_outputs_direction5_voi_accr" / "failures"
RESEARCH = REPO / "research" / "direction5_voi_accr_mpc_result_driven"
HORIZON = REPO / "research_outputs_working" / "ORACLE_HORIZON_SCREEN"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _ratio(group: pd.DataFrame, metric: str, method: str) -> float:
    baseline_name = f"{metric}__contract_only_recourse_mpc"
    candidate_name = f"{metric}__{method}"
    balanced = group.assign(_numerator=group[baseline_name] - group[candidate_name]).groupby("design_cell")[["_numerator", baseline_name]].mean()
    baseline = float(balanced[baseline_name].mean())
    return float(balanced["_numerator"].mean() / baseline) if baseline else float("nan")


def _factor_summary(paired: pd.DataFrame) -> pd.DataFrame:
    high = paired.loc[paired["probe_worthwhile_preregistered"].astype(bool)].copy()
    records: list[dict] = []
    for factor in ("plant", "condition", "mechanism", "timing_relation", "period_s", "sg_tension"):
        for level, group in high.groupby(factor, dropna=False):
            records.append(
                {
                    "factor": factor,
                    "level": level,
                    "scenarios": len(group),
                    "probed_scenarios": int((group["voi_probe_triggers__voi_accr_mpc"] > 0).sum()),
                    "voi_ace_improvement": _ratio(group, "ace_iae_pu_s", "voi_accr_mpc"),
                    "voi_tie_improvement": _ratio(group, "tie_iae_pu_s", "voi_accr_mpc"),
                    "oracle_ace_improvement": _ratio(group, "ace_iae_pu_s", "perfect_capability_recourse_oracle"),
                    "oracle_tie_improvement": _ratio(group, "tie_iae_pu_s", "perfect_capability_recourse_oracle"),
                }
            )
    return pd.DataFrame.from_records(records)


def _aggregate_summary(paired: pd.DataFrame) -> pd.DataFrame:
    high = paired.loc[paired["probe_worthwhile_preregistered"].astype(bool)].copy()
    actual = high.loc[high["voi_probe_triggers__voi_accr_mpc"] > 0].copy()
    low = paired.loc[~paired["probe_worthwhile_preregistered"].astype(bool)].copy()
    records: list[dict] = []
    for name, group in (("ALL", paired), ("PREREGISTERED_WORTHWHILE", high), ("ACTUALLY_PROBED", actual), ("NOT_WORTHWHILE", low)):
        record: dict[str, object] = {
            "subset": name,
            "scenarios": len(group),
            "probed_scenarios": int((group["voi_probe_triggers__voi_accr_mpc"] > 0).sum()),
            "probe_trigger_rate": float((group["voi_probe_triggers__voi_accr_mpc"] > 0).mean()),
            "probe_command_l1_pu_s_total": float(group["probe_command_l1_pu_s__voi_accr_mpc"].sum()),
            "candidate_diameter_reduction_mean": float(group["candidate_diameter_reduction_max__voi_accr_mpc"].mean()),
        }
        for metric in ("ace_iae_pu_s", "tie_iae_pu_s", "sg_mechanical_mileage_pu"):
            record[f"voi_{metric}_improvement"] = _ratio(group, metric, "voi_accr_mpc")
            record[f"oracle_{metric}_improvement"] = _ratio(group, metric, "perfect_capability_recourse_oracle")
        records.append(record)
    return pd.DataFrame.from_records(records)


def _make_plots(factors: pd.DataFrame, horizon: pd.DataFrame) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    x = np.arange(len(horizon))
    ax.bar(x - 0.18, 100 * horizon["oracle_ace_iae_pu_s_aggregate_improvement"], 0.36, label="ACE IAE")
    ax.bar(x + 0.18, 100 * horizon["oracle_tie_iae_pu_s_aggregate_improvement"], 0.36, label="Tie-line IAE")
    ax.axhline(4.0, color="crimson", linestyle="--", linewidth=1.5, label="Registered 4% gate")
    ax.set_xticks(x, [f"H={int(v)}" for v in horizon["horizon_steps"]])
    ax.set_ylabel("Perfect-information aggregate improvement (%)")
    ax.set_title("Oracle materiality ceiling remains below the registered gate")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIGURES / "oracle_horizon_materiality_ceiling.png", dpi=180)
    plt.close(fig)

    plant = factors.loc[factors["factor"] == "plant"].copy()
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    x = np.arange(len(plant))
    ax.bar(x - 0.18, 100 * plant["voi_ace_improvement"], 0.36, label="VOI ACE")
    ax.bar(x + 0.18, 100 * plant["voi_tie_improvement"], 0.36, label="VOI tie-line")
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.axhline(4.0, color="crimson", linestyle="--", linewidth=1.2, label="Registered 4% gate")
    ax.set_xticks(x, plant["level"], rotation=10)
    ax.set_ylabel("Scenario-balanced improvement (%)")
    ax.set_title("M2 worthwhile-subset result by physical plant")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIGURES / "m2_cross_plant_value.png", dpi=180)
    plt.close(fig)

    gates = pd.read_csv(FINAL / "ALL_GATES.csv")
    gate_order = gates.loc[gates["milestone"] == "M2"].copy()
    colors = gate_order["status"].map(
        {"PASS": "#2b8c6b", "FAIL": "#c73e3a", "INVALIDATED": "#d58b2b", "NOT_EVALUATED": "#888888"}
    )
    fig, ax = plt.subplots(figsize=(9.0, 5.8))
    y = np.arange(len(gate_order))
    ax.barh(y, np.ones(len(y)), color=colors)
    ax.set_yticks(y, gate_order["gate"])
    ax.set_xticks([])
    ax.set_xlim(0, 1)
    ax.invert_yaxis()
    ax.set_title("Independent M2 validation gates")
    for index, status in enumerate(gate_order["status"]):
        ax.text(0.5, index, status, ha="center", va="center", color="white", fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIGURES / "m2_gate_outcomes.png", dpi=180)
    plt.close(fig)


def main() -> None:
    FINAL.mkdir(parents=True, exist_ok=True)
    PAPER.mkdir(parents=True, exist_ok=True)
    FAILURES.mkdir(parents=True, exist_ok=True)

    paired = pd.read_csv(M2 / "M2_PAIRED.csv")
    episodes = pd.read_csv(M2 / "M2_EPISODES.csv")
    normal = pd.read_csv(M2 / "M2_NORMAL1H_EPISODES.csv")
    contract_violation = pd.read_csv(M2 / "M2_CONTRACT_VIOLATION_EPISODES.csv")
    m2_decision = _json(M2 / "M2_DECISION.json")
    horizon = pd.read_csv(HORIZON / "SUMMARY.csv")
    horizon_decision = _json(HORIZON / "DECISION.json")
    factor = _factor_summary(paired)
    aggregate = _aggregate_summary(paired)
    factor.to_csv(FINAL / "M2_FACTOR_SUMMARY.csv", index=False)
    aggregate.to_csv(FINAL / "M2_AGGREGATE_SUMMARY.csv", index=False)

    high = paired.loc[paired["probe_worthwhile_preregistered"].astype(bool)]
    actual = high.loc[high["voi_probe_triggers__voi_accr_mpc"] > 0]
    low = paired.loc[~paired["probe_worthwhile_preregistered"].astype(bool)]
    native = episodes.loc[episodes["plant"] == "B_native_ANDES_Kundur"]
    cert_audit = pd.read_csv(M2 / "M2_CERTIFICATE_AUDIT.csv")
    false_optimism = int((cert_audit["false_optimism"].astype(str).str.lower() == "true").sum())

    m2_gates = [
        (name, "PASS" if passed else "FAIL") for name, passed in m2_decision["gates"].items()
    ]
    gate_rows = [
        {"milestone": "M1", "gate": "integrated_positive_prototype", "status": "PASS", "basis": "8 Plant-A development scenarios; development-only evidence"},
        {"milestone": "M2", "gate": "v1_baseline_fairness", "status": "INVALIDATED", "basis": "baseline-class mismatch; all rows preserved"},
    ]
    gate_rows.extend(
        {"milestone": "M2", "gate": gate, "status": status, "basis": "M2 V2 independent validation"}
        for gate, status in m2_gates
    )
    gate_rows.extend(
        [
            {"milestone": "M2", "gate": "post_m2_development_repair_r1", "status": "FAIL", "basis": "change-detection guard abstained in all 16 scenarios"},
            {"milestone": "M2", "gate": "post_m2_development_repair_r2", "status": "FAIL", "basis": "four independent development candidates; no registered positive prototype"},
            {"milestone": "M2", "gate": "oracle_horizon_materiality", "status": "FAIL", "basis": "perfect capability below 4% aggregate gate for horizons 3, 4, and 6"},
            {"milestone": "Final", "gate": "final_seed_execution", "status": "NOT_EVALUATED", "basis": "M2 did not pass; seeds 6200-6299 unconsumed"},
            {"milestone": "Final", "gate": "terminal_archive", "status": "PASS", "basis": "decisive negative evidence retained"},
        ]
    )
    pd.DataFrame(gate_rows).to_csv(FINAL / "ALL_GATES.csv", index=False)

    failure_rows = [
        {
            "id": "F-001",
            "severity": "DECISIVE",
            "stage": "M2",
            "classification": "METHOD_VALUE_NOT_VALIDATED",
            "evidence": "Worthwhile subset ACE -0.0163%, tie -0.0526%; confidence intervals include zero",
            "disposition": "FAIL",
        },
        {
            "id": "F-002",
            "severity": "MAJOR",
            "stage": "M2",
            "classification": "CERTIFICATE_FALSE_OPTIMISM",
            "evidence": f"{false_optimism}/{len(cert_audit)} audited certificate issues were false optimistic",
            "disposition": "FAIL",
        },
        {
            "id": "F-003",
            "severity": "MAJOR",
            "stage": "M2",
            "classification": "NATIVE_PLANT_B_NO_PROBE_ACTIVATION",
            "evidence": f"0/{int((high['plant'] == 'B_native_ANDES_Kundur').sum())} preregistered worthwhile native Plant-B scenarios triggered a probe",
            "disposition": "FAIL",
        },
        {
            "id": "F-004",
            "severity": "DECISIVE",
            "stage": "POST_M2_DEVELOPMENT",
            "classification": "ORACLE_MATERIALITY_CEILING_BELOW_GATE",
            "evidence": "Best screened aggregate Oracle value: tie 1.7685%, ACE 0.2947%; registered gate 4%",
            "disposition": "STOP",
        },
    ]
    pd.DataFrame(failure_rows).to_csv(FINAL / "FAILURE_LEDGER.csv", index=False)

    final_status = {
        "project": "DIRECTION5",
        "method": "VOI-ACCR-MPC",
        "final_status": "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE",
        "m1": "PASS_DEVELOPMENT_ONLY",
        "m2": "FAIL",
        "final": "NOT_EVALUATED",
        "m2_v1": "INVALIDATED_BASELINE_CLASS_MISMATCH",
        "m2_v2": "VALID_FAIL",
        "selected_probe_policy": "VOI_V12_C13_M1_VALUE_REGIONS (development only; not validated for deployment)",
        "probe_sequence": [1.0, -1.0],
        "probe_amplitude_pu": 0.0025,
        "probe_trigger_rate_all": float((paired["voi_probe_triggers__voi_accr_mpc"] > 0).mean()),
        "probe_trigger_rate_worthwhile": float((high["voi_probe_triggers__voi_accr_mpc"] > 0).mean()),
        "probe_trigger_rate_not_worthwhile": float((low["voi_probe_triggers__voi_accr_mpc"] > 0).mean()),
        "actual_probed_scenarios": len(actual),
        "candidate_diameter_reduction_actual_probed": float(actual["candidate_diameter_reduction_max__voi_accr_mpc"].mean()),
        "probe_command_l1_pu_s_total_actual_probed": float(actual["probe_command_l1_pu_s__voi_accr_mpc"].sum()),
        "m2_worthwhile_ace_improvement": _ratio(high, "ace_iae_pu_s", "voi_accr_mpc"),
        "m2_worthwhile_tie_improvement": _ratio(high, "tie_iae_pu_s", "voi_accr_mpc"),
        "m2_worthwhile_sg_mileage_improvement": _ratio(high, "sg_mechanical_mileage_pu", "voi_accr_mpc"),
        "m2_oracle_ace_improvement": _ratio(high, "ace_iae_pu_s", "perfect_capability_recourse_oracle"),
        "m2_oracle_tie_improvement": _ratio(high, "tie_iae_pu_s", "perfect_capability_recourse_oracle"),
        "scenario_count": len(paired),
        "plant_a_scenarios": int((paired["plant"] == "A_full_nonlinear").sum()),
        "plant_b_scenarios": int((paired["plant"] == "B_native_ANDES_Kundur").sum()),
        "native_plant_b_method_rows": len(native),
        "native_plant_b_all_converged": bool(native["native_converged"].fillna(False).astype(bool).all()),
        "known_scenarios": int((paired["condition"] == "known").sum()),
        "ood_scenarios": int((paired["condition"] == "OOD").sum()),
        "normal1h_method_rows": len(normal),
        "normal1h_real_simulation": bool((normal["duration_s"] == 3600.0).all()),
        "normal1h_hard_violations": int(normal["hard_violation"].astype(bool).sum()),
        "normal1h_max_frequency_peak_hz": float(normal["frequency_peak_hz"].max()),
        "contract_violation_method_rows": len(contract_violation),
        "contract_violation_hard_violations": int(contract_violation["hard_violation"].astype(bool).sum()),
        "attempted_optimization_calls": int(episodes["attempted_optimization_calls"].sum()),
        "voi_attempted_optimization_calls": int(episodes.loc[episodes["method"] == "voi_accr_mpc", "attempted_optimization_calls"].sum()),
        "solver_failure_calls": int(episodes["solver_failure_calls"].sum()),
        "restoration_calls": int(episodes["restoration_calls"].sum()),
        "fallback_calls": int(episodes["fallback_calls"].sum()),
        "false_optimistic_certificates": false_optimism,
        "audited_certificate_issues": len(cert_audit),
        "theory_certificate": "CONDITIONAL_PROBE_SAFETY_ONLY; ONLINE CAPABILITY CERTIFICATE NOT VALIDATED",
        "oracle_horizon_screen": horizon_decision["status"],
        "final_seed_range": "6200-6299",
        "final_seeds_consumed": False,
        "most_severe_limitation": "The available perfect-capability control value is below the registered 4% aggregate materiality gate, while causal probing adds cost and fails cross-plant validation.",
    }
    _write_json(FINAL / "FINAL_STATUS.json", final_status)
    _write_json(
        FINAL / "FINAL_SEED_AUDIT.json",
        {"registered_final_seed_range": [6200, 6299], "consumed": False, "reason": "M2_FAIL"},
    )

    status_table = pd.DataFrame(
        [
            {"milestone": "M1", "status": "PASS_DEVELOPMENT_ONLY", "seeds": "development", "claim": "nonempty integrated positive prototype on 8 Plant-A scenarios"},
            {"milestone": "M2", "status": "FAIL", "seeds": "5300-5399", "claim": "independent Plant-A/native-Plant-B validation did not support paper gates"},
            {"milestone": "Final", "status": "NOT_EVALUATED", "seeds": "6200-6299 unconsumed", "claim": "no final performance claim"},
        ]
    )
    status_table.to_csv(FINAL / "MILESTONE_STATUS.csv", index=False)

    report = f"""# Direction5 VOI-ACCR-MPC final research decision

## Locked decision

`DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE`

M1 passed only as a development prototype. The fair independent M2 V2 validation failed six registered gates. Two new-seed development repair searches did not restore a positive prototype. Finally, a perfect-capability Oracle screen at MPC horizons 3, 4, and 6 found no aggregate ACE or tie-line improvement reaching the registered 4% materiality gate. Final seeds 6200--6299 were therefore not run.

## Evidence

- M2: {len(paired)} paired scenarios ({int((paired['plant'] == 'A_full_nonlinear').sum())} full nonlinear Plant A, {int((paired['plant'] == 'B_native_ANDES_Kundur').sum())} native ANDES Plant B).
- Preregistered worthwhile subset: {len(high)} scenarios; {len(actual)} actually probed.
- VOI improvement on that subset: ACE {100 * _ratio(high, 'ace_iae_pu_s', 'voi_accr_mpc'):.4f}%, tie-line {100 * _ratio(high, 'tie_iae_pu_s', 'voi_accr_mpc'):.4f}%.
- Oracle improvement on that subset: ACE {100 * _ratio(high, 'ace_iae_pu_s', 'perfect_capability_recourse_oracle'):.4f}%, tie-line {100 * _ratio(high, 'tie_iae_pu_s', 'perfect_capability_recourse_oracle'):.4f}%.
- Probe trigger rate: {100 * (paired['voi_probe_triggers__voi_accr_mpc'] > 0).mean():.1f}% overall, {100 * (high['voi_probe_triggers__voi_accr_mpc'] > 0).mean():.1f}% in the worthwhile subset, and 0% in not-worthwhile controls.
- Actual-probe candidate diameter reduction: {100 * actual['candidate_diameter_reduction_max__voi_accr_mpc'].mean():.2f}%; cumulative allocation-probe L1 cost: {actual['probe_command_l1_pu_s__voi_accr_mpc'].sum():.3f} pu-s.
- Certificate audit: {false_optimism}/{len(cert_audit)} false optimistic issues.
- Solver accounting: {int(episodes.loc[episodes['method'] == 'voi_accr_mpc', 'attempted_optimization_calls'].sum())} VOI-method attempted calls and {int(episodes['attempted_optimization_calls'].sum())} attempted calls across all three core methods; {int(episodes['solver_failure_calls'].sum())} solver failures, {int(episodes['restoration_calls'].sum())} restorations, and {int(episodes['fallback_calls'].sum())} fallbacks.
- Genuine normal1h: {len(normal)} method rows, 3600 s each, zero hard violations, maximum frequency peak {normal['frequency_peak_hz'].max():.6f} Hz.

## Claim boundary

The evidence supports safe abstention in low-value scenarios and a nonempty development-only probing region. It does not support a deployable cross-plant performance claim, a validated online capability certificate, positive Oracle-value recovery, or a final-seed result. The negative conclusion is bounded to the registered Direction5 plants, uncertainty mechanisms, controller family, physical limits, scenario ranges, and 4% paper-level materiality gate.
"""
    (RESEARCH / "FINAL_RESEARCH_DECISION.md").write_text(report, encoding="utf-8")
    (FAILURES / "DECISIVE_NEGATIVE_EVIDENCE.md").write_text(report, encoding="utf-8")

    manuscript = f"""# Value boundaries of information-gated active capability certification for black-box IBRs in multi-area frequency control

## Abstract

This study asks whether active certification of hidden inverter-based-resource power, ramp, and delay capability has positive net control value in multi-area secondary frequency control. We formulate VOI-ACCR-MPC, which places a zero-mean SG--IBR allocation probe around the current contract-MPC optimum only when a causal decision-relevance and value-of-information gate predicts positive net value. In low-value conditions it exactly abstains and reduces to contract MPC. A development prototype passed on eight nonlinear Plant-A cases, but a locked independent validation on 48 full nonlinear Plant-A and 12 native ANDES Plant-B paired scenarios did not validate the performance claim. In the preregistered worthwhile subset, scenario-balanced VOI improvements were {100 * _ratio(high, 'ace_iae_pu_s', 'voi_accr_mpc'):.3f}% for ACE IAE and {100 * _ratio(high, 'tie_iae_pu_s', 'voi_accr_mpc'):.3f}% for tie-line IAE, with confidence intervals spanning zero. Native Plant B triggered no probes. A separate perfect-capability screen at horizons 3, 4, and 6 found a best aggregate value of only {100 * horizon['oracle_tie_iae_pu_s_aggregate_improvement'].max():.3f}% for tie-line IAE and {100 * horizon['oracle_ace_iae_pu_s_aggregate_improvement'].max():.3f}% for ACE IAE, below the preregistered 4% materiality threshold. We therefore report a bounded decisive negative result: safe selective probing has a nonempty development region, but its net cross-plant control value is insufficient under the registered problem.

## 1. Scientific question

The ordinary controller observes frequency, ACE, tie-line flow, issued commands, actual BESS point-of-interconnection power, and measured SoC. It does not read true capability, true load, hidden parameters, or future events. The question is not whether a probe can distinguish candidate models in isolation, but whether the information changes a constrained recourse decision enough to repay the closed-loop frequency, ACE, tie-line, synchronous-generator-mileage, and energy costs of probing.

## 2. Method

VOI-ACCR-MPC maintains causal power/ramp/delay candidate models and separates the guaranteed contract floor from a conditional online envelope. The base command is the contract-MPC optimum. A two-step zero-mean allocation perturbation of amplitude 0.0025 pu is considered only when multiple candidates imply materially different optimal actions and predicted recourse benefit exceeds probe cost. A missing certificate never triggers a probe. Certificates expire after 4 s, use cooldown and change reset, and cannot authorize delivery below the contract floor. The selected M1 horizon is three control steps.

## 3. Protocol

M1 used eight 300 s full nonlinear Plant-A development scenarios covering power/ramp uncertainty and low/high SG tension. M2 used independent seeds and 60 paired scenarios: 48 full nonlinear Plant A and 12 native ANDES Plant B, crossing power/ramp/delay, 2/4 s control, known/OOD, SG tension, event timing, and 300--600 s duration. Contract-only rolling MPC is the primary baseline and perfect-capability rolling recourse MPC is evaluation-only. Two genuine 3600 s normal profiles and four contract-violation design cells were evaluated separately. Statistics use scenario-balanced aggregate means, paired absolute differences, and the registered hierarchical bootstrap.

## 4. Results

### 4.1 Development

M1 found four worthwhile and four not-worthwhile Plant-A cases. Tie-line IAE improved 3.776%, ACE IAE improved 1.374%, candidate diameter fell 50%, hard violations and fallbacks were zero, and low-value controls had zero probes and exact baseline performance. This result was used only to lock a prototype.

### 4.2 Independent validation

The M2 worthwhile subset contained {len(high)} scenarios, of which {len(actual)} triggered probes. Aggregate ACE and tie-line improvements were {100 * _ratio(high, 'ace_iae_pu_s', 'voi_accr_mpc'):.4f}% and {100 * _ratio(high, 'tie_iae_pu_s', 'voi_accr_mpc'):.4f}%, respectively. SG mechanical mileage changed by {100 * _ratio(high, 'sg_mechanical_mileage_pu', 'voi_accr_mpc'):.4f}%. Mean diameter reduction over the preregistered worthwhile set was {100 * high['candidate_diameter_reduction_max__voi_accr_mpc'].mean():.2f}%, below the 50% Gate; over actually probed cases it was {100 * actual['candidate_diameter_reduction_max__voi_accr_mpc'].mean():.2f}%. Four of 21 audited certificate issues were false optimistic. Plant A had a best primary improvement of -0.0328%; Plant B had zero VOI change because no probe was triggered, so cross-plant positive direction failed.

Safety and numerical gates were not the bottleneck: all {int(episodes['attempted_optimization_calls'].sum())} attempted optimization calls are included in the denominator, with zero solver failures, restorations, or fallbacks and zero hard violations. Low-value controls had zero probes and exact metric equality. The real 3600 s normal profile had zero hard violations and a maximum frequency peak of {normal['frequency_peak_hz'].max():.6f} Hz.

### 4.3 Post-validation diagnosis

The false optimistic certificates occurred when the load event preceded an unannounced capability transition. A grid-cell outer certificate and change-detection gate eliminated optimism only by abstaining in every new development scenario. A second independent development search over validity and VoI margin retained safe abstention but did not recover registered benefit. Perfect-capability horizon screening then bounded the remaining explanation: tie-line value decreased from {100 * horizon.iloc[0]['oracle_tie_iae_pu_s_aggregate_improvement']:.3f}% at horizon 3 to {100 * horizon.iloc[-1]['oracle_tie_iae_pu_s_aggregate_improvement']:.3f}% at horizon 6, while ACE value remained below {100 * horizon['oracle_ace_iae_pu_s_aggregate_improvement'].max():.3f}%.

## 5. Interpretation

The negative result is not a generic impossibility theorem for active capability identification. It shows that, for the registered plants, contract, uncertainty range, physical disturbance family, and rolling MPC, the controllable value available even to perfect capability information is below the paper-level threshold. A causal probe can only recover a fraction of this ceiling and must additionally pay excitation cost. Consequently, more aggressive or repeated probes cannot establish the preregistered aggregate claim without changing the scientific problem or lowering the Gate.

## 6. Limitations and bounded claims

The sample is finite, only the registered full nonlinear Plant A and native ANDES Plant B are studied, and the Oracle screen covers horizons 3, 4, and 6 rather than arbitrary horizons. The certificate guarantee is conditional on the enumerated candidate set and probe guard; the online certificate did not pass empirical validity. Final seeds were deliberately not consumed because M2 failed. We claim only: (i) low-value abstention can be made contract-equivalent, (ii) safe active allocation probing has a development-only nonempty region, and (iii) the registered cross-plant net-control-value claim is not supported and is terminated with decisive negative evidence.

## 7. Reproducibility statement

The review archive contains source, environment, tests, all development searches including failures, both M2 attempts, raw control-cycle trajectories, locked summaries, figures, and fresh-extract replay scripts. No failed episode was removed and `NOT_EVALUATED` was not counted as success or failure.
"""
    (PAPER / "MANUSCRIPT.md").write_text(manuscript, encoding="utf-8")

    _make_plots(factor, horizon)
    print(json.dumps(final_status, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
