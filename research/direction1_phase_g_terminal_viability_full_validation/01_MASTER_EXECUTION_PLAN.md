# Phase G 总执行计划：终端可生存性重构与完整验证

## 总目标

在不改变方向1核心科学问题、不更换CDSR-MPC主方法的前提下，纠正Phase F终端不确定性和备份架构，建立：

1. 负荷依赖平衡点；
2. 可持续域、有限能量桥接域和不可行域；
3. 结构化全局预测不确定性与本地终端不确定性；
4. SG-only可持续终端集合；
5. SG+BESS保证能力的有限桥接证书；
6. 完整覆盖延迟、实际BESS功率和能量的滚动CDSR-MPC；
7. 可接受的实时求解；
8. Plant A/B、known/OOD、基准、消融、鲁棒性和失败案例；
9. 论文级与完整可复现审查包。

按 G0→G1→G2→G3→G4→G5→G6→G7→G8→G9 连续执行。

---

## G0：冻结Phase F并重分类G5失败

### 目标
独立重算G5一步不相容性、脚本逻辑和backup容量矛盾。

### 输入
Phase F review ZIP、真实Git仓库、F3 residual NPZ、F5 certificates。

### 任务
- 创建 tag `direction1-phase-f-reviewed`；
- 创建分支 `direction1-phase-g-terminal-viability`；
- 重算频率/ACE/tie一步扰动与终端限制；
- 修复 `all()`/`any()`；
- 审计SG reserve与最大持续负荷；
- 审计F4中所有hard constraints是否鲁棒收紧；
- 审计能量使用request还是actual predicted power；
- 审计p99求解时间来源。

### 输出
```text
progress_phase_g/G0.json
research_outputs_phase_g/00_FORENSIC/PHASE_F_RECLASSIFICATION.md
results_phase_g/G0/ONE_STEP_TERMINAL_INCOMPATIBILITY.csv
results_phase_g/G0/HARD_CONSTRAINT_TIGHTENING_AUDIT.csv
results_phase_g/G0/STATIC_RESERVE_CONTRADICTION.csv
```

### 成功判据
所有关键数值可从包内数据和脚本重算；Phase F结论改为：

```text
CERTIFICATE_FORMULATION_INCOMPATIBLE
```

### 失败处理
缺少源数据时只重跑development，不使用final seeds。无法重算则停止并输出证据缺失包。

---

## G1：锁定科学范围和材料性边界

### 目标
根据Phase F修正结果锁定理论范围，不把delay材料性夸大。

### 任务
- 用development-only基线选择重新整理H1；
- power/headroom、ramp、energy、availability分别分级；
- delay作为鲁棒实施因素，除非材料性重新通过；
- 更新不少于30篇直接相关文献，聚焦：多区域LFC tube/robust MPC、black-box IBR、多模式/能力变化、延迟MPC、能量有限储能、terminal viability；
- 建立 claim–closest-work–remaining-gap 表。

### Gate
至少两个能力机制、两个SG tension显示当前能力知识有材料性；否则停止为 `PROBLEM_SCOPE_TOO_WEAK`。

---

## G2：不确定性分解和因果观测器

### 目标
把“全局事故残差”拆成具有物理语义的集合。

### 模型分解

```text
W_global_prediction:
  load-estimation error
  observer error
  local model mismatch
  delay interpolation remainder
  bounded measurement noise

W_terminal_local:
  event-free local observer/model error
  bounded slow load-rate error
  measurement noise
```

能力跳变和0.05–0.08 pu事故不得作为每个终端周期重复发生的state kick。

### 任务
- 建立Plant A可观测Kalman/zonotopic observer；
- 将load作为有界随机游走/斜率状态；
- 在development上校准；
- validation检查1/2/4/6步覆盖；
- 单独校准terminal-region local set；
- 保存event-free、near-terminal和event windows标签；
- 禁止每个窗口事后选择“最好delay顶点”来定义确定性集合；应对全部注册delay外包或明确概率覆盖。

### Gate
- 全局预测集合validation覆盖≥95%；
- 本地终端集合validation覆盖≥95%；
- 本地一步集合不直接超过所有终端性能限制；
- observer在无事件区无系统漂移；
- 无future leakage。

### 失败处理
扩大集合、改观测器或收缩理论域，最多两轮。若本地集合仍使任何非平凡终端域为空，停止为 `LOCAL_TERMINAL_MODEL_NOT_CERTIFIABLE`。

---

## G3：可持续域、桥接域和静态可行性

### 目标
先判断物理上哪些事故可以无限时域恢复，哪些只能有限能量桥接。

### 静态可持续性LP
对于当前负荷估计/区间，求：

\[
p_{g1}^\star-d_1-p_{12}^\star=0,
\qquad
p_{g2}^\star-d_2+p_{12}^\star=0
\]

在无限时域可持续域中要求：

\[
p_{b1}^\star=p_{b2}^\star=0
\]

并满足SG、tie和阀门限制。

### 桥接域
若SG暂时不足，允许BESS保证能力在注册接管时间 \(T_R\) 内承担缺额：

\[
|p_b(t)|\le \underline P_b,
\qquad
|\dot p_b(t)|\le \underline R_b
\]

\[
\int_0^{T_R} \frac{[p_b(t)]^+}{\eta_d}\,dt
\le \underline E_{\rm avail}.
\]

必须明确：
- 若没有慢速接管模型，只能声称有限 \(T_{bridge}\) 生存性；
- 若建模三级/再调度接管，必须给出物理参数和来源；
- 不得默认为BESS无限供能。

### 输出
```text
03_MODEL/SUSTAINABILITY_PARTITION.md
results_phase_g/G3/STATIC_FEASIBILITY_CELLS.csv
results_phase_g/G3/BRIDGE_ENERGY_REQUIREMENTS.csv
configs/phase_g/slow_reserve_or_bridge_contract.yaml
```

### Gate
所有final场景预先分类为 `SUSTAINABLE`、`BRIDGE_ONLY` 或 `PHYSICALLY_INFEASIBLE`。分类不能由控制算法结果反推。

---

## G4：备份控制器、终端集合和桥接证书

### 目标
建立与场景物理属性一致的安全架构。

### 可持续域
- 围绕负荷依赖平衡点 \(x^\star(\hat d)\)；
- 设计SG-only或SG主导backup；
- 对所有注册本地终端不确定性和delay顶点计算RPI/robust control invariant set；
- 使用predecessor或polytope/zonotope/ellipsoid，不能只传播box后检查。

### 桥接域
- backup允许使用IBR保证功率/爬坡/能量；
- 证明在 \([0,T_R]\) 内保持约束；
- 在慢速备用接管后进入可持续终端集合；
- 若无慢速接管模型，只给有限时域viability certificate。

### 必须比较
- stable PI；
- LQI/LQR；
- common robust feedback；
- controlled-invariant predecessor。

### Gate
- 至少一个非空可持续terminal set；
- 至少一个bridge-only注册cell有非空有限桥接证书；
- certificate可独立重算；
- 若不存在，必须区分物理不可行与数值/集合近似问题。

### 失败处理
最多两轮合理controller/set representation修复。若仍为空，停止并输出 `NO_PHYSICALLY_CONSISTENT_TERMINAL_OR_BRIDGE_CERTIFICATE`。

---

## G5：修订CDSR-MPC物理和鲁棒约束

### 目标
使预测模型、执行器和理论完全一致。

### 任务
- 增广delay pipeline；
- 每个delay/能力顶点共享控制序列；
- 对frequency、ACE、tie、SG valve/mechanical、BESS actual power实施一致margin；
- 能量根据预测actual BESS power更新，不使用request替代；
- ramp约束actual BESS power；
- 可持续场景终端进入 \(x^\star+\mathcal X_f\)；
- bridge场景满足剩余bridge能量和接管条件；
- 保持propose/commit事务；
- restoration只放松性能，不放松物理硬约束；
- 明确经验覆盖与确定性物理边界，不能混称deterministic robust。

### Gate
- 完整闭环development运行；
- hard violations=0；
- action availability=100%；
- terminal/bridge分类一致；
- residual coverage使用范围与理论一致。

---

## G6：求解加速和development/validation

### 目标
满足2/4s实时控制并证明相对最佳部署基线的价值。

### 求解加速
- 检查DPP；
- 参数化CVXPY或直接稀疏OSQP矩阵；
- condensed/sparse formulation；
- warm start；
- 预分解；
- 移除重复顶点但不得删除最坏边界；
- 记录build time与solve time。

### 基线
1. SG-only PI；
2. fixed-allocation PI；
3. nominal rolling MPC；
4. RLS adaptive MPC；
5. single-worst-delay robust MPC；
6. capability-floor-only MPC；
7. CDSR-MPC；
8. current-capability rolling NMPC Oracle。

### Gate
- success drop≤2pp；
- failure-aware不劣；
- ≥2/3核心指标改善≥8%，CI>0；
- hard violations=0；
- action availability=100%；
- unresolved mathematical infeasibility≤0.1%；
- fallback≤1%且无级联；
- p99<0.5Ts；
- Plant A/B方向一致；
- sustainable/bridge claim分别验证。

### 失败处理
最多两轮development/validation修复。仍失败则停止，不使用final seeds。

---

## G7：理论和代码一致性审计

### 目标
完成论文可接受的证明边界。

### 必须输出
- assumptions；
- load-dependent equilibrium；
- sustainable RPI/RCI；
- bridge energy/viability theorem；
- finite-horizon robust constraint theorem；
- conditional recursive feasibility theorem（仅可持续域）；
- solver/fallback不属于定理范围的说明；
- equation-code map；
-独立certificate reproduction。

### Gate
所有理论对象与代码文件、配置和数值集合完全一致。若递归证明不成立，自动收缩为有限时域+validated backup声明。

---

## G8：final known/OOD、论文材料和失败分析

### Final lock
在final前锁定：代码、权重、集合、delay grid、seeds、manifest和统计规则。

### Known/OOD
- 五种单机制；
- 组合能力变化；
- 非对称能力；
- 连续delay；
- slow drift；
- repeated events；
-不同SoC；
- Plant B运行点/接入位置；
- 2/4s；
- 300–600s事故；
- 1h正常净负荷。

### 输出
完整基准、消融、敏感性、鲁棒性、失败、求解和理论覆盖结果；论文级SVG/PDF/600dpi PNG及源数据。

---

## G9：单一完整审查包

最终文件：

```text
DIRECTION1_PHASE_G_TERMINAL_VIABILITY_FULL_VALIDATION_SINGLE_REVIEW_PACKAGE.zip
```

必须小于512MB，并可在全新临时目录直接运行minimal replay、manifest验证和certificate重算。
