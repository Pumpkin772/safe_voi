# 方向1 Phase F：CDSR-MPC 科学收敛与投稿级完成

本启动包用于继续当前真实代码仓库中的 Phase E 项目。不要把本包解压到旧审查 ZIP 内部；应放入当前 Git 仓库：

```text
research/direction1_phase_f_cdsr_mpc/
```

本轮不是再次更换科学问题，也不是继续无依据调参。Phase E 已经完成了三项有价值的基础工作：

1. 建立了稳定、单位一致的 Plant A 和原生 ANDES Plant B；
2. 证明当前 IBR 能力知识在部分场景下具有控制价值；
3. 发现自然闭环数据下的被动能力集合和已测试主动探针均未达到预注册要求。

Phase E 的最终 G6 不能直接解释为科学问题或鲁棒路线失败。当前方法存在控制器内部状态未与实际 fallback 动作同步、延迟只取单一最坏值、能量能力未进入预测约束、有限时域 box propagation 被误称为 tube certificate、终端 box 未证明不变，以及 solver/fallback 计数未区分数学不可行与数值失败等问题。

本轮锁定唯一方法路线：

> **CDSR-MPC：Capability-and-Delay-Set Robust Model Predictive Control with Feasibility Restoration**

中文：

> **计及 IBR 保证能力包络与执行延迟集合的可行性恢复鲁棒模型预测二次频率控制**

请按 `CODEX_GOAL.md` 连续执行 F0–F9。只有达到明确停止条件时才提前结束，并仍输出完整负结果审查包。
