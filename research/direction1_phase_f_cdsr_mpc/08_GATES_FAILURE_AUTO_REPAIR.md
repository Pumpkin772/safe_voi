# Phase F Gates、失败判据和自动处理

## G0 Forensic
- Phase E冻结；
- action-history bug、solver分类和review replay得到明确结论。

失败：证据不可恢复。停止。

## G1 Corrected science
- development-only baseline；
- H1修正后仍在≥2 mechanisms、≥2 SG tensions成立。

失败：`PROBLEM_NOT_MATERIAL_AFTER_CORRECTION`，停止。

## G2 Transaction and solver
- actual/model history mismatch=0；
- controller action availability=100%；
- failure taxonomy complete。

失败：最多两轮代码/数值修复；仍失败停止。

## G3 Model set
- delay approximation通过；
- validation residual coverage≥95%；
- power/ramp/energy模型与physical plant一致。

失败：扩大集合或增加顶点；若退化为SG-only且无价值，停止。

## G4 CDSR implementation
- 真滚动MPC；
- 全顶点共同控制；
- physical hard violations=0；
- no truth leakage。

失败：最多两轮 formulation修复，不换算法。

## G5 Certificate
- robust backup set非空；
-独立验证通过；
-理论与代码一致。

失败：允许收缩理论；若连有限时域可行性也无法建立，停止。

## G6 Validation
- success drop≤2pp；
- failure-aware不劣；
- ≥2/3指标改善≥8%且CI>0；
- hard violations=0；
- action availability=100%；
- unresolved mathematical infeasibility≤0.1%；
- fallback≤1%且无级联；
- p99<0.5Ts；
- Plant A/B一致。

失败：两轮development/validation修复；不得改科学问题或评价标准。仍失败生成负结果包。

## G7 Final lock
- configs、manifest、hash、seeds锁定；
- final前全部测试通过。

失败：修manifest，不能运行final。

## G8 Final evidence
- known/OOD完整；
-不删除失败；
- claims逐条有证据。

失败：如实报告，不回调算法。

## G9 Package
- <512MB；
- minimal replay在新临时目录通过；
- manifest/Git clean；
-全部必需文件齐全。

失败：只修打包与文档，不改科学结果。

## 自动诊断顺序

任何失败先分类：

```text
CODE
NUMERICAL
SOLVER
PARAMETER_SOURCE
PHYSICAL_MODEL
METHOD
SCIENTIFIC_HYPOTHESIS
```

禁止：
- 无依据扫权重；
- 删除不利episode；
- 修改final seed；
- 降低成功阈值；
- 把not_evaluated记作失败或成功；
- 在CDSR失败后临时增加RL/AI。
