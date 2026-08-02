# Codex唯一总Goal：方向1 Phase G终端可生存性重构与完整验证

请在当前真实Git仓库中连续执行本Goal。不要在内部阶段结束后等待用户再次发消息。

## 必须先读

完整阅读：

```text
research/direction1_phase_g_terminal_viability_full_validation/
```

下全部文件。

## 项目定位

项目统一名称：

```text
方向1 / DIRECTION1
```

不更换科学问题，不添加AI、RL、CBF或模式分类，不改用另一套算法。继续CDSR-MPC，但纠正终端、能力、延迟、能量和理论范围。

## 连续阶段

严格执行：

```text
G0→G1→G2→G3→G4→G5→G6→G7→G8→G9
```

只有命中明确停止条件才提前停止；即使停止，也必须完成负结果打包。

## 核心必须项

1. 冻结Phase F，并把G5解释修正为certificate formulation incompatibility，而非方向或方法类别失败。
2. 重算一步residual与terminal limit不相容，并修复certificate `all()`/`any()`逻辑。
3. 不再把全局事故/能力变化/估计器瞬态残差作为终端每步独立扰动。
4. 建立因果observer、结构化负荷误差、global prediction set和local terminal set。
5. 围绕负荷依赖平衡点构造终端集合。
6. 将场景预先划分为SUSTAINABLE、BRIDGE_ONLY和PHYSICALLY_INFEASIBLE。
7. 可持续域建立SG主导RPI/RCI；桥接域建立SG+BESS保证能力和能量的有限时域证书。
8. 若无慢速备用模型，bridge场景不得声称无限时域递归安全。
9. 修订CDSR-MPC，使SG机械、BESS实际延迟功率、实际爬坡、累计能量和terminal margin全部进入鲁棒约束。
10. 经验残差覆盖不得称为确定性“所有扰动”保证。
11. 实现真正rolling baselines和rolling Oracle。
12. 求解器p99必须小于半个控制周期；记录build与solve时间。
13. development/validation/final隔离；final后禁止调参。
14. 不得删除失败、降低标准或把物理不可行当solver失败。
15. Plant A和原生ANDES Plant B均需验证。

## 失败处理

任何失败按：

```text
代码→数值/求解器→参数来源→物理模型→方法→科学假设
```

处理。方法最多两轮development/validation修复；科学假设失败时停止，不临时换算法。

## 最终输出

生成：

```text
DIRECTION1_PHASE_G_TERMINAL_VIABILITY_FULL_VALIDATION_SINGLE_REVIEW_PACKAGE.zip
```

要求 `<512MB`，内容严格符合 `08_FINAL_REVIEW_PACKAGE_SPEC.md`。

完成后报告：ZIP路径、大小、SHA256、Git commit/status、G0–G9、H1–H5、sustainable/bridge分类、terminal/bridge certificate、最佳基线、known/OOD结果、solver/restoration/backup统计、最严重失败和最终研究状态。
