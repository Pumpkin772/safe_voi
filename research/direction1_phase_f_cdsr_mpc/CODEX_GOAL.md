# Codex唯一总Goal：方向1 Phase F CDSR-MPC

请在当前真实 Git 仓库中连续执行本Goal。不要在内部阶段结束后等待用户再次发消息。

## 一、必须先读

完整阅读：

```text
research/direction1_phase_f_cdsr_mpc/
```

下全部文件，并将：

```text
01_MASTER_EXECUTION_PLAN.md
08_GATES_FAILURE_AUTO_REPAIR.md
09_FINAL_REVIEW_PACKAGE_SPEC.md
```

视为约束性规范。

## 二、项目定位

项目统一名称：

```text
方向1 / DIRECTION1
```

本轮不更换科学问题，不回到旧论文复现，也不再探索多个算法。

唯一方法路线：

```text
CDSR-MPC
Capability-and-Delay-Set Robust MPC
with Feasibility Restoration
```

## 三、连续阶段

严格执行：

```text
F0 → F1 → F2 → F3 → F4 → F5 → F6 → F7 → F8 → F9
```

只有命中明确科学停止条件时才提前停止；即使停止，也必须执行负结果打包所需的F9。

## 四、关键必须项

1. 冻结Phase E，撤回“1.846% solver infeasibility等于方法类别失败”的外推。
2. 修复候选动作在被拒绝/fallback后仍写入MPC previous-action历史的事务错误。
3. 将solver failure、terminal reject、restoration和fallback分开统计。
4. 修正H1 baseline selection与failure-aware评价；H2/H3只能对测试方法作有限结论。
5. 用保证能力包络和显式delay set建立共同控制序列的鲁棒预测。
6. BESS总PFR+SFR的功率、爬坡和累计能量必须进入预测硬约束。
7. 不再把手工有限时域box称为tube guarantee。
8. 实现真实CDSR-MPC、可行性恢复和SG终端备份。
9. 若声称递归可行/鲁棒安全，必须给出可重算证书；否则收缩声明。
10. 所有叫MPC的基线都必须真实求解滚动时域优化。
11. ordinary controller严禁读取true capability、hidden parameter、true load、future event或final信息。
12. development/validation/final严格隔离；final运行后禁止调参。
13. 不得删除失败、降低标准、隐瞒solver warning或用SG-only冒充robust MPC。
14. Plant A和原生ANDES Plant B均需验证；ANDES初始化警告必须解释和留存。
15. 最终review ZIP必须能在解压目录中直接运行minimal replay。

## 五、失败处理

任何失败按：

```text
代码 → 数值/求解器 → 参数 → 模型 → 方法 → 科学假设
```

处理。

- 代码/数值可修复并重试；
- 参数只能在有来源的预注册范围内修改；
- formulation最多两轮development/validation修复；
- 科学假设失败时停止，不临时换算法；
- final结果不能反向用于方法设计。

## 六、必须输出

最终生成：

```text
DIRECTION1_PHASE_F_CDSR_MPC_SINGLE_REVIEW_PACKAGE.zip
```

要求：

```text
size < 512 MB
```

内容严格符合：

```text
research/direction1_phase_f_cdsr_mpc/09_FINAL_REVIEW_PACKAGE_SPEC.md
```

完成后在终端和最终报告中给出：

- ZIP绝对路径；
- bytes与MB；
- SHA256；
- Git commit；
- Git status；
- F0–F9 Gate；
- H1–H5状态；
- 最佳可部署基线；
- known/OOD结果；
- solver/restoration/fallback统计；
- certificate状态；
- Plant A/B状态；
-最严重失败和限制；
-最终研究状态。
