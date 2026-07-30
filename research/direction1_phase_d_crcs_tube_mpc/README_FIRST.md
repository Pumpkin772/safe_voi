# 方向1 Phase D：黑箱 IBR 控制相关能力集合自适应管束 MPC

本启动包用于接续当前审查包：

`DIRECTION5_PHASE_C_FULL_REBUILD_AND_METHOD_COMPLETION_SINGLE_REVIEW_PACKAGE.zip`

从本阶段起，项目统一称为 **方向1**，不再使用 Direction 5 命名。旧压缩包与旧分支仅作为只读证据保留。

## 本轮总体裁决

- 高层科学问题值得继续；
- 当前 Plant A 可作为透明开发模型，但仍需规范控制周期、测量与延迟；
- 当前 Plant B 存在功率平衡和交叉验证缺陷，不能作为论文验证模型；
- 当前所谓 `proposed_set_adaptive_mpc`、`nominal_mpc`、`rls_adaptive_mpc`、`robust_capability_set_mpc` 多数不是实际 MPC；
- C5 被动可辨识性结论因非因果窗口和合成激励而失效；
- 当前最终负方法结果不能作为可靠科学结论；
- 下一阶段不再探索多个算法，而是固定实现一条问题驱动路线：

> **CRCS-TMPC：Control-Relevant Capability-Set Adaptive Tube MPC**  
> 面向控制相关能力集合的自适应管束模型预测多区域二次频率控制。

## Codex 阅读顺序

1. `00_CURRENT_REVIEW_AND_VERDICT.md`
2. `02_LOCKED_SCIENTIFIC_QUESTION_AND_HYPOTHESES.md`
3. `03_CORRECTED_PLANT_MODELS.md`
4. `04_METHOD_SPEC_CRCS_TUBE_MPC.md`
5. `05_THEORY_AND_PROOFS_SPEC.md`
6. `06_LITERATURE_AND_NOVELTY_PROTOCOL.md`
7. `07_EXPERIMENT_AND_STATISTICS_PROTOCOL.md`
8. `08_SOFTWARE_ARCHITECTURE_AND_FILE_CONTRACTS.md`
9. `09_GATES_FAILURE_AUTO_REPAIR.md`
10. `10_FINAL_REVIEW_PACKAGE_SPEC.md`
11. `01_MASTER_EXECUTION_PLAN.md`
12. `CODEX_GOAL.md`

## 使用方式

将本目录放入当前真实代码仓库：

```text
research/direction1_phase_d_crcs_tube_mpc/
```

然后把 `GOAL_TO_SEND_CODEX.txt` 全文发送给 Codex。Codex 应一次性按 D0–D9 连续执行，只有致命科学失败才可提前停止，但仍必须生成完整负结果审查包。
