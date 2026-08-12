# 最新VOI-ACCR审查包专家评议

## 1. 完整性与可复现性

审查对象：

```text
DIRECTION5_VOI_ACCR_MPC_SINGLE_REVIEW_PACKAGE.zip
```

独立SHA256：

```text
d967abe999ff8e0f0da3cad293d9ccc7644947299b2a8fb636a2469666684f91
```

审查结果：

- 压缩包约20MB，解压约67MB；
- 文件1819个；
- manifest核验通过；
- minimal replay通过；
- M1开发原型通过；
- M2独立validation失败；
- final未运行；
- final seeds未使用；
- 负结果和无效M2-V1均保留。

## 2. 总体裁决

```text
HIGH_LEVEL_SCIENTIFIC_QUESTION: VALID
FROZEN_HEURISTIC_VOI_ACCR_IMPLEMENTATION: NOT_SUPPORTED
BROAD_ACTIVE_PROBING_IMPOSSIBILITY: NOT_ESTABLISHED
FORMAL_VOI_PROBLEM_IMPLEMENTATION: INCOMPLETE
ORACLE_MATERIALITY_CEILING: NOT_A_GLOBAL_CEILING
NEXT_ACTION: ONE_FINAL_BOUNDARY_AND_SELECTIVE_POLICY_PROGRAM
```

## 3. 当前包的可信成果

1. 低价值场景可以安全放弃探测，并与合同MPC保持数值等价；
2. 小幅分配探测在局部开发场景中可以安全降低候选集合直径；
3. 完整M2中求解器稳定、无hard violations、无fallback；
4. Plant A为完整非线性闭环，Plant B使用原生ANDES；
5. false optimism、无探测、负结果均如实保存；
6. 当前方法在实际探测场景中没有获得净性能价值。

## 4. 致命问题

### 4.1 形式化VOI没有在代码中实现

文档定义的是：

- 当前鲁棒控制遗憾；
- 探测后所有可能后验集合；
- 后验最优追索；
- 完整探测代价；
- 净价值。

代码实际使用的是启发式proxy：

- 四个代表能力角点的第一动作差；
- 简化一阶执行器签名；
- 固定代数公式组合gross value与probe cost；
- 不是嵌套鲁棒控制VoI。

因此当前结果只能否定这个proxy，不能否定文档中的正式VoI问题。

### 4.2 “worthwhile”子集不是控制价值边界

M2将 `HIGH_VALUE_CANDIDATE` 主要按固定负荷幅值注册，并不是根据：

- 当前状态；
- 候选集合；
- 最优动作差异；
- perfect-information gap；
- 探测后后验追索成本

确定。

结果中同一“worthwhile”子集包含大量Oracle价值接近零的场景。

### 4.3 Oracle不是全局性能上界

所谓perfect-capability Oracle：

- 与合同MPC共享相同线性预测模型；
- 共享冻结目标函数；
- 目标中tie weight为0；
- 只筛选horizon 3/4/6；
- 主要在Plant A小型development集合中评估。

它是：

```text
registered-controller-family perfect-information comparator
```

不是：

```text
all-controller perfect-information ceiling
```

尤其不能用tie weight为0的控制器族否定tie-line信息价值。

### 4.4 2s设计被直接扩展到4s

M1仅以2s周期设计：

```text
[+q,-q]
```

物理探测持续4s。

M2在4s周期仍使用两个控制步，探测持续8s；horizon 3也从6s变为12s；证书有效期仍为4s。

因此2s与4s不是物理等价实验。M2中2s聚合结果略正、4s结果明显负，与该不一致相符。

### 4.5 Plant B没有触发探测

Plant B的预注册高价值场景中：

```text
probe trigger = 0
```

这只能说明方法在Plant B判断无正价值或代理门失败。若正确策略应当放弃，零改善不应自动成为“跨Plant正方向失败”。

跨Plant Gate把“安全放弃”错误地当成方法失败。

### 4.6 证书false optimism过高

M2中：

```text
4 / 21 = 19.05%
```

证书高估真实能力，不能用于安全性能声明。

### 4.7 候选模型和OOD真值不匹配

有限候选网格只含少量power/ramp/delay点。OOD真值位于网格之间，但证书没有经过连续参数外包证明。

### 4.8 统计重复不足

60个validation场景覆盖许多设计因素，但多数精确设计cell缺少独立重复seed。层级bootstrap主要在异质cell间重采样，不能充分估计同一cell内的随机变异。

### 4.9 探测增量频率指标不正确

M2使用整段episode最大频率峰值之差。若最大峰值发生在探测前，该指标为0，即使探测窗口内产生额外频率扰动。

必须改为：

```text
probe window incremental peak / IAE / ACE / tie
relative to matched no-probe counterfactual
```

### 4.10 正常运行证据过少

只有一个1h profile、两种方法行，不能支持广泛正常运行声明。

### 4.11 Git与全量复现仍不够干净

- Git status包含大量untracked历史结果和ZIP；
- `reproduce_all.py`主要重跑少量测试和可选Oracle screen；
- 不能完整重生M1/M2所有结果；
- pyproject仍保留历史项目名。

## 5. 当前结果的正确解释

当前证据支持：

> 冻结的启发式VOI-ACCR在注册M2总体上没有净控制价值；低价值场景的安全放弃可行；局部探测可以提供模型信息；但正式的状态依赖净VoI边界尚未计算。

当前证据不支持：

> 安全主动能力探测整体无价值。

## 6. 是否继续

继续一次，但论文目标必须从：

```text
所有高负荷/高不确定场景都探测并显著提高控制性能
```

改为：

```text
计算并验证何时探测值得，何时必须放弃
```

如果严格计算后正价值区域为空，则形成边界负结果论文并终止方向5。
