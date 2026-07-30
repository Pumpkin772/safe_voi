# 方向五 Phase C：完整重建与方法完成启动包

## 项目定位

本启动包用于在当前 `D5_PHASE_B2_SCIENTIFIC_HARDENING_REVIEW_PACKAGE.zip` 的基础上，完成一次**从科学问题、物理模型、统计证据、控制方法到论文级结果的连续重建**。

新的主问题锁定为：

> 当参与多区域二次频率调节的黑箱 IBR/BESS，其对外可用的功率头寸、爬坡能力、响应延迟、能量状态或服务可用性发生未通知变化时，调度控制器能否仅利用外部可测信号，在错误模型造成实质频率、ACE 或联络线责任损失之前，识别“控制相关能力变化”，并安全地重新分配调频责任？

本项目不以恢复设备真实 OEM 模式标签为目标，而以识别会改变预测、可行控制集合和最优调频动作的 **control-relevant capability regime** 为目标。

## 使用方法

1. 将本文件夹完整放到当前真实代码仓库：

```text
research/phase_c_full_rebuild_and_method_completion/
```

2. 让 Codex 先阅读本目录全部文件。
3. 将 `CODEX_GOAL.md` 设置为唯一总 Goal。
4. Codex 必须按内部阶段连续执行；阶段间自行检查，不等待用户再次发送 Goal。
5. 最终只提交：

```text
DIRECTION5_PHASE_C_FULL_REBUILD_AND_METHOD_COMPLETION_SINGLE_REVIEW_PACKAGE.zip
```

且大小必须小于 512 MB。

## 阅读顺序

1. `00_CURRENT_PACKAGE_EXPERT_REVIEW.md`
2. `01_MASTER_EXECUTION_PLAN.md`
3. `02_SCIENTIFIC_QUESTION_AND_NOVELTY.md`
4. `03_CORRECTED_PHYSICAL_MATHEMATICAL_MODEL.md`
5. `04_UNITS_PARAMETERS_AND_VALIDATION.md`
6. `05_SCIENCE_GATES_AND_BRANCHING_LOGIC.md`
7. `06_METHOD_THEORY_AND_IMPLEMENTATION_SPEC.md`
8. `07_EXPERIMENT_AND_STATISTICS_PROTOCOL.md`
9. `08_SOFTWARE_ARCHITECTURE_AND_STAGE_CONTRACTS.md`
10. `09_FINAL_REVIEW_PACKAGE_SPEC.md`
11. `CODEX_GOAL.md`

## 不允许的做法

- 不得沿用当前 `PROBLEM_NOT_MATERIAL` 结论；该结论受单位错误、Oracle强度、信息不公平、成本口径和统计门控影响，必须撤回。
- 不得把“模式分类准确率”当作论文核心贡献。
- 不得为了得到优势而削弱 PI、固定 MPC、RLS-MPC 或其他基线。
- 不得读取真实 hidden regime、SoC、内部参数或未来事件用于普通控制器。
- 不得用 final seeds 调参。
- 不得删除失败实验、求解失败或不利结果。
- 不得通过降低频率安全标准、缩短仿真时间或改变成本权重掩盖失败。
- 不得把未运行的方法记为 scientific failure；必须标为 `not_evaluated`。
