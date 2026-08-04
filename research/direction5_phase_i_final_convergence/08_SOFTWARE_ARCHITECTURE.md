# 软件架构

## 新源码
```text
src/direction5freq/
├─ models/
│  ├─ plant_a_full.py
│  ├─ plant_b_andes_full.py
│  ├─ slow_reserve.py
│  └─ capability_contract.py
├─ estimation/
│  ├─ grid_load_observer.py
│  ├─ deliverability_set_mhe.py
│  └─ contract_violation_detector.py
├─ controllers/
│  ├─ dcsv_mpc_final.py
│  ├─ feasibility_restoration.py
│  └─ domain_supervisor.py
├─ theory/
│  ├─ terminal_set.py
│  ├─ bridge_certificate.py
│  └─ infeasibility_certificate.py
└─ evaluation/
   ├─ failure_aware_statistics.py
   └─ claim_evidence.py
```

## 阶段输出
```text
research_outputs_phase_i/
results_phase_i/
figures_phase_i/
logs_phase_i/
progress_phase_i/
```

## 每阶段状态
```text
progress_phase_i/Ix.json
```
包含：
- inputs；
- commit；
- commands；
- outputs；
- Gate；
- failures；
- repairs；
- next stage。

## 审查包
必须含完整source snapshot和所有依赖，不得依赖ZIP外部历史阶段文件。
