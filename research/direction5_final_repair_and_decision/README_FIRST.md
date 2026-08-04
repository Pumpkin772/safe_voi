# 方向5：最终修复与裁决

## 命名锁定

```text
中文：方向5
英文标识：DIRECTION5
代码/目录标识：direction5
```

## 本包用途

本包针对：

```text
DIRECTION5_PHASE_I_FINAL_CONVERGENCE_SINGLE_REVIEW_PACKAGE.zip
```

Phase I 的“决定性负证据”不能成立。它同时存在：

- 统计主指标错误；
- 缺少最关键的 contract-only rolling MPC 对照；
- 在线能力集合只改变目标权重，没有形成清晰的自适应控制贡献；
- 能力估计器并非真正的 set-membership/MHE；
- solver/fallback 分母和分类不清；
- normal1h 出现异常频率而未进入方法Gate；
- Plant B设计范围过窄；
- 当前方法与理论的模型误差/延迟覆盖并不完全一致。

本轮不是新的无止境 Phase。它是方向5的**最终修复与裁决计划**。

Codex必须在一个总Goal中连续完成 R0–R8，并最终只输出以下二者之一：

```text
PAPER_READY_WITH_BOUNDED_CLAIMS
```

或：

```text
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```

不得再创建后续 Phase 逃避结论。

## 最终方法

唯一允许的方法路线为：

> **DCSV-CR-MPC：Disturbance–Capability-Separated Contract-Recourse MPC**

中文：

> **扰动–能力分离的合同安全–性能追索模型预测多区域二次频率控制**

其核心不是把更多算法堆在一起，而是：

1. 合同保证能力用于硬安全；
2. 在线可交付能力只用于可撤销的性能增益；
3. 对“额外能力按预期交付”和“额外能力突然不可用”同时预测；
4. 额外能力失效时由SG/慢速备用进行未来追索；
5. 能力跌破合同下界时明确进入合同违约域，不作无条件安全承诺。
