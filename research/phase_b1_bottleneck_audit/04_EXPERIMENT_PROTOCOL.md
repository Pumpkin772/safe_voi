# Phase B1 Experiment Protocol

## 1. 数据和种子隔离

旧 Phase-6 final 结果只能用于审查动机，禁止用于 Phase B1 调参。

新增：

```text
phase_b1_smoke:       300–301
phase_b1_validation:  400–409
phase_b1_final:       3000–3029
phase_b1_ood_final:   3000–3049
```

B5求解器和 counterfactual 配置只能在 smoke/validation 上调试，final 只运行一次。

## 2. 场景

至少覆盖：

1. nominal stochastic；
2. 正负 0.02/0.04/0.06/0.08 pu load step；
3. nominal→sluggish；
4. nominal→derated；
5. nominal→unavailable；
6. multi-switch；
7. load step 与 mode change 同时发生；
8. high measurement noise；
9. OOD asymmetric limit；
10. OOD time-varying delay；
11. unavailable + double-step。

每个场景运行 SG Level A/B/C。

## 3. 方法

### 核心方法

- B0 LQI-only；
- B2 RLS-MPC；
- B4 truth-mode identified-ARX；
- B5 exact nonlinear Oracle；
- P_old frozen SD-BMPC。

### 受控反事实

- C0 true-ARX expected-cost；
- C1 true-ARX + old worst-cost；
- C2 perfect-belief current-MPC；
- C3 current-belief expected-cost；
- C4 gradual-authority；
- C5 no-sticky/window-likelihood。

## 4. 必须输出的表

```text
problem_materiality.csv
oracle_gap.csv
closed_loop_prediction_error.csv
constraint_activation.csv
information_gramian.csv
pairwise_separation.csv
identifiability_delay.csv
source_confusion.csv
control_design_decomposition.csv
per_episode_metrics.csv
statistical_tests.csv
solver_metrics.csv
```

## 5. 必须输出的图

1. B0/B4/B5 across SG levels；
2. exact-vs-ARX prediction errors；
3. B4–B5 oracle gap；
4. Gramian information over time；
5. pairwise likelihood separation；
6. load-vs-mode confusion；
7. detection lower bound vs frequency-critical window；
8. worst-cost conservatism；
9. binary fallback vs gradual authority；
10. bottleneck decision summary；
11. solver timing；
12. worst retained failures。

## 6. 决策顺序

```text
B5 cannot materially beat B0
    -> PROBLEM_NOT_MATERIAL

B5 materially beats B0, B4 far behind B5
    -> MODEL_MISMATCH_DOMINANT

B4 close to B5, passive evidence cannot identify in time
    -> IDENTIFIABILITY_DOMINANT

B4 and passive diagnosis adequate, P still poor
    -> CONTROL_DESIGN_DOMINANT
```

允许 combined 结论，但必须指定 primary bottleneck。
