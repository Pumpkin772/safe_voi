# 一个总Goal下的完整执行计划

内部阶段：

```text
A0 → A1 → A2 → A3 → A4 → A5 → A6 → A7 → A8
```

Codex不得在阶段间等待用户重新发指令。

## A0：冻结当前负结果与重建基准平台

### 目标
保留当前负结果，修复正常1小时平台，建立可信基线。

### 任务
- 冻结当前ZIP、commit、final seeds；
- 新研究使用全新dev/validation/final seeds；
- 诊断所有方法normal1h失败；
- 修复anti-windup、profile尺度、slow reserve和稳定性；
- 不得使用旧final结果调新方法；
- 完成Plant A/B一致性和dt收敛。

### 输出
```text
00_AUDIT/CURRENT_NEGATIVE_RESULT_FROZEN.md
03_MODEL/NORMAL1H_PLATFORM_REBUILD.md
results/A0/NORMAL1H_BASELINE_VALIDATION.parquet
tests/test_a0_platform.py
```

### Gate
- contract MPC、nominal MPC、anti-windup PI在正常profile下通过注册频率品质；
- 若所有合理基线仍失败，停止为 `BENCHMARK_PLATFORM_NOT_VALID`。

## A1：文献、创新和材料性重验

### 目标
确认主动能力认证仍有创新和信息价值。

### 任务
- ≥70篇正式文献/官方报告；
- 对比safe data-driven secondary control、nullspace excitation、active exploration MPC、power-system probing、adaptive control allocation；
- 重新运行perfect information materiality；
- 预注册materiality-positive cells。

### Gate
- 至少power或ramp机制在两个SG tension上具有ACE/tie/SG-mileage价值；
- 未发现完整覆盖“事件触发安全能力认证+多区域责任”的正式工作。

失败则终止。

## A2：被动集合与探测模型实现

### 目标
建立可审计的候选模型集合和被动基线。

### 任务
- 实现式(15)–(29)；
- noise bound calibration；
- passive set baseline；
- abrupt change reset；
- true containment和false optimism验证；
- no-excitation不虚假收缩。

### Gate
- validation true containment≥95%；
- false optimism≤1%；
- passive结果复现当前信息不足现象。

## A3：安全探测设计

### 目标
设计能提供信息且系统影响受限的探测。

### 任务
- 建立probe library；
- 安全门；
- delivered/loss分支；
- 计算信息增益和probe cost；
- development自动选择幅值、长度和触发策略；
- validation最多两轮修复。

### Gate
- 物理硬约束0违反；
- 额外frequency peak≤0.02 Hz或相对≤2%；
- probe期间ACE/tie代价≤注册阈值；
- 至少50%的materiality-positive eligible episodes使候选集合直径降低≥40%；
- false optimism≤1%。

失败：
- 若所有安全probe无信息，终止 `SAFE_ACTIVE_IDENTIFICATION_NOT_MATERIAL`。

## A4：ACCR-MPC实现

### 目标
把证书真正用于控制，而不是只改变成本权重。

### 任务
- 合同分量；
- 认证剩余分量；
- probe分量；
- delivered/loss branch；
- SG/slow reserve recourse；
- actual action commit；
- energy/delay；
- terminal/bridge；
- feasibility restoration。

### Gate
- 真实滚动MPC；
- 动作100%可用；
- hard violation=0；
- solver分类完整；
- p99<0.5Ts。

## A5：理论和证书

完成P1–P7。若证书范围有限，收缩声明。

## A6：Development/Validation定型

### 主要比较
ACCR vs contract MPC。

### Primary endpoints
1. frequency safety non-inferiority；
2. ACE/tie/SG-mileage的perfect-information value recovery；
3. success和hard constraints；
4. probe cost。

### 预注册Gate
- success drop≤1pp；
- frequency peak非劣margin≤0.02 Hz或2%；
- hard violations=0；
- fallback不高于contract+1pp；
- 在materiality-positive cells中：
  - ACE或tie至少一个改善≥4%，CI lower>0；
  - value recovery ratio至少0.40，CI lower>0；
  - SG mileage不恶化或改善；
- cross-plant方向一致；
- normal1h通过；
- p99实时。

### 修复
development/validation最多三轮：
1. probe library/trigger；
2. estimator window/noise bound；
3. MPC weight/horizon；
仅可按预注册范围、依据诊断修改。

三轮后失败则终止，不运行final。

## A7：Final一次性确认

- 新final seeds；
- 方法、threshold、probe、weights锁定；
- final只运行一次；
- known/OOD/contract violation；
- Plant A/B；
- 全部失败保留；
- final后不调参。

## A8：论文和统一审查包

最终只允许：

```text
PAPER_READY_WITH_BOUNDED_CLAIMS
```

或：

```text
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```

不得创建新阶段继续尝试。
