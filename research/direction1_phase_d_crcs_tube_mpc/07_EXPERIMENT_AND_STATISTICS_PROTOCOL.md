# 实验、统计、消融、鲁棒性和失败协议

## 1. 数据防火墙

- `development`：调模型阶数、控制权重、检测阈值；
- `validation`：选择唯一参数版本；
- `final_known`：已知单机制变化；
- `final_ood`：复合、漂移、非对称和模型外动态；
- final运行后禁止改算法、权重、阈值和统计规则。

## 2. 实验因素必须独立

禁止用 `seed % n` 同时决定多个因素。使用显式全因子/分层抽样表：

- Plant：A、B；
- SFR周期：2 s、4 s；
- SG备用：adequate、scarce、critical；
- 机制：nominal、headroom-only、ramp-only、delay-only、energy-only、availability-only；
- 严重度：mild、medium、severe；
- 能力变化时刻：随机20–120 s；
- 负荷事件相对关系：变化前、同时、变化后、无事故；
- 负荷：阶跃、斜坡、脉冲、随机净负荷；
- 测量噪声：低、中、高；
- 通信：正常、抖动、随机丢包；
- 初始SoC区间；
- 独立随机种子。

## 3. 仿真时长

- 事故场景：至少300 s，关键场景600 s；
- 正常运行：至少3600 s；
- Plant B核心场景不少于Plant A核心矩阵的30%；
- 所有方法使用相同测量、估计器、扰动和随机流。

## 4. 基线

必须实际运行：

- SG-only ACE PI；
- fixed-allocation PI；
- nominal linear MPC；
- true RLS adaptive MPC；
- worst-case tube MPC；
- CRCS-TMPC；
- current-capability rolling NMPC Oracle（evaluation-only）。

## 5. 科学成功标准

episode成功必须同时满足：

- 紧急频率范围；
- RoCoF范围；
- 无SG/BESS物理约束违例；
- 求解/估计没有未恢复失败；
- 最后30 s平均和最大 \(|\Delta f|\) 达标；
- 最后30 s平均和最大 \(|ACE|\) 达标；
- 联络线计划恢复；
- BESS能量位于安全区并保留预注册备用。

具体阈值须按50/60Hz系统标准和参数来源预注册，不得使用0.8 Hz、0.35 pu这类过宽统一门限。

## 6. 主要指标

优先级顺序：

1. 科学成功/失败四格表；
2. 频率IAE、RMS、nadir、RoCoF和恢复时间；
3. ACE IAE和尾段误差；
4. tie-line IAE和尾段误差；
5. SG/BESS里程、能量、备用和约束激活；
6. 能力集合覆盖率、宽度、首次覆盖恢复时间；
7. 变化检测假警率；
8. 求解时间、不可行率和备份占比；
9. 物理成本和Pareto。

## 7. OOD场景

必须真实实现：

- 正负方向不对称功率/爬坡；
- Q占用导致的动态有功电流限幅；
- 未见三阶/非最小相位外部动态；
- 时变/随机延迟；
- 缓慢漂移；
- 多次切换；
- 能力变化与负荷同时发生；
- 未知初始能量区间；
- 服务恢复。

## 8. 消融

真实运行而非proxy：

- no capability update；
- no change reset；
- point estimate代替set；
- no tube tightening；
- no delay scenarios；
- no energy interval；
- no SG terminal backup；
- true load estimator替代/现实估计器差异（只作信息价值）；
- exact capability Oracle。

## 9. 统计

- 先报告失败四格：双方成功、仅方法失败、仅基线失败、双方失败；
- 连续指标只在共同成功场景比较，同时给失败惩罚敏感性；
- 使用配对差值、配对中位数、场景平衡汇总和cluster bootstrap；
- seed必须代表真实独立噪声/负荷实现；
- 不使用逐episode百分比比值的简单平均；
- 多重比较使用Holm校正；
- 报告效应量和95%CI，不只报p值。

## 10. 最低实验量

在计算资源允许的前提下：

- development：每核心cell 5 seeds；
- validation：每核心cell 10 seeds；
- final：每核心cell 20 seeds；
- Plant B允许使用分层代表子集，但每个核心机制、严重度和SG级别必须覆盖；
- 最终episode预计1200–3000，失败不删除。

## 11. 失败分类

严格区分：

```text
success
physical_constraint_failure
frequency_failure
ace_or_tie_failure
terminal_recovery_failure
estimator_failure
capability_set_coverage_failure
solver_failure
code_failure
not_evaluated
not_applicable
```
