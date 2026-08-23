# 方向5：安全能力信息正价值域重构

```text
DIRECTION5_SAFE_VOI_POSITIVE_REGION_REBUILD
direction5_safe_voi_positive_region_rebuild
```

本项目从已冻结的 `PAPER_READY_NO_PROBE_BOUNDARY` 结果出发，不覆盖旧结论。
新的科学问题是：在仍然满足鲁棒物理安全、不读取未来事件真值的前提下，
若信息价值按其真实有效期跨多个滚动MPC周期计算，并使用完整POI功率序列维持
后验集，是否会出现可独立复现的安全正净价值区域？

这是一个新的、预注册的后续研究，不是对旧数据的重新调参。

## 冻结的前任结果

- Git tag: `direction5-voi-boundary-final`
- final status: `PAPER_READY_NO_PROBE_BOUNDARY`
- registered points: `1920`
- positive points: `0`
- selected probe: `NONE`

## 当前阶段

```text
R0_PREREGISTERED_REIMPLEMENTATION_STARTED
```

本阶段只使用development seeds。Validation和final在锁定模型、探测库、目标、统计和
停止条件之前不得运行。
