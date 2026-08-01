# 软件架构和接口契约

## 新目录

```text
src/direction1freq/
├─ controllers/
│  ├─ mpc_transaction.py
│  ├─ feasibility_restoration.py
│  ├─ cdsr_mpc.py
│  ├─ cdsr_supervisor.py
│  └─ sg_backup_invariant.py
├─ models/
│  ├─ delay_augmented_prediction.py
│  ├─ guaranteed_capability_envelope.py
│  └─ residual_uncertainty_set.py
├─ optimization/
│  ├─ robust_scenario_qp.py
│  ├─ robust_backup_set.py
│  └─ certificate_verification.py
└─ evaluation/
   ├─ solver_failure_taxonomy.py
   └─ failure_aware_statistics.py
```

## 核心API

### MPC proposal
```python
proposal = controller.propose(
    observation=obs,
    estimated_state=xhat,
    load_set=load_set,
    previous_applied_action=u_prev,
)
```

不得读取真能力或未来事件。

### Supervisor
```python
applied, decision = supervisor.select(
    proposal=proposal,
    observation=obs,
    backup_state=backup_state,
)
```

### Commit
```python
controller.commit_applied_action(applied)
```

commit必须在物理plant执行前后按统一约定调用，并在日志中核对。

### Diagnostics
每次更新必须输出结构化对象，不得从文本日志猜测：

```text
solver statuses
residuals
scenario count
terminal-set status
restoration status
fallback status
applied command
model previous command
hard-constraint margins
energy margins
delay vertices
solve time
```

## Review package可运行性

审查包根目录必须能够运行：

```bash
python 14_REPRODUCIBILITY/verify_manifest.py
python 14_REPRODUCIBILITY/reproduce_minimal.py
```

不得依赖原仓库之外的相对路径。

全量复现可依赖安装environment，但最小复现必须使用包内路径映射。
