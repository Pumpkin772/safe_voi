# 实验矩阵、统计和结果解释协议

## 1. 数据划分

```text
development seeds: 0–19
validation seeds: 100–119
final known seeds: 1000–1029
final OOD seeds: 2000–2049
```

最终种子不得用于调参。若原项目已有锁定种子，可等价映射并记录。

## 2. 场景因子

### 系统

- Plant A two-area；
- Plant B native multi-machine RMS/DAE。

### SG能力

- adequate；
- scarce；
- critical。

### IBR能力变化

已知单机制：

- nominal；
- headroom 100→50/25%；
- ramp 100→50/25%；
- delay 0.2→1/2 s；
- dropout 0→10/30%；
- energy available high→low；
- service disabled；
- recovery。

OOD：

- 非对称上下调；
- 复合headroom+delay；
- 渐变漂移；
- 未知三阶动态；
- 电流限制/无功占用；
- 多次切换。

### 时序

- 能力变化早于负荷事件；
- 同时；
- 晚于；
- 正常AGC中无大事故。

### 扰动

- step ±2/4/6/8% load；
- ramp；
- pulse；
- sustained imbalance；
- correlated continuous net-load；
- disturbance in either area；
- dual-area coincident disturbance。

### 不确定性

- measurement noise；
- load forecast/estimation error；
- communication jitter；
- H,D,R uncertainty；
- SoC and base operating point。

## 3. 仿真长度

- 事故/切换：至少180 s，必要时600 s；
- 正常调频：至少1 h；
- 不得用12 s结果代表SFR恢复。

## 4. 基线

必须包括：

1. SG-only/PI；
2. fixed proportional allocation；
3. nominal-model MPC；
4. RLS/adaptive MPC；
5. robust capability-set MPC；
6. selected proposed method；
7. current-regime Oracle NMPC；
8. optional clairvoyant ceiling。

若某方法不适用，标记 `not_applicable`，不是失败。

## 5. 消融

根据最终分支至少包括：

- 无online update；
- 无uncertainty tightening；
- 无backup；
- hard regime vs set/belief；
- 无library prior；
- active分支：无information objective、不同excitation budget；
- robust分支：固定最坏集合 vs 在线收缩。

## 6. 指标

### 安全与成功

- max |Delta f|；
- max RoCoF；
- frequency/ACE/tie-line bound violations；
- resource violations；
- scientific success率；
- solver success率分开。

### 性能

- frequency IAE/RMS/nadir；
- ACE IAE/RMS；
- tie-line IAE；
- settling time；
- SG/IBR energy、mileage、peak/ramp；
- SoC excursion；
- responsibility transfer time。

### 诊断/估计

- Tdet、Tcrit；
- P(Tdet<Tcrit)；
- false alarm；
- load-vs-capability confusion；
- capability set coverage/width；
- prediction errors。

### 计算

- mean/P95/P99 wall time；
- timeout；
- infeasibility；
- fallback fraction；
- iterations/KKT/residual。

## 7. 有量纲成本

成本报告为敏感性，不作为唯一科学门：

\[
C=c_E^gE_g+c_M^gM_g+c_E^bE_b+c_M^bM_b+c_VN_{viol}.
\]

每个系数必须注明单位和来源。至少报告低/中/高三组，画频率/ACE—成本Pareto。

## 8. 统计规则

1. 首先比较成功类别四格表：双方成功、仅A失败、仅B失败、双方失败；
2. 连续指标只在共同成功样本比较，同时提供失败惩罚敏感性；
3. 使用配对绝对差和场景平衡后的aggregate ratio；
4. 禁止以mean of episode-wise ratios作为唯一结论；
5. Bootstrap按scenario/seed层级重采样；
6. 报告95%CI、效应量和多重比较修正；
7. OOD单独报告，不能与known混合掩盖。

## 9. 失败分类

```text
success
physical_limit_failure
frequency_or_ace_failure
solver_failure
estimator_failure
code_failure
not_evaluated
not_applicable
```

不得把not_evaluated算入方法失败率。

## 10. 图表

必须包含：

- 模型框图；
- 单位与RoCoF验证；
- 能量守恒/能力边界；
- Oracle材料性；
- Tdet vs Tcrit；
- 代表性责任转移轨迹；
- known/OOD性能；
- success/failure图；
- Pareto；
- 计算时间；
- Plant A/B一致性；
- 最差失败案例。
