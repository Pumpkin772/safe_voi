# 方向1 Phase E：科学恢复、材料性验证与能力感知频率控制

本目录是下一轮 Codex 的唯一治理包。它针对
`DIRECTION1_PHASE_D_CRCS_TUBE_MPC_SINGLE_REVIEW_PACKAGE.zip`
中发现的模型、控制基线、因果评价和 Gate 逻辑问题，提供一个总 Goal 和多个内部阶段。

## 必须先读的顺序

1. `00_CURRENT_PACKAGE_EXPERT_REVIEW.md`
2. `01_MASTER_EXECUTION_PLAN.md`
3. `02_CORRECTED_SCIENTIFIC_QUESTION_AND_HYPOTHESES.md`
4. `03_MODEL_AND_BASELINE_REBUILD_SPEC.md`
5. `04_ORACLE_MATERIALITY_AND_CAUSAL_INFORMATION_PROTOCOL.md`
6. `05_PASSIVE_AND_ACTIVE_CAPABILITY_IDENTIFICATION_SPEC.md`
7. `06_FINAL_METHOD_BRANCH_SPEC.md`
8. `07_THEORY_AND_PROOFS_SPEC.md`
9. `08_EXPERIMENT_AND_STATISTICS_PROTOCOL.md`
10. `09_SOFTWARE_ARCHITECTURE_AND_STAGE_CONTRACTS.md`
11. `10_GATES_FAILURE_AND_AUTO_REPAIR.md`
12. `11_FINAL_REVIEW_PACKAGE_SPEC.md`
13. `CODEX_GOAL.md`

## 锁定原则

- 项目统一命名为“方向1”/`DIRECTION1`。
- 当前 Phase D 的 `PASSIVE_CAPABILITY_SET_NOT_SUPPORTED` 只能作为旧协议的失败记录，不能继续作为科学结论。
- 不允许在名义闭环不稳定、材料性尚未证明、评价时间定义错误的前提下继续设计控制器。
- 先验证科学问题是否有实质价值，再判断被动数据是否足够；只有在 Gate 证据明确后，自动选择一个最终方法分支。
- 最终只允许一个 proposed method 进入 final test；不允许临时堆叠 PPO、CBF、Koopman、GNN 等无必要方法。
- final seeds、final scenario manifest 和统计规则锁定后不得修改。

## 最终输出

Codex 最终生成：

`DIRECTION1_PHASE_E_SCIENCE_RECOVERY_AND_CAPABILITY_CONTROL_SINGLE_REVIEW_PACKAGE.zip`

必须小于 512 MB，并符合 `11_FINAL_REVIEW_PACKAGE_SPEC.md`。
