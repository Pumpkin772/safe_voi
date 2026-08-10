# Gate与自动修复

## A0 平台
- normal1h基线通过；
- Plant A/B和dt通过。
失败：平台不可信则停止。

## A1 创新和材料性
- ≥2个power/ramp cells有perfect info value；
- 创新交叉未被覆盖。
失败：终止。

## A2 被动集合
- true containment≥95%；
- false optimism≤1%；
- no-excitation不收缩。
失败：两轮修复；仍失败终止。

## A3 安全探测
- hard violation=0；
- incremental frequency≤0.02Hz或2%；
- eligible episodes中≥50%集合宽度降低≥40%；
- false optimism≤1%。
失败：三轮development/validation内调整probe library/trigger；仍失败终止。

## A4 ACCR
-真滚动；
-action 100%；
-real-time；
-no truth；
-hard violation=0。
失败：两轮formulation修复。

## A5 理论
-至少有限时域安全探测与合同fallback证书。
失败：收缩声明；全部为空则终止。

## A6 Validation
- success drop≤1pp；
-frequency noninferiority；
- hard violation=0；
-fallback≤contract+1pp；
-materiality-positive cells中ACE或tie改善≥4%，CI lower>0；
-value recovery≥0.40，CI lower>0；
-cross-plant方向一致；
-normal1h通过。
失败：最多三轮预注册范围修复；仍失败终止，不运行final。

## A7 Final
-锁定后一次运行；
-不调参；
-known/OOD分开。

## A8 Package
-<512MB；
-fresh extract replay；
-唯一终态。

## 自动诊断顺序
```text
CODE
NUMERICAL/SOLVER
PARAMETER_SOURCE
PHYSICAL_MODEL
IDENTIFICATION
PROBE_DESIGN
CONTROL_FORMULATION
SCIENTIFIC_HYPOTHESIS
```

禁止：
-按final结果调参；
-删除不利结果；
-放宽安全标准；
-换算法；
-创建后续Phase。
