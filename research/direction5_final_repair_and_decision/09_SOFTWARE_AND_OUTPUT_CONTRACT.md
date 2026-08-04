# 软件和输出契约

## 新源码

```text
src/direction5freq/
├─ estimation/
│  ├─ grid_load_mhe.py
│  ├─ deliverability_set_membership.py
│  └─ contract_violation_detector.py
├─ controllers/
│  ├─ dcsv_cr_mpc.py
│  ├─ recourse_tree.py
│  ├─ anti_windup_pi.py
│  ├─ contract_robust_mpc.py
│  ├─ adaptive_mpc.py
│  └─ oracle_mpc.py
├─ theory/
│  ├─ recourse_certificate.py
│  ├─ terminal_set.py
│  └─ impossibility.py
└─ evaluation/
   ├─ corrected_statistics.py
   ├─ solver_taxonomy.py
   └─ claim_evidence.py
```

## 阶段结果

```text
research_outputs_final/
results_final/
figures_final/
logs_final/
progress_final/
```

## 每阶段状态

```text
progress_final/Rx.json
```

包含：
- inputs；
- commands；
- commit；
- outputs；
-Gate；
-failures；
-repairs；
-next stage。

## 终态

禁止含糊的“需要下一步”。
只能：
```text
PAPER_READY_WITH_BOUNDED_CLAIMS
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```
