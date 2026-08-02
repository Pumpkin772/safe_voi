# Gate、失败判据与自动处理规则

## G0：Phase F重分类
通过：一步不相容、备用矛盾和代码逻辑均可重算。

## G1：科学范围
通过：至少两个非delay机制、两个SG tension仍有材料性。
失败：停止为 `PROBLEM_SCOPE_TOO_WEAK`。

## G2：观测器与不确定性
通过：global/local validation覆盖≥95%，无future leakage，本地集合不直接摧毁terminal。
失败：两轮修复后停止。

## G3：可持续/桥接分类
通过：所有场景预先分类；静态和能量LP可复现。
失败：模型/参数无物理来源则停止。

## G4：终端/桥接证书
通过：非空可持续集合和至少一个有效桥接证书。
失败：两轮合理反馈/集合表示后停止。

## G5：CDSR修订
通过：完整滚动闭环、hard violations=0、action availability=100%。
失败：只修formulation/solver，不换算法。

## G6：validation性能
通过：完整性能、可靠性和实时Gate。
失败：最多两轮；仍失败生成负结果，不用final。

## G7：理论一致
通过：证书、代码和声明一致。
失败：收缩理论；若连有限时域也不成立则停止。

## G8：final
final后禁止调参；失败如实保留。

## G9：包
小于512MB，最小复现和certificate在新目录通过。

## 统一自动诊断顺序

```text
CODE
NUMERICAL
SOLVER
PARAMETER_SOURCE
PHYSICAL_MODEL
METHOD
SCIENTIFIC_HYPOTHESIS
```

禁止：删结果、改final seeds、降低标准、临时加AI/RL、把物理不可行记为solver失败。
