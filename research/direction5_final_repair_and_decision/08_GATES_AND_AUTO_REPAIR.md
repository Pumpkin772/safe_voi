# R0–R8 Gate与自动处理

## R0
统计、分母、Phase I结论可重算。
失败：EVIDENCE_NOT_AUDITABLE。

## R1
材料性和创新通过。
失败：PROBLEM_NOT_MATERIAL或NOVELTY_NOT_SUFFICIENT。

## R2
估计器、合同语义和基线通过。
失败：两轮修复；在线集合无信息价值则终止。

## R3
DCSV-CR真实滚动、hard violation 0、action 100%、实时。
失败：两轮formulation修复，不换算法。

## R4
至少有限时域合同/追索证书通过。
失败：收缩理论；全部为空则终止。

## R5
完整validation通过。
失败：两轮后终止，不运行final。

## R6
final lock和一次运行。

## R7
论文证据和声明边界完整。

## R8
ZIP<512MB；fresh-extract replay通过；只输出两个终态之一。

## 诊断顺序
```text
CODE
NUMERICAL/SOLVER
PARAMETER_SOURCE
PHYSICAL_MODEL
ESTIMATOR
METHOD
SCIENTIFIC_HYPOTHESIS
```

禁止：
-无依据调参；
-删除失败；
-放宽物理标准；
-改final seed；
-把not evaluated计为结果；
-临时加入AI/RL；
-创建后续phase逃避终态。
