# Codex唯一总Goal：方向5安全能力信息正价值域重构

## 项目命名

```text
方向5：安全能力信息正价值域重构
DIRECTION5_SAFE_VOI_POSITIVE_REGION_REBUILD
direction5_safe_voi_positive_region_rebuild
```

## 唯一方法

```text
Selective VOI-ACCR-MPC
```

## 唯一科学目标

在不放松物理安全、不向普通控制器泄露true capability或future event的前提下，
重构能力信息的时域、观测模型和事件分布，确定是否存在安全主动探测的
净正控制价值区域，并使其在独立validation和final中复现。

## 必须保留

1. 不覆盖tag `direction5-voi-boundary-final`及其全部负结果；
2. 不删除新阶段中的零价值点、不安全probe、数值失败和物理失败；
3. no-probe区域与同一contract MPC保持数值等价；
4. Plant A使用完整非线性模型，Plant B使用原生ANDES；
5. 实际BESS POI power作为已知观测器输入；
6. power/ramp/delay的真值只能由评价器读取；
7. energy使用实测SoC计算，availability折算进deliverability；
8. 一次只运行一个受内存监控的episode。

## 允许的决定性模型修改

1. 将rolling MPC horizon与information-value validity horizon分离；
2. 安全约束仍对能力集鲁棒，控制价值对预注册事件分布取期望并报告尾部风险；
3. 使用完整、因果的actual-POI-power时序观测管，不再压缩为单一标量；
4. 能力变化后允许存在不含负荷事故的因果观测窗，后续负荷事件从独立分布抽样；
5. 可在development内改进物理时长归一化probe库、后验集观测管和缓存算法；
6. development probe幅值可在`0.0005–0.015 pu`内搜索，但每个候选必须先通过全能力集物理安全计算。
7. 允许比较两类因果probe：SG–IBR零和分配probe，以及在contract MPC已接近BESS保证功率且当前调频需求与probe同向时的control-aligned surplus probe。后者保持SG contract-safe命令不变，只有在全能力候选下均安全时才可使用。

## 禁止

- 不得为了显著性放大负荷事故或删除不利场景；
- 不得使用固定`HIGH_VALUE`标签代替因果VoI；
- 不得在validation/final结果产生后调整模型、场景、权重或阈值；
- 不得把development-only positive cell写成论文结论；
- 不得使用reduced surrogate代替native Plant B。

## 数据防火墙

```text
development: 8100–8299
validation:  9100–9299
final:      10100–10299
normal1h:  11100–11105
```

Validation和final seed不得用于development配置选择。

## 正面结果

只有同时满足以下条件才允许称为正结果：

- development和独立validation都存在非空正价值区；
- 主结果不使用人为uniform capability prior，而是报告完整break-even prior及一个非空先验模糊集`Pi`，并满足`inf_{pi in Pi} V(pi)>0`；
- 正区paired absolute net benefit的95%置信下界大于0；
- registered-formulation perfect-information value recovery点估计不低于25%；
- hard physical violations为0，频率安全相对contract MPC非劣；
- false optimistic certificate不高于1%；
- 零价值区probe rate不高于5%且与contract MPC等价；
- Plant A复现正区，Plant B至少正确复现正区或安全放弃。
- 低能力分支必须物理安全，且相对contract MPC的频率峰值增量不超过0.005 Hz，ACE和tie主指标恶化均不超过1%。

## 停止条件

若完成预注册development设计后仍无正区，或正区在一次独立validation中不复现，
则如实结束本重构，不通过再次修改场景强行获得正结果。
