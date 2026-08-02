# 实验、统计与基线规范

## 分割

```text
development: 0–19
validation: 20–39
final: 100–159
```

final在G8前禁止运行。

## 基线

- SG-only ACE PI；
- fixed-allocation ACE PI；
- nominal rolling MPC；
- RLS adaptive rolling MPC；
- single-worst-delay robust MPC；
- capability-floor-only MPC；
- CDSR-MPC；
- current-capability rolling NMPC Oracle（evaluation only）。

每个MPC必须保存真实优化状态、控制序列、constraint residual和solver log。

## 场景

### Known
- headroom；
- ramp；
- energy；
- availability；
- delay作为实施不确定性；
- 2/4s；
- 三种SG tension；
- 300–600s事故；
- 1h正常净负荷；
- 独立noise/jitter/dropout。

### OOD
- 联合能力变化；
- 非对称充放电；
- 连续delay；
- slow drift；
- repeated changes；
- 未见SoC；
- Plant B运行点/接入位置。

## 统计

- success-first；
- paired failure table；
-双方成功连续指标；
- failure-aware utility敏感性；
- scenario-balanced；
- seed-cluster bootstrap；
- known/OOD分开；
-可持续域/桥接域/不可行域分开；
- solver/restoration/backup原因分开；
- 不使用逐episode相对比值平均作为主指标。

## 主要Gate

- success下降≤2pp；
- failure-aware不劣；
- frequency/ACE/tie至少2项改善≥8%且CI>0；
- hard violations=0；
- unresolved math infeasibility≤0.1%；
- backup≤1%，无级联；
- p99<0.5Ts；
- Plant A/B方向一致。
