# 统计和基线修正规范

## 1. 主指标

禁止使用：
\[
\mathrm{mean}\left((J_b-J_p)/|J_b|\right)
\]
作为主结论。

使用：

### Paired absolute difference
\[
\Delta_{c,s}=J_{b,c,s}-J_{p,c,s}.
\]

### Scenario-balanced aggregate mean
\[
\bar J_m=\sum_c w_c\frac{1}{n_c}\sum_s J_{m,c,s}.
\]

### Aggregate relative improvement
\[
RI=(\bar J_b-\bar J_p)/\bar J_b.
\]

### Hierarchical bootstrap
-重采样design cell；
-重采样seed cluster；
-同一scenario的paired methods保持配对。

## 2. Success-first

先报告：
- both success；
- only proposed fails；
- only baseline fails；
- both fail；
- not evaluated；
- physically infeasible；
- contract violation。

连续指标：
- both-success；
- failure-aware sensitivity；
-不能掩盖成功率差异。

## 3. Solver denominator

每个控制决策均计为：
```text
optimization_attempt
```

无论：
- primary成功；
- restoration；
-fallback；
-exception；
-empty sequence。

必须满足：
\[
N_{\rm attempt}
=
N_{\rm primary accepted}
+
N_{\rm restoration accepted}
+
N_{\rm backup}
+
N_{\rm unhandled}.
\]

## 4. 必须基线

1. SG-only anti-windup PI；
2. fixed-allocation anti-windup PI；
3. nominal offset-free MPC；
4. contract-only robust rolling MPC；
5. model-adaptive/RLS MPC；
6. DCSV-CR-MPC；
7. true-capability Oracle。

归因创新的首要比较：
```text
DCSV-CR-MPC vs contract-only rolling MPC
```

## 5. Normal1h

必须预注册频率质量：
- peak；
-RMS；
-ACE；
-tie；
-terminal；
-fallback；
-SoC。

出现>1Hz等异常必须单独诊断，不能仅以“硬设备约束未违反”通过。
