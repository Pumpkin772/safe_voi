# Phase H Gate 与自动处理

## H0
旧证据可独立复现、错误可定位。
失败：证据不可恢复则停止。

## H1
科学问题可证伪且创新交叉未被完整覆盖。
失败：创新不足则停止，不换方法包装。

## H2
所有场景预分类；功率平衡；非空可持续域；桥接能量可解释。
失败：物理参数修正一次；仍失败则收缩/终止。

## H3
disturbance observer无漂移；capability set coverage≥95%；false shrinkage≤5%；无泄露。
失败：最多两轮同框架修复；结构不可辨识机制转鲁棒处理。

## H4
terminal窗口物理干净；validation统计覆盖达标；局部集合与持续负荷模型一致。
失败：增加样本/修observer；不能直接放宽terminal。

## H5
DCSV真实滚动优化；动作100%可用；硬约束0违反；实时。
失败：两轮数值/formulation修复；不换算法。

## H6
至少有限时域证书；可持续/桥接/不可行理论与代码一致。
失败：收缩声明；证书全部为空则停止。

## H7
success下降≤2pp；failure-aware不劣；2/3指标改善≥8%且CI>0；硬约束0；unsolved≤0.1%；fallback≤1%；p99<0.5Ts；Plant A/B一致。
失败：两轮后生成负结果，不运行final。

## H8
final锁定后一次运行；不回调算法；claim-evidence完整。

## H9
ZIP<512MB；完整source；minimal replay在新目录通过；manifest/Git clean。

## 失败诊断顺序

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
- 无依据调参；
- 删除失败；
- 放宽物理约束；
- 改final seed；
- 将not_evaluated计为失败/成功；
- DCSV失败后临时加入RL/AI。
