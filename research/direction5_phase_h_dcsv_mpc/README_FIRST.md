# 方向5 Phase H：DCSV-MPC 科学重建与投稿级完成

本启动包对应当前审查对象（其 `DIRECTION1` 名称仅作为历史旧命名保留）：

```text
DIRECTION1_PHASE_G_TERMINAL_VIABILITY_FULL_VALIDATION_SINGLE_REVIEW_PACKAGE（历史旧命名）
```

不要把本包解压到旧审查 ZIP 内部。应放入当前真实 Git 仓库：

```text
research/direction5_phase_h_dcsv_mpc/
```

Phase G 的有效成果可以保留：

- 两区域 Plant A；
- 因果公共测量接口；
- 注册延迟顶点；
- 全局预测误差与局部误差分开的意识；
- H1 的初步材料性结果；
- 完整失败保存、manifest 和 Gate 治理。

但 Phase G 的 G2 负结论不能继续作为科学证据。原因不是简单“终端集合太小”，而是：

1. 实际 near-terminal 窗口没有执行注册的无饱和、无 GRC、无 fallback 等筛选；
2. 可持续/桥接/物理不可行分类本应先于局部终端集合，却被放在 G2 之后；
3. 负荷估计误差被近似为每周期独立重复的加性冲击，而不是持续未知参数/慢变状态；
4. 状态与负荷观测器使用命令预测 BESS，却没有统一建模执行延迟和能力变化，容易把执行器失配吸收到负荷估计；
5. validation 窗口过少，经验覆盖不能被当作具有统计可信度的 95% 集合；
6. 当前审查包缺少其 G2 所依赖的 Phase E/F 脚本，无法从该 ZIP 独立完整重跑 G2。

本轮锁定唯一技术路线：

> **DCSV-MPC：Disturbance–Capability-Separated Viability Model Predictive Control**

中文：

> **扰动–能力分离的可持续/桥接域模型预测多区域二次频率控制**

它不是“分类器 + MPC”的拼接。其核心是先从公共测量中把外部净负荷不平衡与设备执行能力变化分开，再根据可持续域、有限能量桥接域和物理不可行域选择一致的预测与终端架构。

请按 `CODEX_GOAL.md` 自动连续执行 H0–H9。只有命中明确科学停止条件时才提前终止，并仍生成完整负结果审查包。

后续新目录、分支、结果和审查包统一使用 `方向5 / DIRECTION5 / direction5`。

## 项目命名锁定

从本阶段起，本项目统一命名为：

```text
中文：方向5
英文标识：DIRECTION5
代码/目录标识：direction5
```

此前压缩包、分支或文件中出现的 `DIRECTION1`、`ST-BOUND` 等名称仅作为历史旧命名保留，不得用于后续新文件、新分支、新结果目录和最终审查包。
