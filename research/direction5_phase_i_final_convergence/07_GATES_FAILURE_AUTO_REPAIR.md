# Phase I Gate与自动处理

## I0
Phase H缺陷可独立复现。
失败：旧证据不可恢复则终止。

## I1
科学范围和创新足够。
失败：NOVELTY_NOT_SUFFICIENT。

## I2
Plant A/B、完整闭环、normal1h和capability change事件通过。
失败：两轮代码/数值修复；Plant B仍失败则终止。

## I3
load/capability separation和deliverability set通过：
- delay coverage≥95%；
- false optimism≤1%；
- no-excitation不虚假收缩；
- contract floor已验证。
失败：两轮同框架修复；结构不可辨识量转鲁棒集合。

## I4
DCSV完整滚动MPC：
- action 100%；
- hard violation 0；
- no truth leakage；
- bridge clock/energy正确；
- realtime。
失败：两轮formulation修复，不换算法。

## I5
至少有限时域理论与不可保证边界通过。
失败：收缩声明；全部证书为空则终止。

## I6
validation主Gate通过。
失败：两轮后终止方法，禁止运行final和新Phase。

## I7
final锁定后一次运行，不回调。

## I8
包完整、<512MB、fresh-extract minimal replay通过。

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
-临时换AI/RL；
-创建后续Phase逃避结论。
