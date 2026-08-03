# Codex 唯一总 Goal：方向5 Phase H DCSV-MPC

## 0. 命名强制规则

本项目从现在起统一称为：

```text
方向5 / DIRECTION5 / direction5
```

所有新建目录、Git 分支、配置、结果、图表、报告和最终 ZIP 必须使用该命名。历史文件中的其他名称只允许作为旧证据引用，不得继续沿用。


请在当前真实 Git 仓库中执行本 Goal。不要在内部阶段结束后等待用户再次发消息。

## 1. 先完整阅读

```text
research/direction5_phase_h_dcsv_mpc/
```

下全部文件。

以下文件具有约束性：

```text
01_MASTER_EXECUTION_PLAN.md
08_GATES_FAILURE_AUTO_REPAIR.md
10_FINAL_REVIEW_PACKAGE_SPEC.md
```

## 2. 唯一研究路线

项目名称保持：

```text
方向5 / DIRECTION5
```

唯一最终方法：

```text
DCSV-MPC
Disturbance–Capability-Separated Viability MPC
```

本轮不得：
- 更换科学问题；
- 回到真实模式标签分类；
- 临时加入AI/RL；
- 用阈值放宽掩盖终端失败；
- 继续沿用Phase G错误的G2负结论。

## 3. 连续执行

严格按：

```text
H0 → H1 → H2 → H3 → H4 → H5 → H6 → H7 → H8 → H9
```

连续执行。只有命中明确停止条件时才提前停止，但仍必须生成负结果审查包。

## 4. 必须完成的修正

1. 冻结Phase G并把最终状态改为：
   ```text
   TERMINAL_SET_CALIBRATION_PREMATURE_AND_MISSPECIFIED
   ```
2. 独立审计所有 near-terminal 窗口，检查：
   - saturation；
   - GRC；
   - valve/pm boundaries；
   - BESS limits；
   - fallback；
   - domain classification；
   - equilibrium distance。
3. 先完成 sustainable/bridge/infeasible 分类，再构造 terminal sets。
4. 电网负荷观测器必须把 actual BESS POI power 作为已知输入，不得用未建模delay/capability的command模型吸收能力失配。
5. 能力集合估计器独立处理 command-to-actual-power 通道。
6. 持续负荷误差必须作为增广参数/慢变状态处理，不得每周期重复为新负荷事故。
7. terminal window必须严格满足注册的全部物理条件和 no-future 条件。
8. coverage必须给出样本量和有限样本置信下界。
9. 实现真正的 DCSV-MPC：
   - sustainable terminal；
   - bridge viability；
   - infeasibility certificate；
   - power/ramp/delay/energy；
   - actual action commit；
   - feasibility restoration。
10. 所有叫MPC的基线必须真实求解滚动优化。
11. ordinary controller禁止读取true capability、true load、future event和future mode。
12. development/validation/final隔离；final后禁止调参。
13. 不删除失败、不放宽物理标准、不把not_evaluated伪装成失败或成功。
14. 下一审查包必须包含完整source snapshot，Phase H脚本不得依赖ZIP外部的Phase E/F文件。

## 5. 失败规则

按：

```text
代码 → 数值/求解器 → 参数来源 → 模型 → 估计器 → 方法 → 科学假设
```

诊断。

- 代码/数值可修复；
- 估计器最多两轮同框架修复；
- 方法最多两轮development/validation修复；
- 科学假设失败时停止并保存负结果；
- 禁止临时换算法。

## 6. 最终输出

生成：

```text
DIRECTION5_PHASE_H_DCSV_MPC_SINGLE_REVIEW_PACKAGE.zip
```

要求：

```text
size < 512MB
```

内容严格符合：

```text
research/direction5_phase_h_dcsv_mpc/10_FINAL_REVIEW_PACKAGE_SPEC.md
```

完成后报告：

- ZIP绝对路径；
- bytes/MB；
- SHA256；
- Git commit/status；
- H0–H9 Gate；
- H1–H6状态；
- selected observer/estimator；
- sustainable/bridge/infeasible统计；
- best deployable baseline；
- known/OOD结果；
- solver/restoration/fallback；
- theory certificate；
- Plant A/B；
-最严重失败和限制；
-最终研究状态。
