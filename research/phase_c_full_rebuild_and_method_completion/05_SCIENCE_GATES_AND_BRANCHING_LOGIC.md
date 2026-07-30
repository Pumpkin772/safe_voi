# 科学Gate与自动分支逻辑

## 1. 状态机原则

Codex必须维护：

```text
progress/phase_status.json
progress/decision_ledger.md
```

每阶段状态只能是：

```text
NOT_STARTED
RUNNING
PASSED
FAILED_REPAIRABLE
FAILED_FATAL
SKIPPED_BY_GATE
COMPLETED_WITH_LIMITATIONS
```

## 2. 材料性Gate

### 通过

Plant A和Plant B中至少满足一条：

- Oracle在两个核心指标上≥10%改善且95%CI下界>0；
- 失败率降低≥20个百分点；
- 同资源预算下Pareto前沿显著外移。

### 不通过

单位/模型/Oracle全部验证后，Plant A与Plant B均无上述价值。

### 自动规则

- 不通过：停止方法开发，生成完整负结果包，最终状态 `PROBLEM_NOT_MATERIAL`；
- 仅Plant A通过：继续但状态 `NATIVE_MODEL_NOT_VALIDATED`；
- 通过：进入可辨识性Gate。

## 3. 可辨识性Gate

### 被动可辨识

- `P(Tdet<Tcrit)≥0.8`
- false alarm≤5%
- 负荷/能力变化macro-F1≥0.8或等价统计门
- 至少在headroom/ramp/delay三个主要机制中两类满足

进入C6-A。

### 需要主动辨识

- Oracle材料性通过；
- 被动检测不满足；
- 存在robust safe excitation set；
- 在激励预算内理论/仿真信息量显著提高。

进入C6-B。

### 结构不可辨识

- 在允许输入和测量下，候选能力的外部行为距离低于分辨阈值；
- 或所有安全激励都不足以区分；

进入C6-C，不再追求标签分类。

## 4. 方法成功Gate

相对最佳可部署基线：

- 成功率不降低超过2个百分点；
- 至少两个主要性能指标改善≥8%，场景平衡95%CI支持；
- OOD不发生系统性安全退化；
- 求解不可行率≤1%；
- 99%在线时间<0.5控制周期；
- fallback占比合理并有解释。

## 5. 理论Gate

至少获得：

1. 能力/模型集合更新的真值覆盖条件；
2. backup/terminal set；
3. 递归可行性；
4. 约束安全。

若不能获得，方法不得声称“guaranteed safe”。可以降级为经验方法，但论文创新评价同时降级。

## 6. 自动失败诊断顺序

任何实验失败时必须依次检查：

1. **代码**：符号、单位、索引、延迟、状态泄露、数据匹配；
2. **数值**：积分步长、缩放、KKT、初值、求解器；
3. **参数**：是否超出预注册范围、是否物理不合理；
4. **模型**：模型失配、未建模约束、不可观测；
5. **方法**：控制器结构、估计器、robustness；
6. **科学假设**：Oracle无价值或结构不可辨识。

不得跳过前五项直接宣称科学问题失败，也不得通过无依据调参掩盖第六项。

## 7. 重试限制

- 代码/数值错误：修复后不限于一次，但每次必须有测试和diff；
- 方法性调参：最多两轮，必须基于development/validation数据和预注册范围；
- final seed结果出来后：禁止改变方法、参数、阈值和场景；
- 两轮后仍失败：保留失败证据并继续整理负结果。
