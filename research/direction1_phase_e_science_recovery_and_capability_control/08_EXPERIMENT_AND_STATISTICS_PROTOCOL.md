# 实验、统计、消融、鲁棒性与失败分析协议

## 1. 数据划分

```text
development seeds: 0–49
validation seeds: 100–149
final seeds: 1000–1099
```

具体数量可根据计算量调整，但：

- 三者必须不重叠；
- final manifest冻结后不得调用final结果调参；
- Plant A与Plant B可使用映射seed，但必须记录。

## 2. 因素必须显式独立

禁止使用 `seed % n` 同时决定多个物理因素。

实验manifest必须显式包含：

- plant；
- load profile/seed；
- disturbance area、sign、magnitude、time；
- SG reserve level；
- SFR period；
- measurement noise；
- communication delay/jitter/dropout；
- initial SoC；
- capability mechanism；
- change magnitude/time；
- known/OOD；
- method；
- solver seed。

使用全因子、分层随机或LHS，并在 `DESIGN_BALANCE_REPORT.md` 中证明无混杂。

## 3. 场景

### 3.1 正常运行

- 至少1 h净负荷波动；
- 多种频谱和相关性；
- 无能力变化、单次变化、缓慢漂移；
- 评估频率RMS、ACE、里程、SoC和误报。

### 3.2 事故

- 0.02/0.05/0.08 pu阶跃；
- 300–600 s；
- 事故前/同时/事故后能力变化；
- 连续双事故；
- 区域1/区域2；
- 上/下扰动。

### 3.3 能力机制

Known：

- headroom-only；
- ramp-only；
- delay-only；
- energy-only；
- availability-only。

OOD：

- 非对称上下能力；
- 复合变化；
- 三阶或不同时间常数动态；
- 慢漂移+跳变；
- 丢包/随机延迟；
- P/Q共享能力变化。

### 3.4 结构不可辨识负控制

- 能力下降但命令从不接近边界；
- OEM标签变化但外部行为不变；
- no-change；
- load-only。

## 4. 方法

至少包括：

1. SG-only ACE PI/LQI；
2. fixed allocation PI；
3. nominal MPC；
4. RLS adaptive MPC；
5. worst-case capability-set tube MPC；
6. current-capability rolling Oracle；
7. selected proposed；
8. proposed关键消融。

所有MPC必须符合真正MPC代码审计。

## 5. 物理成功判据

按场景预注册阈值，至少检查：

- `max_abs_frequency_hz`；
- `max_abs_rocof_hz_s`；
- `terminal_frequency_mean_hz`；
- `terminal_ace_mean_pu`；
- `terminal_tie_mean_pu`；
- SG/BESS功率、GRC、爬坡、能量、SoC；
- solver连续可用；
- fallback安全。

终端窗口建议最后30–60 s。

## 6. 指标

### 6.1 频率与区域责任

- nadir/peak；
- RoCoF；
- frequency IAE、RMS、P95；
- ACE IAE/RMS；
- tie-line IAE与计划恢复；
- settling/recovery time。

### 6.2 资源与经济

- SG/BESS mileage；
- BESS throughput与SoC偏移；
- SG reserve使用；
- probe mileage/energy（分支A）；
- 物理单位成本敏感性；
- 性能—资源Pareto。

### 6.3 信息

- capability truth coverage；
- set diameter；
- false alarm；
- alarm/set-update/recovery时刻；
- `Tdet-Tcrit`；
- information Gramian；
- load-vs-capability混淆；
- calibration/coverage by mechanism。

### 6.4 计算

- solve success；
- median/p95/p99 solve time；
- iterations；
- fallback rate；
- KKT/constraint residual。

## 7. 统计

### 7.1 Success-first

先用配对四格表比较成功/失败，不把失败episode从主结论中删除。

### 7.2 连续指标

双方共同成功episode上报告：

- 配对差均值与中位数；
- cluster bootstrap 95% CI（按scenario/load seed聚类）；
- effect size；
- 场景平衡总体结果；
- 每机制和每SG余量分层结果。

禁止以 episode-wise relative ratio 的简单均值作为唯一结论，尤其当分母接近零。

### 7.3 多重比较

核心假设H1–H5预先指定；次要比较使用FDR或明确标记探索性。

## 8. 消融

根据选定分支：

- 无能力集合更新；
- 无tube/constraint tightening；
- 无终端SG backup；
- 无未知负荷估计；
- 分支A：无信息项、固定probe、无backup；
- 分支P：固定集合、无突变reset；
- 分支R：不同全局能力集合宽度。

消融不得通过不同信息集或不同物理约束获得优势。

## 9. 敏感性与鲁棒性

- SFR 2/4s；
- dt；
- prediction horizon；
- solver tolerance；
- noise/model error bounds；
- SG reserve；
- BESS power/energy ratio；
- initial SoC；
- delay；
- PFR gain；
- tube set representation；
- `J_mat`和探测预算。

## 10. 失败分类

```text
physical_frequency_failure
physical_ace_tie_failure
resource_constraint_failure
estimator_coverage_failure
estimator_timing_failure
solver_infeasible
solver_timeout
fallback_failure
code_failure
not_evaluated
not_applicable
scientific_hypothesis_failure
```

每个失败必须保留：配置、seed、日志、指标和可重放命令。

## 11. 图表

至少生成：

1. 科学问题与信息边界框图；
2. Plant A/B与控制架构；
3. Oracle材料性；
4. Tdet vs Tcrit；
5. 能力集合随时间；
6. 频率/ACE/tie/命令/输出/SoC联合时序；
7. success-first比较；
8. known/OOD；
9. 信息—性能—探测代价Pareto；
10. 失败案例；
11. 计算时间；
12. 理论tube与约束裕度。

格式：SVG、PDF、600dpi PNG，并提供源数据和生成脚本。
