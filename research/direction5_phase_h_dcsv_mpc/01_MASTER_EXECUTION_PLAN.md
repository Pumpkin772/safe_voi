# Phase H 总体执行计划：一个总 Goal、十个内部阶段

## 总目标

在不改变方向5高层科学问题的前提下，纠正 Phase G 的阶段顺序、观测器结构、负荷不确定性语义、局部终端标定和统计覆盖，并完成 DCSV-MPC 的数学模型、可部署代码、理论边界、Plant A/B、known/OOD、论文级材料和统一审查包。

内部阶段：

```text
H0 → H1 → H2 → H3 → H4 → H5 → H6 → H7 → H8 → H9
```

阶段之间自行运行 Gate。不得等待用户重新发送 Goal。

---

## H0：冻结 Phase G 与独立缺陷复现

### 研究目标
冻结旧证据，并独立重现决定 G2 无效的代码和数据问题。

### 输入
- 当前真实仓库；
- Phase G review ZIP；
- Phase G commit、manifest、G2 Parquet/NPZ/CSV；
- 历史 Phase E/F 必需脚本。

### 具体任务
1. 创建：
   ```text
   tag: direction5-phase-g-historical-reviewed
   branch: direction5-phase-h-dcsv-mpc
   ```
2. 校验 ZIP、Git、manifest。
3. 重放 near-terminal 筛选，统计其中：
   - valve/mechanical at bounds；
   - GRC active；
   - BESS power/ramp/energy constrained；
   - command saturated；
   - fallback/solver anomaly；
   - sustainable/bridge/infeasible；
   - 与 \(x^\star(\hat d)\) 的距离。
4. 复算 current one-step terminal incompatibility。
5. 验证 current package 缺失 Phase E/F 脚本。
6. 生成 Phase G 更正状态。

### 修改/新建文件
```text
progress_phase_h/H0.json
research_outputs_phase_h/00_FORENSIC/PHASE_G_CORRECTION.md
results_phase_h/H0/NEAR_TERMINAL_VALIDITY_AUDIT.parquet
results_phase_h/H0/G2_DEPENDENCY_AUDIT.csv
results_phase_h/H0/CURRENT_CERTIFICATE_REPRODUCTION.json
tests/phase_h/test_h0_phase_g_defects.py
```

### 必须实验
- 全部 near-terminal 窗口离线审计；
- 至少20个 development/validation场景精确重放；
- 2s/4s分开；
- current observer/load residual复算。

### 成功判据
- 解释至少95%的局部大残差来源；
- 每个排除原因可由代码重算；
- Phase G结果未被覆盖；
- current G2负结论被正式重分类。

### 失败与自动处理
- 若历史脚本缺失：从前一审查包或Git恢复，记录hash；
- 若无法恢复原数据：停止为 `PHASE_G_EVIDENCE_NOT_REPRODUCIBLE` 并打包；
- 不允许重新生成一组不同数据冒充旧证据。

### 衔接
H0 给出 H2/H3 的重建依据。

---

## H1：科学问题、创新边界与可证伪假设锁定

### 研究目标
完成最新正式文献调研并锁定不再变动的科学问题。

### 具体任务
1. 检索 2019–当前：
   - 黑箱 IBR 多模式/数据驱动建模；
   - 黑箱 IBR 二次频率控制；
   - 多区域 MPC/LFC；
   - unknown-input/disturbance observer；
   - offset-free MPC；
   - set-membership/MHE；
   - robust/viability MPC；
   - energy-limited bridge；
   - NERC/IEEE 设备模型验证要求。
2. 至少50篇核心文献，正式期刊/官方报告占主导。
3. 建立：
   ```text
   claim – closest work – remaining gap – required evidence
   ```
4. 锁定 H1–H6。

### 锁定科学问题
> 当黑箱 IBR 能力发生未通知变化时，能否从公共测量中将外部净负荷不平衡与资源执行能力变化分开，并根据系统属于可持续域、有限能量桥接域或物理不可行域，安全恢复多区域频率、ACE 与联络线责任？

### 假设
- H1：当前能力知识在至少两个能力机制、两个 SG tension 上具有材料性价值；
- H2：使用 actual POI power 的扰动观测器可显著降低 load/capability 混淆；
- H3：至少部分控制相关能力可由公共 I/O 形成有覆盖的集合；
- H4：可持续/桥接分类能避免错误终端证书；
- H5：DCSV-MPC 优于最佳可部署基线；
- H6：理论声明与代码一致，并明确限定可持续/桥接域。

### 输出
```text
01_SCIENCE/SCIENTIFIC_QUESTION.md
01_SCIENCE/HYPOTHESES_H1_H6.md
02_LITERATURE/LITERATURE_REVIEW.md
02_LITERATURE/NOVELTY_MATRIX.csv
02_LITERATURE/SEARCH_LOG.csv
02_LITERATURE/CLAIM_CLOSEST_GAP.csv
```

### 成功判据
- 未发现完整覆盖该交叉问题的正式工作；
- 每个创新声明都有相应实验/定理要求；
- 若创新仅剩“换一种MPC”，立即停止为 `NOVELTY_NOT_SUFFICIENT`。

### 衔接
H1 锁定后不得改变科学问题或临时堆叠算法。

---

## H2：先完成物理可持续性、桥接性与负荷依赖平衡点

### 研究目标
在终端集合标定之前，先确定每个场景的物理类别和对应平衡点。

### 具体任务
1. 对 Plant A/B、每个 SG tension、能力包络和负荷区间求静态可行 LP：
   \[
   p_{g1}^\star+p_{b1}^\star-d_1-p_{12}^\star=0
   \]
   \[
   p_{g2}^\star+p_{b2}^\star-d_2+p_{12}^\star=0.
   \]
2. 可持续域要求长期：
   \[
   p_b^\star=0
   \]
   或由明确的持续资源合同支持非零稳态值。
3. 桥接域计算：
   - 功率；
   - 爬坡；
   - 能量；
   - 慢速备用接管时间 \(T_R\)。
4. 若不建模慢速备用：
   - 只允许固定 \(T_{\rm bridge}\) 有限时域证书；
   - 不允许无限时域恢复声明。
5. 物理不可行域提前分类，不由控制器结果反推。
6. 对每个可持续 cell 计算：
   \[
   x^\star(d)
   \]
   及局部线性化。

### 输入
Plant A/B、SG reserve、BESS capability contracts、场景manifest。

### 新建/修改
```text
03_MODEL/SUSTAINABILITY_LP.md
03_MODEL/LOAD_PARAMETERIZED_EQUILIBRIA.md
03_MODEL/BRIDGE_ENERGY_MODEL.md
results_phase_h/H2/SUSTAINABILITY_CELLS.parquet
results_phase_h/H2/BRIDGE_REQUIREMENTS.parquet
results_phase_h/H2/PHYSICALLY_INFEASIBLE_CELLS.csv
configs/phase_h/slow_reserve_contract.yaml
tests/phase_h/test_h2_power_balance_and_partition.py
```

### 必须实验
- 全注册负荷/SG/能力组合；
- 2s/4s；
- known/OOD capability；
- Plant A/B代表运行点；
- 静态LP与时域平衡点交叉验证。

### 成功判据
- 每个 final cell 在控制前已有唯一分类；
- 所有 \(x^\star\) 的功率平衡残差低于 \(10^{-8}\) pu；
- 至少存在非空可持续域；
- 至少一个桥接cell有物理可解释的有限能量需求；
- 不可行域不被伪装成方法失败。

### 失败与自动处理
- 若无可持续域：检查SG/tie参数来源；物理合理后仍无，方向收缩为有限桥接研究；
- 若桥接无慢速接管：只保留有限时域；
- 不允许通过缩小事故或放宽设备能力制造可行性。

### 衔接
只有 H2 完成后才允许 H3/H4 构造局部终端数据。

---

## H3：扰动–能力分离的因果输出反馈估计

### 研究目标
避免把 BESS 延迟/降额误判为外部负荷。

### 3.1 电网状态与负荷估计器

使用实际测得：

- \(\Delta f\)；
- tie；
- \(p_m\)；
- \(p_b^{\rm actual}\)；

将实际 BESS POI power 作为已知输入，而不是由命令预测。

建议增广状态：

\[
\chi=[\omega_1,\omega_2,p_{12},p_{v1},p_{v2},p_{m1},p_{m2},d_1,d_2].
\]

不在该估计器中包含 BESS 命令–功率动态。

候选仅限同一框架内的三种实现：
- reduced-order Kalman；
- unknown-input observer；
- constrained MHE。

使用 development/validation 选择一个，不能在 final 后切换。

### 3.2 能力集合估计器

单独根据：

- issued BESS total command；
- actual BESS POI power；
- local frequency/PFR demand；
- SoC；
- command history；

更新：

\[
\mathcal C_k
=
[P^\pm,R^\pm,\tau,E_{\rm avail},a].
\]

估计器必须：
- 因果；
- 保留集合覆盖；
- 不能使用 true mode；
- 不能把无激励时的不更新当作错误；
- 区分 load change 与 actuator capability change。

### 输出
```text
03_MODEL/DISTURBANCE_OBSERVER.md
03_MODEL/CAPABILITY_SET_ESTIMATOR.md
04_METHOD/INFORMATION_BOUNDARY.md
results_phase_h/H3/OBSERVER_COMPARISON.parquet
results_phase_h/H3/CAPABILITY_SET_COVERAGE.parquet
results_phase_h/H3/LOAD_CAPABILITY_CONFUSION.parquet
tests/phase_h/test_h3_no_truth_or_future_leakage.py
```

### 必须实验
- load-only；
- capability-only；
- simultaneous；
- no-excitation negative control；
- headroom/ramp/delay/energy/availability；
- measurement noise/jitter/dropout；
- Plant A/B；
- 2s/4s；
- slow drift/OOD。

### 成功判据
- load估计无系统漂移；
- load/capability confusion显著低于Phase G observer；
- validation capability set coverage≥95%；
- false shrinkage≤5%；
- no-excitation时允许保持宽集合，不产生虚假高置信检测；
- 4s observability/conditioning明确报告。

### 失败与自动处理
- 最多两轮：调整观测状态、噪声模型或MHE窗口；
- 若公共I/O结构上无法区分某机制，标记 `STRUCTURALLY_UNIDENTIFIABLE`，方法必须对其鲁棒，不再强制辨识；
- 不得通过加入真值传感器或未来数据通过Gate。

### 衔接
H3 输出 \(\hat d_k,\mathcal D_k,\mathcal C_k\) 供 H4/H5。

---

## H4：重新构造全局预测集合和局部终端集合

### 研究目标
建立物理语义正确、样本充分、围绕 \(x^\star(\hat d)\) 的 uncertainty sets。

### 全局集合
覆盖：
- observer estimation error；
- \(\Delta d\) / bounded load-rate；
- local model mismatch；
- delay interpolation；
- measurement noise。

能力跳变由 \(\mathcal C_k\) 约束，不作为任意 state kick。

### 局部终端集合
只使用：
- H2中 `SUSTAINABLE`；
- state接近 \(x^\star(\hat d)\)；
- 无新load/capability事件至少完整horizon；
- SG valve/pm未在边界；
- GRC未激活；
- BESS未功率/ramp/energy受限；
- observer warmed；
- 无solver/fallback；
- command未饱和。

每个被排除窗口必须保存唯一主因和所有附加原因。

### 持续负荷误差
增广：
\[
\tilde d_{k+1}=\tilde d_k+\nu_k,
\quad \nu_k\in\mathcal V_d.
\]

终端集合围绕 \((x^\star(\hat d),\tilde d=0)\)，而不是将 \(\tilde d\) 每周期重复为新step。

### 统计
采用：
- split conformal；
- 或二项分布覆盖下界。

每个 period/Plant/horizon 的 validation 样本应足够；不足则增加独立场景，不得使用 final seeds。

### 输出
```text
03_MODEL/GLOBAL_PREDICTION_SET.npz
03_MODEL/LOCAL_TERMINAL_SET.npz
03_MODEL/TERMINAL_WINDOW_FILTER_SPEC.md
results_phase_h/H4/WINDOW_LABELS.parquet
results_phase_h/H4/COVERAGE_WITH_CONFIDENCE.csv
results_phase_h/H4/EXCLUSION_REASONS.csv
tests/phase_h/test_h4_terminal_window_semantics.py
```

### 成功判据
- validation joint coverage target满足且统计下界达标；
- near-terminal中物理限制激活率为0；
- local set嵌套于global set；
- 一步兼容性在负荷依赖误差模型下通过；
- no future leakage。

### 失败与自动处理
- 样本不足：增加 development/validation trajectories；
- local set过大：先检查window和observer，不得直接放宽terminal limits；
- 两轮后仍空：停止为 `LOCAL_TERMINAL_DOMAIN_NOT_SUPPORTED`，保存负结果。

### 衔接
通过后进入 H5。

---

## H5：实现唯一方法 DCSV-MPC

### 研究目标
完成一个一致处理三类物理域的输出反馈预测控制器。

### 可持续域
- 以 \(x^\star(\hat d)\) 为参考；
- 对 \(\mathcal D_k,\mathcal C_k,\mathcal W\) 进行场景/管束鲁棒预测；
- 终端进入可持续 RCI/RPI 集；
- BESS长期目标回到可持续状态。

### 桥接域
- 使用保证BESS power/ramp/energy；
- 显式剩余桥接时间和慢速备用接管；
- 终端约束为“在 \(T_R\) 前保持可行并接入可持续域”；
- 无慢速备用时只求固定时域 viability，不声称递归。

### 不可行域
- 提前标记；
- 执行预注册 emergency/SG backup；
- 作为物理不可行，不计为普通控制器数值失败。

### 优化要求
所有叫 MPC 的方法必须真实包含：
- 预测状态序列；
- 输入序列；
- 动力学；
-功率/ramp/energy/delay约束；
-终端/桥接条件；
-solver diagnostics。

### 输出
```text
src/direction5_freq/controllers/dcsv_mpc.py
src/direction5_freq/controllers/domain_supervisor.py
src/direction5_freq/controllers/feasibility_restoration.py
04_METHOD/DCSV_MPC_FORMULATION.md
04_METHOD/DCSV_MPC_PSEUDOCODE.md
04_METHOD/EQUATION_CODE_MAP.csv
tests/phase_h/test_h5_dcsv_mpc.py
```

### 成功判据
- action availability=100%；
- physical hard violations=0；
- actual action history与预测一致；
- sustainable/bridge/infeasible逻辑与H2一致；
- ordinary controller无truth leakage；
- p99求解时间满足实时要求。

### 失败与自动处理
- 数值问题：缩放、warm start、稀疏化，最多两轮；
- formulation不可行：检查domain分类与终端；不得放松物理能力；
- 若鲁棒集合使IBR永远为0且相对SG-only无价值，停止为 `CAPABILITY_UNCERTAINTY_COLLAPSES_CONTROL_VALUE`。

### 衔接
H5控制器进入H6理论与H7验证。

---

## H6：理论、终端集合与桥接证书

### 研究目标
让理论声明与实际代码严格一致。

### 可持续域
至少给出：
- load-parameterized equilibrium；
- augmented error dynamics；
- robust control invariant/positive invariant terminal set；
- 注册初始域内的递归可行或有限时域鲁棒约束结论。

### 桥接域
给出：
\[
\int_0^{T_R} p_b^+/\eta_d\,dt
\le E_{\rm avail}
\]
及功率/爬坡/频率/ACE约束的有限时域 viability certificate。

### 不可行域
给出物理不可行性 certificate：
- steady-state power；
- ramp；
- energy；
- tie/SG limits。

### 输出
```text
05_THEORY/ASSUMPTIONS.md
05_THEORY/SUSTAINABLE_TERMINAL_SET.npz
05_THEORY/SUSTAINABLE_CERTIFICATE.json
05_THEORY/BRIDGE_CERTIFICATES.parquet
05_THEORY/INFEASIBILITY_CERTIFICATES.parquet
05_THEORY/THEOREMS_AND_PROOFS.md
05_THEORY/REPRODUCE_CERTIFICATES.py
tests/phase_h/test_h6_certificates.py
```

### 成功判据
- 证书可独立重算；
- 代码使用同一对象；
- theorem适用域明确；
- 不夸大经验覆盖为确定性全扰动保证。

### 失败与自动处理
- 允许收缩为有限时域/条件性结论；
- 不允许保留无法证明的“递归安全”措辞；
- 若可持续和桥接证书均为空，停止方法路线。

### 衔接
H6确定论文理论声明。

---

## H7：Development/Validation 方法定型

### 基线
必须实际实现并运行：
1. SG-only ACE PI；
2. fixed allocation PI；
3. nominal offset-free MPC；
4. RLS/adaptive MPC；
5. worst-case contract robust MPC；
6. mode-label/true-capability Oracle（evaluation only）；
7. DCSV-MPC。

### 实验
- Plant A全矩阵；
- Plant B代表矩阵；
- 2s/4s；
- 300–600s事故；
- 1h正常净负荷；
- five mechanisms；
- simultaneous load/capability；
- noise/jitter/dropout；
- repeated changes；
- different SoC；
- sustainable/bridge/infeasible分开。

### Gate
- success率相对最佳可部署基线下降≤2pp；
- failure-aware不劣；
- frequency/ACE/tie至少2项改善≥8%，CI下界>0；
- hard violations=0；
- unsolved math infeasibility≤0.1%；
- fallback≤1%，无级联；
- p99<0.5Ts；
- Plant A/B方向一致；
- classification错误不被隐藏。

### 自动处理
最多两轮 development/validation 修复。不能改变科学问题、事故范围或 final 标准。

若失败，停止并生成完整负结果，不运行 final。

---

## H8：Final、论文级分析与图表

### Final
- 固定方法、权重、集合、阈值；
- final seeds只运行一次；
- known/OOD分开；
- 所有失败保留；
- 不回调算法。

### 必须图表
- 科学问题和信息边界；
- load–capability separation；
- sustainable/bridge/infeasible map；
- capability set evolution；
- \(T_{\rm update}\) vs \(T_{\rm crit}\)；
- DCSV predictive scenarios；
- Plant A/B；
- frequency/ACE/tie；
- power/ramp/energy；
- solver/fallback；
- known/OOD；
- failure cases；
- ablation；
- certificate；
- computation。

### 论文文件
```text
14_PAPER_ANALYSIS/PAPER_ROUTE.md
14_PAPER_ANALYSIS/CONTRIBUTIONS.md
14_PAPER_ANALYSIS/RESULTS_NARRATIVE.md
14_PAPER_ANALYSIS/REVIEWER_RISK_REGISTER.md
14_PAPER_ANALYSIS/SUPPORTED_AND_UNSUPPORTED_CLAIMS.md
```

### 成功判据
每个 claim 有对应公式、代码、表格、图或失败反例。

---

## H9：统一可复现审查包

### 最终文件名
```text
DIRECTION5_PHASE_H_DCSV_MPC_SINGLE_REVIEW_PACKAGE.zip
```

### 成功判据
- <512MB；
-完整source snapshot，不缺Phase E/F依赖；
- manifest/SHA256通过；
-新临时目录中 `reproduce_minimal` 通过；
-全量复现命令完整；
- Git clean；
- cache、env、license、重复checkpoint删除；
-支持结论的原始结果与全部失败保留。
