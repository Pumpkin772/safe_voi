# 黑箱IBR未通知能力变化下的安全主动能力认证与追索模型预测多区域二次频率控制

## Safe Active Capability Certification and Recourse Model Predictive Control for Multi-Area Secondary Frequency Regulation With Unannounced Black-Box IBR Capability Changes

## 摘要

本文检验主动能力认证–追索模型预测控制（ACCR-MPC）。电网负荷观测器使用实际 BESS 并网点功率，因果集合成员估计器维护 power/ramp/delay 可交付集合；事件触发探测保持 SG–IBR 命令分配和为零，但不声称实际功率中性。有限有效期证书仅允许合同保证以上的认证分量，能力丢失分支由 SG 和慢速备用在未来追索。A0–A5 的平台、材料性、识别、探测安全、实现与有限时域理论 Gate 均通过；锁定 A6 validation 为 **FAIL**。唯一终态为 **DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE**。

## 1. 引言

黑箱 IBR 的可交付功率、爬坡和延迟会在未通知情况下改变；自然闭环数据可能缺少辨识激励。本文研究的交叉问题是：能否以对所有候选与不交付分支安全的探测形成短期能力证书，并在多区域 ACE 责任下回收部分完美能力信息价值。历史 DCSV-CR 负结果保持冻结，未被本研究覆盖或改写。

贡献限定为：（1）命令层分配中性安全探测；（2）因果候选能力集合及有限证书；（3）合同、认证、探测和 surplus-loss recourse 四分量滚动 ACCR-MPC；（4）P1–P7 的条件性有限时域证书；（5）完整非线性 Plant A、原生 ANDES Plant B、known/OOD 与真实 3600 s normal1h 协议。

## 2. 模型

模型、负荷观测器与能力集合严格采用治理材料 `02_COMPLETE_MATHEMATICAL_DERIVATION.md` 的式(1)–(29)。ordinary controller 不读取 true capability、true load 或 future event；完美能力方法仅作为明确标注的 evaluation-only Oracle。

## 3. 主动能力认证

探测采用 `u_g=u_g0-q, u_b=u_b0+q`，安全筛选覆盖 36 个候选/不交付分支。选定 `staircase_5`，幅值 0.0025 pu，证书有效期 40 s。A3 的 36/36 分支通过硬约束安全门；最坏增量频差 0.005516 Hz，ACE 比例 0.019500，tie 比例 0.005960。被动与主动识别的实际对照见 `PASSIVE_ACTIVE_IDENTIFICATION_SUMMARY.csv`。

## 4. ACCR-MPC

每个称为 MPC 的方法均保存预测状态序列、控制序列、动力学约束、功率/爬坡/延迟/能量约束、terminal/bridge 条件与 solver diagnostics。A4 的 61 次 controller calls 对应 61 次 attempted optimization calls，fallback=0，P99 solve=0.215262 s；实际 applied action 被事务式 commit。

## 5. 理论

P1–P7 均通过，其声明等级仅为 `CONDITIONAL_REGISTERED_SET_FINITE_HORIZON`。证书覆盖注册有限候选集、有限探测时域、合同 fallback 与 surplus-loss future recourse；不声称全局递归安全，也不把原生 Plant B DAE 纳入定理。

## 6. 实验与统计

主要比较为 ACCR-MPC 与 contract-only rolling recourse MPC；Oracle 只量化信息价值。额外基线包括 SG-only anti-windup PI、fixed-allocation PI、passive set-adaptive MPC、safe PE、fixed periodic probe 与 unsafe/no-gate probe 消融。决策证据来自 A6 locked validation，包含 16 个完整非线性 Plant A 场景和 4 个原生 ANDES Plant B 场景；每个核心 episode 含至少 60 s warm-up、独立随机能力变化与负荷事件，并滚动至 300 s。统计采用 paired absolute differences、scenario-balanced means、seed/design-cell hierarchical bootstrap，并对 ACE/tie 联合选择使用 Bonferroni 区间。

## 7. 实际结果

| Result | Actual value | Registered judgment |
|---|---:|---|
| Active-set mean diameter reduction | 63.286% | A3 PASS |
| Probe incremental frequency | 0.005516 Hz | A3 PASS |
| Active false optimism | 0.000% | A3 PASS |
| Decision-split certificate episode coverage | 80.000% | descriptive |
| ACE improvement | -31.310% | multiplicity-adjusted CI [-51.355%, -7.939%] |
| ACE value recovery | 0.00249 | CI [-0.0004301, 0.005411] |
| Tie improvement | -84.265% | multiplicity-adjusted CI [-206.822%, -16.104%] |
| Tie value recovery | -0.0003108 | CI [-0.0004531, -0.0001686] |
| Frequency change, ACCR minus contract | 0.003879 Hz | PASS |
| Success drop | 0.000 pp | PASS |
| Hard-violation rows | 0 | PASS |
| Fallback calls | 0 | all attempted-call evidence retained |


统计端点：

- ace_iae_pu_s: improvement -31.310% (95% CI -51.355%, -7.939%); value recovery 0.00249.
- tie_iae_pu_s: improvement -84.265% (95% CI -206.822%, -16.104%); value recovery -0.0003108.
- sg_mechanical_mileage_pu: improvement -82.267% (95% CI -132.204%, -29.274%); value recovery nan.
- frequency_peak_hz: improvement -0.002% (95% CI -0.008%, 0.003%); value recovery 0.3175.

known/OOD：

- A_full_nonlinear/OOD: n=8, success=1.000, frequency=0.236260 Hz, ACE=1.615503, tie=0.480423.
- A_full_nonlinear/known: n=8, success=1.000, frequency=0.237078 Hz, ACE=1.652289, tie=0.448457.
- B_native_ANDES_Kundur/OOD: n=2, success=1.000, frequency=0.050072 Hz, ACE=2.192543, tie=0.977965.
- B_native_ANDES_Kundur/known: n=2, success=1.000, frequency=0.050497 Hz, ACE=0.658305, tie=0.242997.

normal1h 实际运行 2 个方法行；Gate 为 PASS。全部 10428 次 attempted optimization calls 构成 solver failure 分母，solver failures=44、restoration=0、fallback=0。合同以下能力审计明确标为保证域外，不计入普通控制器失败，也不声称同瞬间保证。

## 8. 失败与限制

注册失败 Gate：ace_or_tie_improves_4pct_positive_ci, value_recovery_at_least_0p40_positive_ci, sg_mileage_not_worse, cross_plant_direction_consistent_positive。所有失败、被拒 probe、fallback 与不利结果均保留。只有 38.57% 的注册候选对满足所用噪声直径下的充分输出分离条件；证书因此是条件性和有限有效期的。频率安全非劣不等于频率性能显著改善。

## 9. 结论边界

Within the registered safety margins, active certification did not satisfy the joint validation Gates required to recover useful perfect-information value. Direction5 terminates and archives the complete negative evidence.
