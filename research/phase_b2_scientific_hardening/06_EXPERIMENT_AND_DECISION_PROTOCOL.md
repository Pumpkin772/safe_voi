# Phase B2 预注册实验与判决协议

## 1. 数据分割

- development seeds：用于调试；
- validation seeds：用于选择 horizon、solver tolerance、阈值；
- final known seeds：30；
- final OOD/extreme seeds：50；
- final 只运行一次，不反馈调参。

## 2. 场景组

### Load-only

- ±0.02/0.04/0.06/0.08 pu step；
- ramp；
- stochastic；
- double event。

### Regime-only

- headroom loss；
- energy limit；
- delay/dropout；
- disable；
- gradual degradation；
- recovery。

### Relative timing

- regime change 10/5 s before load；
- coincident；
- 5/10/30 s after load；
- repeated changes。

### OOD

- structurally different delay/hysteresis；
- asymmetric capability；
- untrained combination；
- Plant C 或不同 plant order（如工作量允许）。

## 3. 方法

最少：

- O0 conventional baseline；
- current RLS-MPC；
- O1 truth-regime identified MPC；
- O2 exact nonlinear NMPC；
- old SD-BMPC（只作历史参考，不再调）；
- perfect telemetry comparison（可选）。

## 4. 主要指标

### Safety/quality

- max frequency deviation；
- frequency IAE；
- ACE IAE；
- tie-line restoration；
- frequency/ACE settling；
- failure/catastrophic rate。

### Resource

- SG/IBR actual energy；
- SG/IBR mileage；
- reserve saturation；
- GRC activation；
- SoC/headroom violation；
- cost sensitivity。

### Model/diagnosis

- 1/5/10/20-step errors；
- control-relevant regime error；
- detection delay vs Tcritical；
- source confusion；
- OOD detection；
- information Gramian。

### Computation

- mean/p95/max solve time；
- timeout/infeasible；
- KKT and constraint residuals。

## 5. Materiality gate

问题具有实质性需满足：

1. Plant B 至少一个合理 SG-scarce 场景中 O2 相比 O0 显著降低 failure 或频率/ACE指标；
2. 改善不是仅由无限/廉价 IBR 控制努力换取；
3. 在至少两个成本比假设下仍成立；
4. O2 求解质量合格；
5. 结果不只由 O0 明显不可行的单一事故支配。

## 6. Bottleneck trigger

### MODEL_MISMATCH

O2 相比 O1 的场景平衡 IAE/ACE 或 failure 改善超过预注册阈值，且 O2 合格。

### PASSIVE_IDENTIFIABILITY

拥有正确候选模型时，超过一半 control-relevant changes 在 Tcritical 前无法被动判别，并且 O1/O2 显示及时知道 regime 有实质价值。

### CONTROL_DESIGN

正确 model/belief 可获得且可辨识时，一个单因素控制设计修正带来超过阈值的场景平衡改善。

### INCONCLUSIVE

没有触发任何条件，或 materiality/Oracle 质量不足。

## 7. 禁止事项

- 不得按 final seed 调参；
- 不得删除失败；
- 不得将真实 regime 输入普通方法；
- 不得用 SG mileage 单项替代总成本；
- 不得把 O2 称为 globally optimal；
- 不得在无 trigger 时强制选择 bottleneck；
- 不得在本阶段未经审查直接实现下一 proposed method。
