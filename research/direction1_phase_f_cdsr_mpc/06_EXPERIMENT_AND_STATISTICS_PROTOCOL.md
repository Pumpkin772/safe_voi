# Phase F 实验与统计协议

## 1. 数据分割

```text
development seeds: 0–19
validation seeds: 20–39
final seeds: 100–159
```

final seeds在F7前不得运行。

所有选择只能用development：
- 最佳基线；
- horizon；
-权重；
- residual set；
- delay grid；
- terminal set；
- solver tolerance；
- Gate阈值。

validation只允许最多两轮有依据修复；final运行一次。

## 2. 因素必须独立

manifest显式列出：

- mechanism；
- SG tension；
- SFR period；
- load timing；
- disturbance area；
- sign；
- magnitude；
- duration；
- measurement noise；
- jitter；
- dropout；
- initial SoC；
- capability change time；
- delay trajectory；
- Plant A/B；
- split。

不得用 `seed % n` 隐式绑定多个物理因素。

## 3. 基准

- SG-only PI；
- fixed-allocation PI；
- nominal rolling MPC；
- RLS adaptive rolling MPC；
- single-worst-delay robust MPC；
- capability-floor-only MPC；
- CDSR-MPC；
- current-capability rolling NMPC Oracle（evaluation-only）。

每个叫MPC的方法必须保存预测时域、动作序列、solver status和约束残差。

## 4. 指标

### Success-first
- physical success；
- only proposed fails；
- only baseline fails；
- both fail；
- not evaluated；
- solver failure；
- fallback。

### Frequency
- max frequency；
- RoCoF；
- frequency IAE/RMS；
- terminal frequency；
- settling time。

### Regional
- ACE IAE/RMS；
- tie-line IAE；
- terminal ACE/tie；
-区域责任恢复。

### Resource
- SG/BESS mileage；
- energy；
- headroom/ramp saturation；
- SoC；
- backup reserve；
- hard constraint violation。

### Computation
- primary/secondary/restoration status；
- solver time median/p95/p99；
- residual；
- fallback；
- consecutive fallback；
- action-history mismatch。

## 5. 统计

- 场景平衡后汇总；
- 配对绝对差和aggregate-mean ratio；
- seed-cluster bootstrap；
- failure-aware utility敏感性；
- known与OOD分开；
- 多重比较修正；
- 不使用“逐episode相对比值平均”作为主指标；
- 连续指标只在both-success上比较时，必须同时展示paired failure table。

## 6. OOD

- capability combinations；
- asymmetric charge/discharge；
- continuous time-varying delay；
- slow drift；
- unseen SoC；
- unseen Plant B operating point；
- delayed capability recovery；
- repeated changes。

## 7. 失败案例

至少保存：
- 最严重frequency；
- 最严重ACE；
- 最严重tie；
- solver failure；
- restoration；
- SG fallback；
- delay mismatch；
- energy boundary；
- Plant B divergence/initialization warning。

不得只保存有利图。
