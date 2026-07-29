# README FIRST — Direction 5 Phase B1

本启动包针对以下已完成审查包：

```text
D5_FROM_SCRATCH_SD_BMPC_REVIEW_PACKAGE(1).zip
```

审查包 SHA256：

```text
2e1c3bfc380c57172a5d96663a6ab90cf95b79511f60cefce73ce4c38e2f04a9
```

其中记录的冻结 Phase-6 源码 commit：

```text
20f652f5f8b180a2518798d0ed85aa3f48212908
```

## 本轮为什么只做瓶颈审计

当前工程实现已经完整，但现有 SD-BMPC 还不能支持投稿级核心结论：

- proposed `P` 的总体 frequency IAE 为约 `1.1956 Hz·s`；
- 单模型在线 RLS-MPC `B2` 为约 `1.0227 Hz·s`；
- LQI-only `B0` 为约 `1.0435 Hz·s`；
- `P` 的模式准确率约 `0.3545`，Macro-F1 约 `0.1519`；
- OOD AUROC 约 `0.5213`，仅检测到 `15/100` 个 OOD episode；
- `no-transition-prior` 和 `no-worst` 均优于完整 `P`；
- 当前 `B4` 只是“真实模式选择的辨识 ARX”，不是精确非线性 Oracle。

因此，下一轮不能直接继续调权重或盲目实现新算法。必须先回答：

1. 黑箱 IBR 在当前频率场景中是否真的有足够控制价值？
2. 主要瓶颈是模型失配、被动可辨识性，还是控制器过度保守？
3. 当前物理模式分类是否与最优频率控制决策真正相关？

## 阅读顺序

1. `00_CURRENT_REVIEW_FINDINGS.md`
2. `01_PHASE_B1_PROJECT_PLAN.md`
3. `02_BOTTLENECK_AUDIT_MATH_AND_METRICS.md`
4. `03_IMPLEMENTATION_AND_API_SPEC.md`
5. `04_EXPERIMENT_PROTOCOL.md`
6. `05_REVIEW_PACKAGE_SPEC.md`
7. `CODEX_GOAL.md`

## 本轮唯一交付

```text
D5_PHASE_B1_BOTTLENECK_AUDIT_REVIEW_PACKAGE.zip
```

必须小于 512 MB。
