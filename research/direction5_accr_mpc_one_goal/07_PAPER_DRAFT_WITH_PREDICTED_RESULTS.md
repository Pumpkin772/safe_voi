# 论文初稿（含预期结果，必须以实际结果替换）

## 暂定题目

### 中文
**黑箱IBR未通知能力变化下的安全主动能力认证与追索模型预测多区域二次频率控制**

### 英文
**Safe Active Capability Certification and Recourse Model Predictive Control for Multi-Area Secondary Frequency Regulation With Unannounced Black-Box IBR Capability Changes**

## 摘要草稿

黑箱逆变器型资源参与二次频率调节时，其实际可交付功率、爬坡和执行延迟可能偏离调度模型。被动闭环数据通常缺乏足够激励，使在线控制器无法认证合同能力以上的可用调频能力；直接依赖历史能力又无法应对未通知下降。本文提出主动能力认证–追索模型预测控制（ACCR-MPC）。首先，将实际IBR并网点功率作为电网功率平衡的已知输入，以分离外部负荷与设备执行失配；然后基于命令–出力数据维护候选执行模型集合。为解决自然数据不可辨识问题，本文设计分配中性的事件触发探测：同步机和IBR命令进行等量反向调整，区域总SFR命令保持不变；探测仅在所有候选能力以及不交付分支下均满足频率、ACE、联络线和设备约束时执行。探测结果形成有限有效期的控制相关能力证书。随后，ACCR-MPC在合同保证分量、认证剩余分量和探测分量之间分解IBR命令，并通过能力丢失分支由同步机和慢速备用进行未来追索。本文给出分配中性、候选集合包含性、有限时域安全探测、能力类可区分性和条件性追索可行性结果。

`[PREDICTED]` 基于前期负结果，完美能力信息的价值主要体现在ACE和联络线责任，而非频率峰值。预计ACCR-MPC能够在保持频率安全非劣和零物理硬约束违反的前提下，在具有额外功率/爬坡价值的预注册场景中回收40%–70%的完美信息价值；能力候选集合宽度预计降低40%–80%，探测引起的增量频差保持在0.02 Hz以内。所有预期值均为预注册目标，不是已获得结果；最终结论取决于独立validation和一次性final。

## 1. 引言

### 1.1 问题
- 黑箱IBR模型不可得；
- 实际能力会变化；
- 被动数据缺乏激励；
- 安全估计越保守，额外能力越无法利用；
- 主动探测可能影响频率，需要安全设计。

### 1.2 文献空白
- 黑箱多模式建模已有；
- 数据驱动二次控制与安全持续激励已有；
- 双重/主动探索MPC已有；
- 功率系统探测设计已有；
- 但“事件触发的设备可交付能力认证、多区域ACE责任、合同安全与能力丢失追索”的交叉仍需验证。

### 1.3 贡献
1. 分配中性的安全主动能力认证；
2. 控制能力类集合成员认证；
3. ACCR-MPC；
4. 条件性理论和不可保证边界；
5. Plant A/原生Plant B、normal1h、known/OOD完整协议。

## 2. 模型
使用 `02_COMPLETE_MATHEMATICAL_DERIVATION.md` 中式(1)–(29)。

## 3. 主动能力认证
使用式(30)–(54)。

## 4. ACCR-MPC
使用式(55)–(63)。

## 5. 理论
使用定理1–6。

## 6. 实验

### 6.1 基线
列出合同MPC、被动自适应、安全PE、周期探测、Oracle。

### 6.2 场景
完整能力变化与负荷事件。

### 6.3 指标
安全、信息、性能和计算。

## 7. 预期结果表

| 结果 | 历史被动方法 | ACCR预期 | 判断 |
|---|---:|---:|---|
| 剩余能力激活 | 0.0089%调用 | eligible后显著提高 | 实际填充 |
| 候选集合宽度 | 宽 | 降低40%–80% | 实际填充 |
| 探测增量频差 | 无探测 | ≤0.02 Hz | 实际填充 |
| false optimism | 低但无信息 | ≤1% | 实际填充 |
| ACE价值回收 | 负 | 40%–70% Oracle value | 实际填充 |
| tie价值回收 | 负 | 40%–70% Oracle value | 实际填充 |
| frequency | 被动变差 | 非劣 | 实际填充 |
| success | 下降7.48pp | 下降≤1pp | 实际填充 |
| hard violation | 0 | 0 | 实际填充 |
| fallback | 5%量级 | ≤contract+1pp | 实际填充 |

## 8. 结果章节模板

```text
[TO BE FILLED: platform qualification]
[TO BE FILLED: passive information deficit reproduction]
[TO BE FILLED: probe safety and information]
[TO BE FILLED: certification coverage]
[TO BE FILLED: value recovery]
[TO BE FILLED: known/OOD]
[TO BE FILLED: Plant A/B]
[TO BE FILLED: normal1h]
[TO BE FILLED: contract violation]
[TO BE FILLED: failure cases]
[TO BE FILLED: computation]
```

## 9. 结论边界

若Gate通过：
> ACCR-MPC在注册条件下以安全主动探测克服自然闭环信息不足，并在频率安全非劣的条件下回收部分ACE/联络线/同步机成本价值。

若Gate失败：
> 在注册安全裕度内，主动探测的信息增益不足以抵消探测和追索成本；方向5终止，并形成决定性负结果。
