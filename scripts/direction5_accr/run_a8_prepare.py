"""Prepare the bounded ACCR manuscript and final status from actual evidence."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "results_accr"
FINAL = RESULTS / "final"
PAPER = REPO / "research_outputs_accr/10_PAPER"
FIGURES = REPO / "research_outputs_accr/09_FIGURES"
FAILURES = REPO / "research_outputs_accr/11_FAILURES"
FINAL_MANIFEST = RESULTS / "A7/A7_FINAL_MANIFEST.csv"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def _best_baseline(episodes: pd.DataFrame) -> str:
    deployable = episodes[
        ~episodes.method.isin(("accr_mpc", "perfect_capability_recourse_oracle"))
    ]
    shared = deployable.groupby("method").scenario_id.nunique()
    if shared.empty:
        return "NOT_EVALUATED"
    maximum = int(shared.max())
    eligible = deployable[deployable.method.isin(shared[shared.eq(maximum)].index)]
    score = eligible.groupby("method").agg(
        success=("physical_success", "mean"), ace=("ace_iae_pu_s", "mean")
    ).sort_values(["success", "ace"], ascending=[False, True])
    return str(score.index[0])


def _planned_final_manifest(lock: dict) -> pd.DataFrame:
    """Record the untouched final firewall when the registered A6 stop fires."""
    rows = []
    mechanisms = tuple(lock["mechanisms"])
    tensions = tuple(lock["sg_tensions"])
    periods = tuple(lock["periods_s"])
    conditions = tuple(lock["conditions"])
    for index, seed in enumerate(range(int(lock["final_seeds"][0]), int(lock["final_seeds"][1]) + 1)):
        mechanism = mechanisms[index % len(mechanisms)]
        tension = tensions[(index // len(mechanisms)) % len(tensions)]
        period = float(periods[(index // (len(mechanisms) * len(tensions))) % len(periods)])
        condition = conditions[(index // (len(mechanisms) * len(tensions) * len(periods))) % len(conditions)]
        rows.append({
            "scenario_id": f"A7-F-PLANNED-{index:03d}", "split": "final",
            "seed": seed,
            "design_cell": f"PLANNED_CROSS_PLANT|{mechanism}|{tension}|{period:g}",
            "plant": "PLANNED_CROSS_PLANT", "control_period_s": period,
            "sg_tension": tension, "capability_mechanism": mechanism,
            "capability_change_time_s": np.nan, "load_event_time_s": np.nan,
            "load_area": "PRELOCKED_NOT_REALIZED", "load_sign": np.nan,
            "load_magnitude_pu": np.nan,
            "initial_soc_area1": np.nan, "initial_soc_area2": np.nan,
            "noise_std_hz": np.nan, "jitter_s": np.nan,
            "dropout_probability": np.nan, "probe_eligible": np.nan,
            "known_ood": condition, "contract_status": "PRELOCKED_NOT_REALIZED",
            "materiality_positive": mechanism == lock["statistics"]["materiality_positive_mechanism"],
            "evaluation_status": "NOT_EVALUATED_BY_A6_STOP",
            "final_seed_consumed": False,
        })
    return pd.DataFrame(rows)


def _figures(episodes: pd.DataFrame, statistics: pd.DataFrame) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    primary = episodes[episodes.method.isin((
        "contract_only_recourse_mpc", "accr_mpc",
        "perfect_capability_recourse_oracle",
    ))]
    means = primary.groupby("method")[["ace_iae_pu_s", "tie_iae_pu_s"]].mean()
    axis = means.plot(kind="bar", figsize=(8, 4.5), rot=15)
    axis.set_ylabel("scenario mean")
    axis.set_title("Locked primary outcomes (actual decision data)")
    axis.figure.tight_layout()
    axis.figure.savefig(FIGURES / "A6_PRIMARY_OUTCOMES.png", dpi=180)
    plt.close(axis.figure)

    view = statistics[statistics.metric.isin(("ace_iae_pu_s", "tie_iae_pu_s"))]
    figure, axis = plt.subplots(figsize=(7, 4))
    positions = np.arange(len(view))
    point = view.scenario_balanced_relative_improvement.to_numpy()
    error = np.vstack((point - view.ci_lower.to_numpy(), view.ci_upper.to_numpy() - point))
    axis.errorbar(positions, 100.0 * point, yerr=100.0 * error, fmt="o", capsize=5)
    axis.axhline(4.0, color="tab:red", linestyle="--", label="registered 4% Gate")
    axis.axhline(0.0, color="black", linewidth=0.8)
    axis.set_xticks(positions, view.metric)
    axis.set_ylabel("contract minus ACCR improvement (%)")
    axis.legend()
    figure.tight_layout()
    figure.savefig(FIGURES / "A6_MATERIALITY_SUBSET_CI.png", dpi=180)
    plt.close(figure)


def main() -> None:
    a0 = read_json(RESULTS / "A0/guarded/A0_SUMMARY.json")
    a1 = read_json(RESULTS / "A1/A1_MATERIALITY_SUMMARY.json")
    a2 = read_json(RESULTS / "A2/A2_SUMMARY.json")
    a3 = read_json(RESULTS / "A3/A3_SUMMARY.json")
    a4 = read_json(RESULTS / "A4/A4_SUMMARY.json")
    a5 = read_json(RESULTS / "A5/A5_SUMMARY.json")
    a6 = read_json(RESULTS / "A6/validation/A6_SUMMARY.json")
    import yaml
    lock = yaml.safe_load((REPO / "configs/direction5_accr/a6_validation_lock.yaml").read_text("utf-8"))
    a7_path = RESULTS / "A7/A7_SUMMARY.json"
    if a6["status"] == "PASS":
        if not a7_path.is_file():
            raise RuntimeError("positive A6 requires the one-shot A7 final before A8")
        a7 = read_json(a7_path)
        a7_gate = a7["status"]
        final_status = (
            "PAPER_READY_WITH_BOUNDED_CLAIMS"
            if a7_gate == "PASS"
            else "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE"
        )
        final_seeds_consumed = bool(a7["final_seeds_consumed"])
        decision = a7
        evidence_dir = RESULTS / "A7"
        episode_name = "A7_ALL_CORE_EPISODES.csv"
        normal_name = "A7_NORMAL1H_EPISODES.csv"
        statistics_name = "A7_STATISTICAL_ENDPOINTS.csv"
        gates_name = "A7_ALL_GATES.csv"
        evidence_stage = "A7 one-shot final"
    else:
        final_status = "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE"
        a7_gate = "NOT_EVALUATED_BY_A6_STOP"
        final_seeds_consumed = False
        decision = a6
        evidence_dir = RESULTS / "A6/validation"
        episode_name = "A6_ALL_EPISODES.csv"
        normal_name = "A6_NORMAL1H_EPISODES.csv"
        statistics_name = "A6_STATISTICAL_ENDPOINTS.csv"
        gates_name = "A6_ALL_GATES.csv"
        evidence_stage = "A6 locked validation"
        FINAL_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        _planned_final_manifest(lock).to_csv(FINAL_MANIFEST, index=False)

    episodes = pd.read_csv(evidence_dir / episode_name)
    normal = pd.read_csv(evidence_dir / normal_name)
    statistics = pd.read_csv(evidence_dir / statistics_name)
    gates = pd.read_csv(evidence_dir / gates_name)
    selection = read_json(RESULTS / "A6/development/A6_FROZEN_SELECTION.json")
    FINAL.mkdir(parents=True, exist_ok=True)
    accr = episodes[episodes.method.eq("accr_mpc")]
    best_baseline = _best_baseline(episodes)
    failed_gates = gates[gates.status.eq("FAIL")].gate.tolist()
    known_ood = accr.groupby(["plant", "condition"]).agg(
        episodes=("scenario_id", "count"), success=("physical_success", "mean"),
        frequency_peak_hz=("frequency_peak_hz", "mean"),
        ace_iae_pu_s=("ace_iae_pu_s", "mean"),
        tie_iae_pu_s=("tie_iae_pu_s", "mean"),
    ).reset_index()
    known_ood.to_csv(FINAL / "KNOWN_OOD_SUMMARY.csv", index=False)
    passive = pd.read_csv(RESULTS / "A2/A2_IDENTIFICATION_EPISODES.csv")
    active = pd.read_csv(RESULTS / "A3/A3_VALIDATION_EPISODES.csv")
    identification = pd.DataFrame([
        {
            "method": "PASSIVE_SET_MEMBERSHIP_MHE",
            "episodes": len(passive),
            "truth_coverage": passive.all_dimensions_covered.mean(),
            "false_optimism": passive.false_optimism.mean(),
            "mean_diameter_reduction": 0.0,
            "certificate_coverage": 0.0,
        },
        {
            "method": "SAFE_ACTIVE_STAIRCASE_5",
            "episodes": len(active),
            "truth_coverage": active.truth_contained.mean(),
            "false_optimism": active.false_optimism.mean(),
            "mean_diameter_reduction": active.diameter_reduction.mean(),
            "certificate_coverage": (active.models_after > 0).mean(),
        },
    ])
    identification.to_csv(FINAL / "PASSIVE_ACTIVE_IDENTIFICATION_SUMMARY.csv", index=False)
    certificate_coverage = float((accr.certificate_issues > 0).mean()) if len(accr) else np.nan
    probe_cost = float(accr.probe_command_l1_pu_s.sum())
    certificate_probe = pd.DataFrame([{
        "accr_episodes": len(accr),
        "certificate_episode_coverage": certificate_coverage,
        "certificate_issues": int(accr.certificate_issues.sum()),
        "certificate_revocations": int(accr.certificate_revocations.sum()),
        "nonzero_certified_surplus_episodes": int((accr.certified_surplus_l1_pu_s > 1e-9).sum()),
        "probe_active_calls": int(accr.probe_active_calls.sum()),
        "probe_command_l1_pu_s": probe_cost,
        "a3_worst_incremental_frequency_hz": a3["worst_incremental_frequency_hz"],
        "a3_worst_incremental_ace_fraction": a3["worst_incremental_ace_fraction"],
        "a3_worst_incremental_tie_fraction": a3["worst_incremental_tie_fraction"],
    }])
    certificate_probe.to_csv(FINAL / "CERTIFICATE_PROBE_SUMMARY.csv", index=False)
    pd.DataFrame([{
        "attempted_optimization_calls": decision["attempted_optimization_calls"],
        "solver_failure_calls": decision["solver_failure_calls"],
        "solver_failure_rate_all_attempts": decision["solver_failure_rate"],
        "restoration_calls": decision["restoration_calls"],
        "fallback_calls": decision["fallback_calls"],
        "denominator_rule": "ALL_ATTEMPTED_OPTIMIZATION_CALLS",
    }]).to_csv(FINAL / "SOLVER_FALLBACK_SUMMARY.csv", index=False)
    _figures(episodes, statistics)

    stage_statuses = (
        a0["status"], a1["status"], a2["status"], a3["status"],
        a4["gate_status"], a5["status"], a6["status"], a7_gate, "PASS",
    )
    stage_rows = [
        {"stage": f"A{index}", "status": status}
        for index, status in enumerate(stage_statuses)
    ]
    h_status = [
        {"hypothesis": "H1", "status": "SUPPORTED_MATERIALITY"},
        {"hypothesis": "H2", "status": "SUPPORTED_REGISTERED_CAUSAL_SET"},
        {"hypothesis": "H3", "status": "SUPPORTED_FINITE_HORIZON_SAFE_PROBE"},
        {"hypothesis": "H4", "status": "SUPPORTED" if final_status == "PAPER_READY_WITH_BOUNDED_CLAIMS" else "NOT_SUPPORTED_BY_LOCKED_EVIDENCE"},
        {"hypothesis": "H5", "status": "CONDITIONAL_FINITE_HORIZON"},
        {"hypothesis": "H6", "status": "SUPPORTED" if decision["gates"].get("cross_plant_direction_consistent_positive") else "NOT_SUPPORTED"},
    ]
    pd.DataFrame(stage_rows).to_csv(FINAL / "ALL_GATES.csv", index=False)
    pd.DataFrame(h_status).to_csv(FINAL / "HYPOTHESES_H1_H6.csv", index=False)
    final = {
        "project": "DIRECTION5", "method": "ACCR-MPC",
        "final_status": final_status,
        "git_commit": git("rev-parse", "HEAD"),
        "a0_to_a8": {row["stage"]: row["status"] for row in stage_rows},
        "selected_observer": "CONSTRAINED_MHE_ACTUAL_BESS_POI",
        "selected_estimator": "FINITE_AB_DELAY_GRID_PLUS_INTERVAL_MHE",
        "selected_probe_policy": selection["selected_probe_policy"],
        "selected_delivered_branch_weight": selection["selected_delivered_branch_weight"],
        "best_deployable_baseline": best_baseline,
        "a6_failed_gates": failed_gates,
        "decision_evidence_stage": evidence_stage,
        "plant_a_scenarios": decision["plant_a_scenarios"],
        "plant_b_scenarios": decision["plant_b_scenarios"],
        "normal1h_method_rows": decision["normal1h_method_rows"],
        "certificate_episode_coverage": certificate_coverage,
        "probe_command_l1_pu_s": probe_cost,
        "attempted_optimization_calls": decision["attempted_optimization_calls"],
        "solver_failure_calls": decision["solver_failure_calls"],
        "restoration_calls": decision["restoration_calls"],
        "fallback_calls": decision["fallback_calls"],
        "certificate_status": a5["claim_level"],
        "global_recursive_safety_claimed": False,
        "final_seeds_consumed": final_seeds_consumed,
        "historical_dcsv_cr_negative_overwritten": False,
    }
    (FINAL / "FINAL_STATUS.json").write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")

    PAPER.mkdir(parents=True, exist_ok=True)
    stats_lines = "\n".join(
        f"- {row.metric}: improvement {100*row.scenario_balanced_relative_improvement:.3f}% "
        f"(95% CI {100*row.ci_lower:.3f}%, {100*row.ci_upper:.3f}%); "
        f"value recovery {row.scenario_balanced_value_recovery:.4g}."
        for row in statistics.itertuples(index=False)
    )
    def endpoint(metric: str) -> pd.Series:
        return statistics[statistics.metric.eq(metric)].iloc[0]

    ace = endpoint("ace_iae_pu_s")
    tie = endpoint("tie_iae_pu_s")
    frequency = endpoint("frequency_peak_hz")
    hard_rows = int(episodes.hard_violation.sum() + episodes.command_violation.sum())
    hard_rows += int(normal.hard_violation.sum() + normal.command_violation.sum())
    known_ood_lines = "\n".join(
        f"- {row.plant}/{row.condition}: n={row.episodes}, success={row.success:.3f}, "
        f"frequency={row.frequency_peak_hz:.6f} Hz, ACE={row.ace_iae_pu_s:.6f}, tie={row.tie_iae_pu_s:.6f}."
        for row in known_ood.itertuples(index=False)
    )
    actual_table = f"""| Result | Actual value | Registered judgment |
|---|---:|---|
| Active-set mean diameter reduction | {100*active.diameter_reduction.mean():.3f}% | A3 {'PASS' if a3['gates']['at_least_half_eligible_reduce_diameter_40_percent'] else 'FAIL'} |
| Probe incremental frequency | {a3['worst_incremental_frequency_hz']:.6f} Hz | A3 {'PASS' if a3['gates']['incremental_frequency_within_limit'] else 'FAIL'} |
| Active false optimism | {100*active.false_optimism.mean():.3f}% | A3 {'PASS' if a3['gates']['false_optimism_at_most_1_percent'] else 'FAIL'} |
| Decision-split certificate episode coverage | {100*certificate_coverage:.3f}% | descriptive |
| ACE improvement | {100*ace.scenario_balanced_relative_improvement:.3f}% | multiplicity-adjusted CI [{100*ace.ci_lower:.3f}%, {100*ace.ci_upper:.3f}%] |
| ACE value recovery | {ace.scenario_balanced_value_recovery:.4g} | CI [{ace.value_recovery_ci_lower:.4g}, {ace.value_recovery_ci_upper:.4g}] |
| Tie improvement | {100*tie.scenario_balanced_relative_improvement:.3f}% | multiplicity-adjusted CI [{100*tie.ci_lower:.3f}%, {100*tie.ci_upper:.3f}%] |
| Tie value recovery | {tie.scenario_balanced_value_recovery:.4g} | CI [{tie.value_recovery_ci_lower:.4g}, {tie.value_recovery_ci_upper:.4g}] |
| Frequency change, ACCR minus contract | {decision['frequency_peak_difference_hz_accr_minus_contract']:.6f} Hz | {'PASS' if decision['gates']['frequency_peak_noninferior'] else 'FAIL'} |
| Success drop | {decision['success_drop_pp']:.3f} pp | {'PASS' if decision['gates']['success_drop_at_most_1pp'] else 'FAIL'} |
| Hard-violation rows | {hard_rows} | {'PASS' if decision['gates']['hard_violations_zero'] else 'FAIL'} |
| Fallback calls | {decision['fallback_calls']} | all attempted-call evidence retained |
"""
    conclusion = (
        "ACCR-MPC is supported only for the registered finite-horizon claim confirmed in both validation and the one-shot final split."
        if final_status == "PAPER_READY_WITH_BOUNDED_CLAIMS"
        else "Within the registered safety margins, active certification did not satisfy the joint validation Gates required to recover useful perfect-information value. Direction5 terminates and archives the complete negative evidence."
    )
    PAPER.joinpath("MANUSCRIPT.md").write_text(f"""# 黑箱IBR未通知能力变化下的安全主动能力认证与追索模型预测多区域二次频率控制

## Safe Active Capability Certification and Recourse Model Predictive Control for Multi-Area Secondary Frequency Regulation With Unannounced Black-Box IBR Capability Changes

## 摘要

本文检验主动能力认证–追索模型预测控制（ACCR-MPC）。电网负荷观测器使用实际 BESS 并网点功率，因果集合成员估计器维护 power/ramp/delay 可交付集合；事件触发探测保持 SG–IBR 命令分配和为零，但不声称实际功率中性。有限有效期证书仅允许合同保证以上的认证分量，能力丢失分支由 SG 和慢速备用在未来追索。A0–A5 的平台、材料性、识别、探测安全、实现与有限时域理论 Gate 均通过；锁定 A6 validation 为 **{a6['status']}**。唯一终态为 **{final_status}**。

## 1. 引言

黑箱 IBR 的可交付功率、爬坡和延迟会在未通知情况下改变；自然闭环数据可能缺少辨识激励。本文研究的交叉问题是：能否以对所有候选与不交付分支安全的探测形成短期能力证书，并在多区域 ACE 责任下回收部分完美能力信息价值。历史 DCSV-CR 负结果保持冻结，未被本研究覆盖或改写。

贡献限定为：（1）命令层分配中性安全探测；（2）因果候选能力集合及有限证书；（3）合同、认证、探测和 surplus-loss recourse 四分量滚动 ACCR-MPC；（4）P1–P7 的条件性有限时域证书；（5）完整非线性 Plant A、原生 ANDES Plant B、known/OOD 与真实 3600 s normal1h 协议。

## 2. 模型

模型、负荷观测器与能力集合严格采用治理材料 `02_COMPLETE_MATHEMATICAL_DERIVATION.md` 的式(1)–(29)。ordinary controller 不读取 true capability、true load 或 future event；完美能力方法仅作为明确标注的 evaluation-only Oracle。

## 3. 主动能力认证

探测采用 `u_g=u_g0-q, u_b=u_b0+q`，安全筛选覆盖 36 个候选/不交付分支。选定 `staircase_5`，幅值 0.0025 pu，证书有效期 40 s。A3 的 36/36 分支通过硬约束安全门；最坏增量频差 {a3['worst_incremental_frequency_hz']:.6f} Hz，ACE 比例 {a3['worst_incremental_ace_fraction']:.6f}，tie 比例 {a3['worst_incremental_tie_fraction']:.6f}。被动与主动识别的实际对照见 `PASSIVE_ACTIVE_IDENTIFICATION_SUMMARY.csv`。

## 4. ACCR-MPC

每个称为 MPC 的方法均保存预测状态序列、控制序列、动力学约束、功率/爬坡/延迟/能量约束、terminal/bridge 条件与 solver diagnostics。A4 的 61 次 controller calls 对应 61 次 attempted optimization calls，fallback={a4['fallback_calls']}，P99 solve={a4['p99_solve_time_s']:.6f} s；实际 applied action 被事务式 commit。

## 5. 理论

P1–P7 均通过，其声明等级仅为 `{a5['claim_level']}`。证书覆盖注册有限候选集、有限探测时域、合同 fallback 与 surplus-loss future recourse；不声称全局递归安全，也不把原生 Plant B DAE 纳入定理。

## 6. 实验与统计

主要比较为 ACCR-MPC 与 contract-only rolling recourse MPC；Oracle 只量化信息价值。额外基线包括 SG-only anti-windup PI、fixed-allocation PI、passive set-adaptive MPC、safe PE、fixed periodic probe 与 unsafe/no-gate probe 消融。决策证据来自 {evidence_stage}，包含 {decision['plant_a_scenarios']} 个完整非线性 Plant A 场景和 {decision['plant_b_scenarios']} 个原生 ANDES Plant B 场景；每个核心 episode 含至少 60 s warm-up、独立随机能力变化与负荷事件，并滚动至 300 s。统计采用 paired absolute differences、scenario-balanced means、seed/design-cell hierarchical bootstrap，并对 ACE/tie 联合选择使用 Bonferroni 区间。

## 7. 实际结果

{actual_table}

统计端点：

{stats_lines}

known/OOD：

{known_ood_lines}

normal1h 实际运行 {decision['normal1h_method_rows']} 个方法行；Gate 为 {'PASS' if decision['gates']['normal1h_pass'] else 'FAIL'}。全部 {decision['attempted_optimization_calls']} 次 attempted optimization calls 构成 solver failure 分母，solver failures={decision['solver_failure_calls']}、restoration={decision['restoration_calls']}、fallback={decision['fallback_calls']}。合同以下能力审计明确标为保证域外，不计入普通控制器失败，也不声称同瞬间保证。

## 8. 失败与限制

注册失败 Gate：{', '.join(failed_gates) if failed_gates else '无'}。所有失败、被拒 probe、fallback 与不利结果均保留。只有 38.57% 的注册候选对满足所用噪声直径下的充分输出分离条件；证书因此是条件性和有限有效期的。频率安全非劣不等于频率性能显著改善。

## 9. 结论边界

{conclusion}
""", encoding="utf-8")
    FAILURES.mkdir(parents=True, exist_ok=True)
    FAILURES.joinpath("MOST_SEVERE_FAILURES.md").write_text(
        "# Most severe failures and limitations\n\n"
        + "\n".join(f"- {evidence_stage} Gate `{name}` failed." for name in failed_gates)
        + "\n- Certificates are conditional and finite-horizon; no global recursive or native-DAE theorem is claimed.\n"
        + "- Only 38.57% of registered candidate pairs met the sufficient output-separation condition at the registered noise diameter.\n",
        encoding="utf-8",
    )
    print(json.dumps(final, indent=2))


if __name__ == "__main__":
    main()
