# ACCR-MPC方法与实现规范

## 1. 模块

```text
公共测量
  ├─ GridLoadObserver
  ├─ CapabilityChangeMonitor
  └─ SetMembershipCapabilityEstimator
             ↓
      ProbeTriggerAndSafetyGate
             ↓
        ProbeDesigner
             ↓
       CapabilityCertificate
             ↓
          ACCR-MPC
```

## 2. 实现优先顺序

1. 重用已验证Plant A和原生Plant B；
2. 修复normal1h基准，使所有基础控制器至少在合理profile下稳定；
3. 建立被动集合估计baseline；
4. 建立探测库；
5. 安全筛选探测；
6. 集合更新和有限期证书；
7. ACCR控制器；
8. 理论证书；
9. 全矩阵实验。

## 3. 探测库

至少包括：

- biphasic：
  ```text
  [+a,+a,-a,-a]
  ```
- alternating：
  ```text
  [+a,-a,+a,-a]
  ```
- staircase：
  ```text
  [+a,+2a,0,-2a,-a]
  ```
- zero-mean PRBS；
- development优化的连续序列。

幅值候选：

```text
0.0025, 0.005, 0.0075, 0.010, 0.015 pu
```

长度候选：

```text
2, 3, 4, 6 control intervals
```

所有探测必须零和或在窗口内能量中性，并通过鲁棒安全筛选。

## 4. 自动方法选择

在development中：

1. 先筛除所有不安全探测；
2. 对剩余探测计算：
   - 信息增益；
   - 频率/ACE/tie代价；
   - 能量；
   - 可区分能力类；
3. 选择Pareto最优探测策略；
4. validation只允许最多两轮有依据修复；
5. final冻结。

## 5. 集合成员实现

推荐：

- power/ramp/delay候选离散网格；
- 对每个候选delay和capacity cell，求连续 \(a,b\) 可行多面体或网格；
- 滑动窗口；
- 变化检测后reset；
- 保留true containment测试；
- 输出candidate count、diameter、certificate和expiry。

## 6. 探测安全门

只有满足以下条件才允许：

- frequency/ACE/tie处于探测允许区；
- SG具有抵消headroom；
- BESS SoC和合同headroom充足；
- loss branch安全；
- solver可行；
- 预测probe cost低于注册上限。

## 7. 对照方法

必须包括：

1. contract-only MPC；
2. passive set-adaptive MPC；
3. safe persistent-excitation feedback optimization基线；
4. fixed periodic probe；
5. event-triggered probe without safety gate；
6. ACCR-MPC；
7. true-capability Oracle。

## 8. 代码接口

```python
probe = probe_designer.propose(
    observation,
    feasible_model_set,
    contract_capability,
    state_estimate,
)

accepted_probe = safety_gate.accept_or_zero(probe)

certificate = estimator.update(
    issued_command,
    actual_poi_power,
    accepted_probe,
)

action = accr_mpc.solve(
    state_estimate,
    load_set,
    contract_capability,
    certificate,
    probe=accepted_probe,
)
```

## 9. 禁止

- 用truth决定是否探测；
- 在final后改变探测幅值；
- 删除探测失败；
- 把command-neutral称为physical-power-neutral；
- 通过扩大事故幅值制造信息价值；
- 把普通随机噪声叠加称为新方法；
- 临时加入RL。
