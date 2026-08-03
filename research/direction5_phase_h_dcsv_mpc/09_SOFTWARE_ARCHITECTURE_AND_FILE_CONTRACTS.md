# 软件架构和文件契约

## 新源码

```text
src/direction5_freq/
├─ estimation/
│  ├─ grid_disturbance_observer.py
│  ├─ capability_set_estimator.py
│  └─ load_capability_separator.py
├─ models/
│  ├─ sustainability_classifier.py
│  ├─ load_parameterized_equilibrium.py
│  └─ persistent_load_error_model.py
├─ controllers/
│  ├─ dcsv_mpc.py
│  ├─ bridge_viability_mpc.py
│  ├─ domain_supervisor.py
│  └─ feasibility_restoration.py
├─ optimization/
│  ├─ terminal_set.py
│  ├─ bridge_certificate.py
│  └─ infeasibility_certificate.py
└─ evaluation/
   ├─ coverage_statistics.py
   ├─ failure_aware_statistics.py
   └─ claim_evidence.py
```

## 阶段输出

```text
research_outputs_phase_h/
results_phase_h/
figures_phase_h/
logs_phase_h/
progress_phase_h/
```

每个阶段必须有：
```text
progress_phase_h/Hx.json
```

包含：
- inputs；
- commit；
- commands；
- outputs；
- gate；
- failures；
- repairs；
- next stage。

## 完整源码快照

下一审查包必须包含：
- Phase E/F/G/H所有被导入脚本；
- `pyproject.toml`；
- configs；
- tests；
- reproduce scripts。

禁止出现“最小复现能跑，但完整阶段脚本缺依赖”的情况。
