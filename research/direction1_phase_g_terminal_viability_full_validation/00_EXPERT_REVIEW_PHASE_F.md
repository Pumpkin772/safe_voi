# Phase F 专家审查与裁决

## 一、可信成果

- ZIP、manifest 和阶段治理完整；没有删除失败结果。
- G0–G4 均产生了明确、可追踪证据。
- 实现了 `propose → supervisor → commit_applied_action`，修复了 Phase E 的动作历史事务缺陷。
- 对 solver、terminal reject、restoration 和 backup 进行了结构化分类。
- 建立了五个延迟顶点的共同控制序列滚动 QP 原型。
- 在 G5 无法得到证书后停止，没有伪称递归可行，也没有消耗 final seeds。

## 二、G5失败的决定性原因

### 1. 终端扰动集合与终端限制在一步上已经不相容

Phase F 一步状态残差半径为：

```text
[0.00799565, 0.00709626, 0.10434633, 0.06645182,
 0.05858623, 0.06308563, 0.03916844, 0.01753620, 0.02027096]
```

前两项是标幺频率状态，按 50 Hz 换算：

```text
Area 1: 0.3998 Hz
Area 2: 0.3548 Hz
```

均大于终端频率限制 0.30 Hz。联络线一步半径 0.10435 pu 也大于终端限制 0.08 pu。

若 ACE 频率偏置为 21，则零状态下的一步 ACE 最坏半径至少为：

```text
Area 1: 21*0.00799565 + 0.10434633 = 0.2723 pu
Area 2: 21*0.00709626 + 0.10434633 = 0.2534 pu
```

也均大于终端 ACE 限制 0.15 pu。

因此，对当前被解释为“每个控制周期都可独立出现”的全局加性扰动集合，任何反馈都无法让当前终端 box 正不变。此时正确状态应是：

```text
TERMINAL_DISTURBANCE_SET_INCOMPATIBLE_WITH_TERMINAL_LIMITS
```

而不是简单解释为“两个 backup 设计都失败”。

### 2. 全局残差被错误用于本地终端不确定性

F3残差同时包含：

- 0.05–0.08 pu 负荷阶跃；
- 能力变化；
- estimator transient；
- 饱和、GRC 和非线性；
- 未观测阀门状态的重构误差；
- 延迟顶点选择误差。

随后使用 99.5% 分位数再乘 1.5，并把它当成终端区域内每一步可重复发生的独立扰动。这把一次性事件和估计器瞬态转换成了持续对抗性状态冲击，物理含义不成立。

终端证书必须使用：

- 终端局部区域；
- 无新事故、无新能力跳变的窗口；
- 因果状态观测误差；
- 有结构的负荷估计误差；
- 本地模型残差；

而不是全局事故窗口。

### 3. SG-only无限时域备份与场景备用不足矛盾

F5要求每个区域 SG 命令不超过 0.025 pu，并令 BESS SFR 为零。两个区域总保证 SG 备用只有 0.05 pu，而注册事故最大为 0.08 pu。即使控制器完美，也不可能由 SG-only 无限时域承担全部持续缺额。

该研究恰好关注 SG 稀缺时 BESS 的价值，因此不能把“SG-only无限时域接管所有注册事故”作为所有场景统一必须满足的终端假设。

正确划分是：

1. **可持续域**：持续缺额能由 SG/慢速可持续资源承担，BESS 最终回到零净功率，可建立无限时域终端不变集；
2. **有限能量桥接域**：SG当前备用不足，BESS利用保证功率和能量在有限时间内桥接，直到慢速备用/再调度接管；这里只能给有限时域生存性或条件性递归保证；
3. **不可行域**：即使考虑保证BESS能力和注册慢速接管时间也无法满足物理约束，应明确失败而不是调参掩盖。

### 4. 只测试两个固定反馈不能证明“不存在集合”

F5仅测试 stable ACE PI 和全状态 LQR。二者失败只能说明该反馈和该扰动集合不适用，不能证明不存在：

- SG+BESS保证能力的共同backup；
- 鲁棒控制不变集合；
- 前驱集合；
- 负荷依赖平衡点附近的本地RPI；
- 分阶段 bridge-to-terminal 方案。

### 5. 代码中还有一个逻辑缺陷

证书脚本把：

```python
backup_nonempty = bool(table.constraints_satisfied.all())
```

作为整体通过条件。若只要求存在至少一个有效设计，应使用 `any()`。当前四个设计都失败，所以不改变本轮结果，但必须修复。

## 三、F4尚未达到完整鲁棒物理预测

- SG机械功率硬约束没有按同一误差集合完整收紧；
- BESS能量使用请求功率近似，而不是预测的实际延迟后BESS输出；
- ramp主要约束请求动作，不完全等价于执行器实际功率爬坡；
- 终端约束没有采用一致误差margin；
- residual set约97%经验覆盖，不能称为确定性“对所有扰动”保证；
- G4仅验证了20个开发状态上的一次动作，未完成闭环比较；
- p99求解约2.40 s，对2 s控制周期不满足实时性，对4 s也超过半周期Gate。

## 四、科学状态

```text
SCIENTIFIC_QUESTION: CONTINUE
H1_MATERIALITY: SUPPORTED_FOR_POWER_RAMP_ENERGY_AVAILABILITY; DELAY_CONDITIONAL
H2/H3: LIMITED_NEGATIVE_EVIDENCE_ONLY
G5_RESULT: CERTIFICATE_FORMULATION_INCOMPATIBLE, NOT_METHOD_FALSIFICATION
CURRENT_CDSR: DEVELOPMENT_PROTOTYPE
NEXT_ACTION: TERMINAL/UNCERTAINTY RECONSTRUCTION AND FULL VALIDATION
```
