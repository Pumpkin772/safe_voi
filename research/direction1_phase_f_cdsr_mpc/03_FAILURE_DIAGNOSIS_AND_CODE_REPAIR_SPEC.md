# Phase E G6失败诊断与代码修复规范

## 1. 动作事务语义

### 禁止
```python
solve()
    -> internal previous_action = candidate
controller
    -> candidate rejected
    -> execute fallback
```

### 必须
```python
proposal = optimizer.propose(...)
applied = supervisor.select(proposal, fallback)
optimizer.commit_applied_action(applied)
delay_model.commit(applied)
```

`propose`必须是无物理副作用的。warm-start数值变量可以更新，但不得修改已执行动作、延迟管线或物理历史。

## 2. 求解状态分类

每个控制周期必须输出：

```text
primary_status
secondary_status
primary_primal_residual
primary_dual_residual
secondary_primal_residual
secondary_dual_residual
mathematical_infeasible
numerical_failure
terminal_reject
restoration_used
backup_used
previous_applied_action
previous_model_action
history_match
consecutive_backup_count
```

## 3. 验收规则

- `OPTIMAL_INACCURATE`只有在显式约束残差低于容差时才接受。
- `primal_infeasible`与`max_iter`不得合并。
- 终端集合拒绝不是solver infeasibility。
- fallback是一种控制模式，不等同于科学失败。
- 若执行fallback，下一周期模型必须使用fallback动作。

## 4. Feasibility restoration

采用词典序两阶段：

### Stage 1
最小化performance slack：

\[
\min \|\epsilon_f\|_1+\|\epsilon_{\rm ACE}\|_1+\|\epsilon_{\rm tie}\|_1
\]

保持以下约束完全硬：

- SG/BESS功率；
- BESS总PFR+SFR；
- ramp；
- energy；
- delay pipeline；
- terminal backup admissibility。

### Stage 2
固定最小slack后优化正常代价。

不得通过放松物理能力“恢复”可行性。

## 5. 必须新增的测试

1. successful proposal accepted；
2. successful proposal terminal-rejected；
3. primary solver failure, secondary success；
4. both solvers fail, restoration success；
5. restoration fail, SG fallback；
6. two consecutive fallback；
7. fallback followed by recovered QP；
8. 2s near-full-period delay；
9. 4s delay；
10. actual/model previous action equality at every step；
11. no stale candidate enters delayed dynamics；
12. no physical hard constraint softened。
