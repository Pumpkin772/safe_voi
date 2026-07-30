# Codex Master Goal — 方向1 Phase D

你必须在当前真实仓库中一次性完成方向1 Phase D，严格按照本目录全部规范执行。不要在D0–D9内部阶段之间等待用户重新发送Goal。

## 总目标

撤回当前Phase C中因Plant B功率平衡错误、非因果C5、虚假MPC命名和混杂实验形成的结论，保留可用工程基础；随后从物理模型、因果能力集合估计、真实基线、滚动Oracle、管束MPC理论和完整实验五个层面，完成：

> **CRCS-TMPC：面向黑箱IBR未通知能力变化的控制相关能力集合自适应管束模型预测多区域二次频率控制。**

## 执行顺序

严格连续执行：

```text
D0 → D1 → D2 → D3 → D4 → D5 → D6 → D7 → D8 → D9
```

每阶段必须写 `progress_phase_d/Dx.json`，包含输入哈希、命令、结果、Gate、失败、修复和输出哈希。

## 强制要求

1. 从本阶段起项目统一命名为“方向1”或`DIRECTION1`；旧D5命名只在历史路径中保留。
2. `proposed_set_adaptive_mpc`停止作为论文方法；不得简单调旧阈值。
3. Plant B必须真正耦合BESS有功与原生多机网络/摆动方程；单独运行ANDES不算交叉验证。
4. 所有称为MPC的方法必须有预测模型、时域、优化变量、目标和约束。
5. Causal detector不得使用中心窗口、未来窗口或真实变化时刻。
6. 部署方法不得读取true load、true capability、true SoC、hidden state、future event或Oracle。
7. 所有部署方法共享同一公共测量和未知负荷估计器。
8. final场景因素必须显式独立，不得由seed取模混合编码。
9. final运行后禁止改算法、权重、阈值、场景和统计方法。
10. 失败不得删除；not_evaluated不得记为科学失败。
11. 不得通过扩大安全阈值、增强SG、减小扰动或隐藏失败制造优势。
12. 只实现CRCS-TMPC这一条最终方法；若其科学假设失败，保存负结果并停止，不换新算法。

## 阶段合同

每个阶段的目标、输入、任务、文件、实验、成功/失败判据、自动处理和衔接，均以：

- `01_MASTER_EXECUTION_PLAN.md`
- `09_GATES_FAILURE_AUTO_REPAIR.md`

为唯一权威。

物理模型以 `03_CORRECTED_PLANT_MODELS.md` 为准；方法以 `04_METHOD_SPEC_CRCS_TUBE_MPC.md` 为准；理论以 `05_THEORY_AND_PROOFS_SPEC.md` 为准；实验以 `07_EXPERIMENT_AND_STATISTICS_PROTOCOL.md` 为准。

## 允许的提前停止

只有以下情况可以提前停止方法开发：

- `SOURCE_BASELINE_INCOMPLETE`
- `NOVELTY_NOT_SUPPORTED`
- `NATIVE_MODEL_NOT_VALIDATED`
- `PASSIVE_CAPABILITY_SET_NOT_SUPPORTED`
- `PROBLEM_NOT_MATERIAL`
- `ROBUST_CONTROL_NOT_FEASIBLE`

即使提前停止，也必须继续生成D9格式的完整负结果审查包，并保存所有代码、证据和失败原因。

## 最终输出

生成：

```text
DIRECTION1_PHASE_D_CRCS_TUBE_MPC_SINGLE_REVIEW_PACKAGE.zip
```

必须小于512MB，并严格满足 `10_FINAL_REVIEW_PACKAGE_SPEC.md`。

完成后在终端和 `14_FINAL_STATUS/FINAL_RESEARCH_STATUS.md` 报告：

- ZIP绝对路径、大小和SHA256；
- Git commit/branch/status；
- D0–D9 Gate；
- H1–H4结果；
- Oracle材料性；
- 能力集合覆盖和因果更新时间；
- 最佳部署基线；
- CRCS-TMPC known/OOD结果；
- 最严重限制；
- 最终状态：
  - `METHOD_SUPPORTED_FOR_MANUSCRIPT`
  - `METHOD_NOT_SUPPORTED_BY_EVIDENCE`
  - 或上述致命停止状态之一。
