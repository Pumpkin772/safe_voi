# Phase I 总体执行计划：最终收敛，不再无限迭代

## 总目标

在一个Codex Goal内完成：

```text
I0 → I1 → I2 → I3 → I4 → I5 → I6 → I7 → I8
```

最终必须得到以下二者之一：

1. **PAPER_READY_WITH_BOUNDED_CLAIMS**  
   科学问题、方法、理论、Plant A/B、known/OOD和复现材料达到预注册Gate；

2. **DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE**  
   在纠正后的模型、估计器、完整闭环和公平基线下，材料性或方法Gate仍失败。

不得在Phase I后继续创建新的Phase J/K来逃避结论。

---

## I0：冻结Phase H与独立审计

### 研究目标
冻结原包，复现所有决定性问题并生成可追溯更正。

### 输入
- Phase H review ZIP；
-当前真实仓库；
-Phase H commit/manifest/results。

### 任务
1. 建立：
   ```text
   tag: direction5-phase-h-reviewed
   branch: direction5-phase-i-final-convergence
   ```
2. 校验ZIP、manifest、Git。
3. 单元测试复现：
   - artificial 1h rows；
   - held-tail behavior；
   - Plant B reduced surrogate；
   - seed-factor confounding；
   - energy semantics mismatch；
   - availability no-op；
   - bridge time not decrementing；
   - capability floors；
   - continuous delay not enveloped。
4. 撤回Phase H H5结果作为方法证据。

### 修改/新建
```text
progress_phase_i/I0.json
research_outputs_phase_i/00_FORENSIC/PHASE_H_CORRECTION.md
results_phase_i/I0/SCIENTIFIC_VALIDITY_DEFECTS.csv
results_phase_i/I0/CLAIM_RETRACTION_TABLE.csv
tests/phase_i/test_i0_phase_h_defects.py
```

### 必须实验
- 选取至少20个H7场景进行精确重放；
- 将held-tail改为全滚动后进行差异重放；
- true Plant A step与H7 ZOH driver对照；
-原生Plant B与H7 surrogate对照；
- 1h row provenance审计。

### 成功判据
- 所有致命问题均有源码、测试或数据证据；
- Phase H结果未覆盖；
-更正状态明确。

### 失败处理
旧证据不可恢复则停止并输出不可复现负结果包。

### 衔接
I0锁定Phase I不得再使用的代码与声明。

---

## I1：最终科学范围与文献创新锁定

### 研究目标
收缩到可辨识、可控制、可证明的问题，不再同时估计五个含义混杂的隐变量。

### 锁定隐藏能力范围
安全相关隐藏集合只包括：

\[
\theta_c=
\{P^+,P^-,R^+,R^-,\tau\}.
\]

- SoC/energy：由公共SoC、额定能量和效率直接计算；
- availability：不单独估计，折算进power/ramp envelope；
-合同能力下界：用于硬安全；
-在线可交付能力集合：用于性能和责任分配；
- 若真实能力跌破合同下界，定义为contract violation，并由应急备用处理。

### 科学问题
> 能否仅凭公共测量，把净负荷变化与IBR可交付能力下降分开，并在合同下界、在线可交付集合和实测SoC约束下，提高多区域频率与ACE控制，同时明确突降低于合同下界时的不可保证边界？

### 理论边界
必须明确证明/说明：

> 若设备能力可以在无预警情况下瞬间跌破任何已知下界，则任何仅依赖历史I/O的控制器都不能在变化发生的同一瞬间保证其指令可执行。

这不是缺陷，而是论文的条件性安全边界。

### 文献任务
- 更新至执行日期；
- ≥60篇核心文献；
- 正式期刊/官方报告为主；
- 对比黑箱IBR建模、data-driven SFR、set-membership adaptive MPC、fault tolerant/actuator degradation control、multi-area MPC、BESS energy constraints；
- 建立精确closest-work矩阵。

### 输出
```text
01_SCIENCE/LOCKED_SCIENTIFIC_QUESTION.md
01_SCIENCE/HYPOTHESES_H1_H6.md
01_SCIENCE/IMPOSSIBILITY_BOUNDARY.md
02_LITERATURE/LITERATURE_REVIEW.md
02_LITERATURE/NOVELTY_MATRIX.csv
02_LITERATURE/SEARCH_LOG.csv
02_LITERATURE/CLAIM_CLOSEST_WORK.csv
```

### 成功判据
- 未发现正式工作完整覆盖该交叉问题；
- 每个创新点对应实验或定理；
- 不再声称估计隐藏energy/availability。

### 失败处理
若创新只剩“现有set-membership MPC用于AGC”，停止为 `NOVELTY_NOT_SUFFICIENT`。

---

## I2：重建物理平台和完整实验驱动

### 研究目标
建立真正可评价核心科学事件的Plant A和原生Plant B。

### Plant A
- 使用非线性 `TwoAreaPlantAV2.step()`，而不是只用线性ZOH；
- 完整SG governor/turbine/GRC/valve；
- BESS PFR+SFR共享power/ramp/delay/SoC；
- 2s/4s；
- dt收敛；
- energy守恒。

### Plant B
- 原生ANDES Kundur或IEEE39；
- BESS在母线注入；
-相同SFR接口；
-相同能力事件；
-保存初始化警告；
-不得以reduced layer+noise替代native final。

### 能力变化事件
每个主要episode必须包含：

```text
nominal warm-up
→ unannounced capability change at randomized time
→ possible load event before/after/simultaneously
→ full rolling controller for entire horizon
```

### 慢速备用
- 使用一阶或受爬坡约束的慢速备用状态；
-不得在60s瞬时从负荷中减去；
- bridge time必须逐周期递减。

### 正常运行
真正仿真至少1h净负荷，不得插入零行。

### 输入/输出
```text
03_MODEL/PLANT_A_FULL_MODEL.md
03_MODEL/PLANT_B_NATIVE_MODEL.md
03_MODEL/SLOW_RESERVE_MODEL.md
03_MODEL/ABILITY_EVENT_MODEL.md
results_phase_i/I2/DT_CONVERGENCE.csv
results_phase_i/I2/ENERGY_BALANCE.csv
results_phase_i/I2/PLANT_A_B_CROSSCHECK.csv
tests/phase_i/test_i2_physical_models.py
```

### 成功判据
- Plant A单位、功率和能量残差通过；
- Plant B在相同事件下方向一致且原生运行；
-完整闭环每个控制周期都更新；
- 1h结果来自真实轨迹；
- capability change时刻在manifest中独立随机。

### 失败处理
-代码/数值最多两轮；
- Plant B无法运行时只允许更换一次正式标准系统；
-仍失败则停止为 `NATIVE_VALIDATION_NOT_AVAILABLE`，不得虚构surrogate final。

---

## I3：扰动观测与可交付能力集合重建

### 研究目标
建立具有正确物理语义的因果估计器。

### 负荷观测器
输入：
- frequency；
- tie；
- SG mechanical power；
- actual BESS POI power。

不得使用issued BESS command预测POI power后再估负荷。

候选：
- reduced-order Kalman；
- unknown-input observer；
- constrained MHE。

仅在development选择一个。

### 可交付能力模型
设备外部模型：

\[
p_{k+1}
=
a p_k+b u_{k-d}+\epsilon_k,
\]

并满足：

\[
-P^-_k\le p_k\le P^+_k,
\]

\[
-T_sR^-_k\le p_{k+1}-p_k\le T_sR^+_k.
\]

延迟：
\[
d\in\mathcal D_k.
\]

使用移动窗口set-membership/MHE，输出：
- feasible parameter/model set；
- power/ramp deliverability interval；
- delay candidate set；
- confidence/coverage diagnostics。

### 能量
直接由：
\[
E_k=E_{\rm rated}SOC_k
\]
和效率更新。不得用“已使用能量”当作“剩余可用能量下界”。

### 合同下界与在线集合
区分：
- \(\mathcal C_{\rm contract}\)：安全硬约束；
- \(\mathcal C_{\rm online}\)：额外可用性能；
- contract violation alarm。

### 必须实验
- load-only；
- capability-only；
- simultaneous；
- no-excitation；
- downward abrupt change；
- slow drift；
- noise/jitter/dropout；
- Plant A/B；
- 2s/4s。

### 输出
```text
03_MODEL/DISTURBANCE_OBSERVER.md
03_MODEL/DELIVERABILITY_SET_ESTIMATOR.md
03_MODEL/CONTRACT_FLOOR_SEMANTICS.md
results_phase_i/I3/LOAD_CAPABILITY_CONFUSION.parquet
results_phase_i/I3/DELIVERABILITY_SET_COVERAGE.parquet
results_phase_i/I3/CONTRACT_VIOLATION_DETECTION.parquet
tests/phase_i/test_i3_estimation_and_no_leakage.py
```

### 成功判据
- load估计无系统漂移；
- true delay候选覆盖≥95% validation；
- power/ramp set false optimism≤1%；
- contract floor在known注册场景中100%不超过true capability；
- no-excitation保持宽集合；
- SoC/energy物理一致；
- estimator不读取truth/future。

### 失败处理
最多两轮同框架修复。
结构不可辨识的量转为鲁棒集合，不得继续强制点估计。
若安全只能依赖零IBR能力且没有材料性价值，停止。

---

## I4：重建DCSV-MPC

### 研究目标
实现合同下界安全、在线可交付集合增益、完整SoC和连续延迟覆盖的滚动MPC。

### 状态与模型
- load disturbance estimate；
- actual-action history；
- full delay pipeline；
- BESS actual power；
- measured energy/SoC；
- SG states；
- slow-reserve state。

### 不确定性
- contract floor用于所有硬约束；
- online surplus只用于软性能/可撤销分配；
- delay候选或外包顶点；
- development残差集合；
-连续delay稠密网格验证。

### 能量
使用真实状态：

\[
E_{k+1}
=
E_k-\frac{T_sS_B}{3600}
(P_k^+/\eta_d-\eta_cP_k^-).
\]

同时约束：
\[
E_{\min}\le E_k\le E_{\max}.
\]

### 三域
- sustainable：负荷相关终端集；
- bridge：动态慢速备用接管和剩余能量；
- infeasible：提前物理证书与应急动作。

### 优化
- 所有顶点共享控制序列；
- robust hard constraints；
- worst-case epigraph或明确平均情景目标；
- feasibility restoration只放松性能，不放松资源硬约束；
- actual action commit；
-全时域滚动，不允许held tail。

### 基线
必须是真实实现：
1. SG-only PI；
2. fixed allocation PI；
3. nominal offset-free MPC；
4. RLS/model-adaptive MPC；
5. contract-floor robust MPC；
6. true current-capability Oracle；
7. DCSV-MPC。

### 输出
```text
04_METHOD/DCSV_MPC_FORMULATION.md
04_METHOD/DCSV_MPC_PSEUDOCODE.md
04_METHOD/EQUATION_CODE_MAP.csv
src/direction5freq/controllers/dcsv_mpc_final.py
src/direction5freq/controllers/slow_reserve.py
src/direction5freq/controllers/contract_violation_supervisor.py
tests/phase_i/test_i4_dcsv_mpc_final.py
```

### 成功判据
-每个MPC是真实滚动优化；
-完整时域每周期更新；
- hard violations=0；
- action availability=100%；
- no truth/future leakage；
- energy/delay/ramp与physical plant一致；
- bridge clock递减并实际接管。

### 失败处理
最多两轮数值/formulation修复；不得换算法或放宽物理限制。

---

## I5：理论推导与证书

### 研究目标
形成可投稿但不过度夸大的理论。

### 必须推导

#### T1 不可保证边界
若能力可以无预警跌破所有已知下界，则在变化瞬间不能保证依赖该资源的命令可执行。

#### T2 合同下界下的有限时域鲁棒约束
在：
\[
\mathcal C_{\rm true}\supseteq \mathcal C_{\rm contract},
\quad
\tau\in\mathcal D,
\quad
w\in\mathcal W
\]
时，预测时域内资源硬约束和注册频率/ACE约束成立。

#### T3 可持续域终端条件
围绕负荷相关平衡点，给出RPI/RCI或明确的条件性递归可行性。

#### T4 桥接域有限时域
在慢速备用 \(T_R\) 内，power/ramp/energy足够则可进入sustainable domain。

#### T5 物理不可行证书
给出steady power、ramp、energy、tie/SG短缺。

### 输出
```text
05_THEORY/ASSUMPTIONS.md
05_THEORY/IMPOSSIBILITY_THEOREM.md
05_THEORY/SUSTAINABLE_CERTIFICATE.*
05_THEORY/BRIDGE_CERTIFICATES.parquet
05_THEORY/INFEASIBILITY_CERTIFICATES.parquet
05_THEORY/THEOREMS_AND_PROOFS.md
05_THEORY/REPRODUCE_CERTIFICATES.py
tests/phase_i/test_i5_certificates.py
```

### 成功判据
-证书可独立重算；
-代码使用同一集合；
-理论范围和Plant A/B范围明确；
-无法证明递归可行时主动收缩为有限时域声明。

### 失败处理
不允许保留无法证明的“安全保证”措辞。
若所有域证书为空，终止方法路线。

---

## I6：Development/Validation定型

### 研究目标
在final前作出唯一继续/终止判断。

### 实验设计
因素显式独立，不得由seed取模绑定：

- mechanism；
- SG tension；
- period；
- load area/sign/magnitude/timing；
- capability change timing；
- SoC；
- noise；
- jitter；
- dropout；
- Plant；
- domain。

### 最小规模
- Plant A：每个mechanism×SG tension×period至少10个validation paired seeds；
- Plant B：每个mechanism至少8个代表paired seeds；
- 1h normal：至少6条真实净负荷profile/方法；
- 300–600s事故；
- repeated capability changes；
- load/capability simultaneous；
- contract violation单独报告。

### 主Gate
- success率相对最佳部署基线下降≤2pp；
- failure-aware总体不劣；
- frequency/ACE/tie至少2项改善≥8%，cluster bootstrap CI下界>0；
- terminal recovery成功；
- hard violations=0；
- unresolved mathematical infeasibility≤0.1%；
- fallback≤1%，无级联；
- p99<0.5Ts；
- Plant A/B方向一致；
- normal 1h非占位仿真；
- contract-violation场景不冒充保证域。

### 自动修复
仅允许两轮development/validation修复。
仍失败则停止为：
```text
DIRECTION5_METHOD_NOT_SUPPORTED_AFTER_CORRECTED_FULL_VALIDATION
```
不得运行final，也不得再建新Phase。

---

## I7：Final known/OOD与论文级证据

### 前提
I6全部Gate通过，所有配置和hash锁定。

### Final
- known与OOD分开；
- final seeds只运行一次；
-不回调算法；
-全部失败保留。

### OOD
- capability组合；
-能力跌破合同下界；
-非对称充放电；
-连续delay；
-slow drift；
-新SoC；
-新Plant B operating point；
-连续能力变化；
-负荷与能力同时突变。

### 必须分析
- success-first；
- paired failures；
- terminal recovery；
- contract violation；
- estimator coverage；
- solver/fallback；
- normal1h；
- bridge；
- infeasible certificate；
- computation；
- ablation。

---

## I8：论文材料与统一审查包

### 论文级输出
- system/method diagrams；
- closest-work/novelty table；
- mathematical appendix；
- all figures SVG/PDF/600dpi；
-源数据；
-supported/unsupported claims；
-reviewer risk register；
-paper route；
-reproducibility report。

### 最终状态
只允许：
```text
PAPER_READY_WITH_BOUNDED_CLAIMS
```
或
```text
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```

### ZIP
```text
DIRECTION5_PHASE_I_FINAL_CONVERGENCE_SINGLE_REVIEW_PACKAGE.zip
```
小于512MB，并在新临时目录通过minimal replay。
