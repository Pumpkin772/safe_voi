# Phase F 总体执行计划：一个总 Goal、十个内部阶段

## 总目标

在不改变方向1核心科学问题的前提下，修复 Phase E 的证据口径、控制器状态管理和鲁棒预测模型，完成唯一方法 CDSR-MPC 的数学 formulation、代码实现、可行性治理、理论边界、Plant A/B 验证、known/OOD final 实验和论文级可复现材料。

不得在阶段间等待用户重新发 Goal。阶段失败时依次检查：

```text
代码 → 数值/求解器 → 参数来源 → 数学模型 → 方法 → 科学假设
```

只有科学问题材料性不成立，或保证能力包络必然退化为 SG-only 且无法产生可测价值时，才允许停止当前路线。

---

## F0：冻结 Phase E 与独立故障复现

### 研究目标
把 Phase E 固定为只读证据，并独立重现决定下一步的实现缺陷。

### 输入
- 当前真实 Git 仓库；
- Phase E review ZIP；
- Phase E commit、manifest、E6 日志和 E6 控制轨迹。

### 具体任务
1. 创建 tag：
   ```text
   direction1-phase-e-reviewed
   ```
2. 创建分支：
   ```text
   direction1-phase-f-cdsr-mpc
   ```
3. 校验 Phase E ZIP SHA256、Git commit、clean status。
4. 新增独立审计脚本，验证：
   - fallback 后 `optimizer.previous_action` 与实际动作不一致；
   - terminal reject 后同样不一致；
   - delay episode 的失败是否在 fallback 后集中出现；
   - review ZIP 中 `reproduce_minimal.py` 无法直接运行。
5. 解析每个求解周期的：
   - primary solver status；
   - secondary solver status；
   - primal/dual residual；
   - terminal rejection；
   - fallback；
   - 前一周期是否 fallback；
   - actual previous command；
   - optimizer stored previous command。

### 新建/修改文件
```text
progress_phase_f/F0.json
research_outputs_phase_f/00_FORENSIC/PHASE_E_REVIEW_CORRECTION.md
results_phase_f/F0/E6_FAILURE_DECOMPOSITION.csv
results_phase_f/F0/ACTION_HISTORY_MISMATCH.csv
tests/phase_f/test_f0_phase_e_defects.py
```

### 必须运行的实验
- 全部 E6 控制轨迹离线故障分解；
- 至少20个 delay 失败场景的精确重放；
- forced solver failure；
- forced terminal rejection；
- 连续两次 fallback；
- review ZIP 最小复现测试。

### 成功判据
- 解释至少95%的 E6 unsolved/fallback 周期；
- action-history mismatch 可被单元测试稳定复现；
- 所有旧结果仍可追溯，未覆盖 Phase E。

### 失败判据与自动处理
- 若旧轨迹缺少必要字段：仅重跑 development E6 并补齐字段，不使用 final seeds。
- 若 action mismatch 不存在：保留证据，转而从数值状态、终端筛查和 delay model 继续诊断，不强行维持原假设。
- 若仓库无法恢复：从 review ZIP source 还原独立仓库；仍缺失关键依赖则停止并输出负结果包。

### 衔接
F0 输出决定 F2 的修复优先级。

---

## F1：纠正科学证据与声明边界

### 研究目标
在不运行新控制器的情况下，纠正 H1/H2/H3 的统计和语言边界。

### 具体任务
1. 最佳可部署基线只能用 development seeds 选择，并在 validation 固定。
2. E3 使用 success-first 分析：
   - 双方成功/仅Oracle失败/仅基线失败/双方失败；
   - 双方成功时比较连续指标；
   - 失败惩罚敏感性；
   - 不能以连续指标改善掩盖成功率下降。
3. 将 H1 分机制分级：
   ```text
   SUPPORTED
   CONDITIONAL
   NOT_SUPPORTED
   ```
4. 将 H2 改为：
   ```text
   TESTED_PASSIVE_ESTIMATORS_NOT_SUPPORTED_UNDER_REGISTERED_EXCITATION
   ```
5. 将 H3 改为：
   ```text
   TESTED_ACTIVE_PROBE_NOT_SAFE
   ```
6. 重新计算 Tcrit 时只用 development 冻结阈值，validation 不参与设计。

### 输入
Phase E E3/E4/E5 原始结果和源码。

### 输出
```text
research_outputs_phase_f/01_SCIENCE/CORRECTED_HYPOTHESES_STATUS.csv
research_outputs_phase_f/01_SCIENCE/CORRECTED_CLAIM_BOUNDARY.md
results_phase_f/F1/MATERIALITY_FAILURE_AWARE.csv
results_phase_f/F1/BASELINE_SELECTION_DEVELOPMENT_ONLY.csv
results_phase_f/F1/TCRIT_DEVELOPMENT_ONLY.csv
tests/phase_f/test_f1_statistics_and_split.py
```

### 成功判据
- validation 从未参与基线、阈值或权重选择；
- 失败和 not_evaluated 分开；
- 所有比率均可从逐 episode 数据重算；
- H1 至少在两个机制、两个 SG tension 上仍有证据，否则触发科学停止门。

### 失败判据与自动处理
- 若修正后 H1 不成立：停止 CDSR-MPC，输出 `PROBLEM_NOT_MATERIAL_AFTER_CORRECTION`。
- 不允许通过修改事故规模、删 episode 或放宽 success 标准挽救 H1。

### 衔接
只有 H1 修正后仍成立才进入 F2。

---

## F2：控制器状态、求解器和可行性治理修复

### 研究目标
消除实现层导致的伪不可行和级联 fallback。

### 具体任务
1. 把 MPC 接口改为：
   ```python
   proposal, diagnostics = optimizer.propose(...)
   applied, supervisor = controller.accept_or_fallback(proposal, diagnostics)
   optimizer.commit_applied_action(applied)
   ```
2. `propose()` 禁止修改 `previous_action`、delay pipeline 或 warm-start physical history。
3. terminal reject、solver fail、feasibility restoration、SG fallback 后均提交实际动作。
4. 区分：
   ```text
   optimal
   optimal_inaccurate_accepted
   numerical_failure
   primal_infeasible
   dual_infeasible
   max_iter
   terminal_reject
   restoration_used
   sg_fallback
   ```
5. 为 OSQP/CLARABEL 实施残差验收，而不是仅看状态字符串。
6. 增加两级恢复：
   - 一级：同一物理约束下的 numerical retry；
   - 二级：只放松频率/ACE/tie performance envelope，不放松功率、爬坡、能量和SG/BESS硬边界；
   - 最后才 SG-only fallback。
7. 在每个周期记录 actual previous action 与 model previous action。

### 新建/修改文件
```text
src/direction1freq/controllers/mpc_transaction.py
src/direction1freq/controllers/feasibility_restoration.py
src/direction1freq/controllers/nominal_mpc.py
src/direction1freq/controllers/proposed_robust_tube_mpc.py
tests/phase_f/test_f2_action_commit_contract.py
tests/phase_f/test_f2_solver_status_taxonomy.py
results_phase_f/F2/SOLVER_FAILURE_ROOT_CAUSE.csv
```

### 必须运行
- Phase E 原 E6 development 全部重放；
- delay机制单独至少100 episode；
- forced status、forced inaccurate solution、forced terminal reject；
- fallback 后连续10周期；
- 2 s和4 s。

### 成功判据
- 每个周期的预测历史与实际已执行动作完全一致；
- 物理硬约束不得被恢复QP放松；
- 控制器100%返回有限、物理可执行动作；
- 不再出现未分类的 solver/fallback 原因；
- 若仅修复接口即可把原E6 unsolved率降低，必须报告但不能直接作为最终方法结果。

### 失败后的自动处理
- 数值问题：检查缩放、warm start、solver tolerance和DPP；最多两轮。
- 数学不可行：不得降低物理约束，转入 F3/F4 重新建模。
- 仍无法区分失败类型则停止，状态 `SOLVER_DIAGNOSIS_INCOMPLETE`。

### 衔接
F2 形成可信 solver infrastructure，供 F4 使用。

---

## F3：保证能力包络、延迟集合与预测误差集合

### 研究目标
把未知能力变化转换成可解释、可验证、能进入优化问题的集合。

### 保证能力包络
定义：

\[
\underline{\mathcal C}
=
\{\underline P_b^+,\underline P_b^-,
\underline R_b^+,\underline R_b^-,
\bar\tau,
\underline E_{\rm avail}\}.
\]

初始建议仅作为development配置，不得直接锁死：

```text
P floor: 0.03 pu
ramp floor: 0.012 pu/s
delay upper bound: 2.0 s
energy floor: 0.8 MWh per BESS
```

Codex必须解释这些数值如何由现有五类机制和服务合同含义得到。

### 延迟模型
对每个延迟候选：

\[
\tau_q\in\mathcal D
\]

建立：

\[
x_{k+1}^{(q)}
=
A_dx_k^{(q)}
+
B_0(\tau_q)u_k
+
B_1(\tau_q)u_{k-1}
+
E_d\hat d_k
+
w_k.
\]

使用 augmented state：

\[
z_k=[x_k^\top,u_{k-1}^\top,E_{b,k}^\top]^\top.
\]

候选网格至少覆盖：

```text
0.2, 0.6, 1.0, 1.6, 2.0 s
```

并在稠密延迟网格上验证凸包或外包误差。

### 预测误差集合
- 只能使用 development 残差校准；
- validation 检查 one-step 和 multi-step 覆盖；
- final 不得重新估计；
- 不得使用手工无来源的 disturbance radius。

### 输出
```text
03_MODEL/GUARANTEED_CAPABILITY_ENVELOPE.md
03_MODEL/DELAY_AUGMENTED_MODEL.md
03_MODEL/UNCERTAINTY_SET_CALIBRATION.md
results_phase_f/F3/DELAY_MODEL_HULL_ERROR.csv
results_phase_f/F3/RESIDUAL_SET_COVERAGE.csv
configs/phase_f/capability_envelope.yaml
tests/phase_f/test_f3_delay_and_energy_model.py
```

### 成功判据
- 延迟模型在稠密网格上的一步误差低于预注册阈值；
- development校准的误差集合在validation上达到至少95%覆盖；
- BESS总功率、爬坡和累计能量与Plant A物理执行器一致；
- 若包络收缩到零BESS能力，应明确记录而非隐藏。

### 失败与自动处理
- delay外包误差大：增加有限顶点或使用保守外包，最多两轮；
- residual coverage不足：扩大集合而非删异常；若扩大后方法退化为SG-only，触发方法价值停止门；
- 能力包络缺乏物理依据：只允许改成保守合同包络并收缩声明。

### 衔接
F3给出F4唯一允许使用的 uncertainty set。

---

## F4：实现唯一方法 CDSR-MPC

### 研究目标
建立真正覆盖能力和延迟集合的滚动鲁棒MPC，不再使用虚假的tube命名。

### 方法
对每个不确定顶点 \(q\) 建立独立预测状态，但所有顶点共享同一控制序列：

\[
z_{i+1|k}^{(q)}
=
\bar A_qz_{i|k}^{(q)}
+
\bar B_qv_{i|k}
+
\bar E\hat d_k.
\]

非预见性：

\[
v_{i|k}^{(q)}=v_{i|k},\quad\forall q.
\]

鲁棒约束：

\[
f_i^{(q)},ACE_i^{(q)},P_{\rm tie,i}^{(q)}
\in\mathcal X_{\rm perf},
\]

\[
p_{b,i}^{(q)}
\in[-\underline P_b^-,\underline P_b^+],
\]

\[
\Delta p_{b,i}^{(q)}
\in[-T_s\underline R_b^-,T_s\underline R_b^+],
\]

并使用充放电分裂变量表达累计能量。

目标采用 epigraph 最坏情景代价：

\[
\min_{v,\epsilon,t}
t+\rho_\epsilon\|\epsilon\|_1+\rho_\Delta\|v-v^{\rm ref}\|_2^2
\]

\[
J_q(v)\le t,\quad\forall q.
\]

性能约束可有有界slack；所有资源物理约束保持硬约束。

### 必须实现
- explicit horizon；
- delay scenario states；
- command-history augmented state；
- cumulative energy；
- feasibility restoration；
- actual-action commit；
- SG-only backup；
- complete diagnostics；
- 2/4s周期；
- Plant A和Plant B公共接口。

### 文件
```text
src/direction1freq/controllers/cdsr_mpc.py
src/direction1freq/controllers/cdsr_feasibility_supervisor.py
src/direction1freq/models/delay_augmented_prediction.py
04_METHOD/CDSR_MPC_FORMULATION.md
04_METHOD/EQUATION_CODE_MAP.csv
tests/phase_f/test_f4_cdsr_mpc.py
```

### 成功判据
- 所有叫MPC的代码确实含状态/输入序列、预测动力学和在线优化；
- 不读取真实能力、真实负荷或未来事件；
- development中动作生成率100%；
- 资源硬约束违反为0；
- 对所有注册顶点预测；
- action history始终同步。

### 失败与自动处理
- 计算量过大：可减少冗余顶点或使用等价凸包，不得删除最坏边界；
- 若鲁棒包络使方法始终等价于SG-only，记录 `ROBUST_ENVELOPE_COLLAPSES_TO_SG_ONLY` 并进入停止判据；
- 不允许临时叠加RL、神经网络或模式分类。

### 衔接
F4方法进入F5证书和F6验证。

---

## F5：终端备份集合与理论边界

### 研究目标
使论文理论声明与真实代码一致。

### 必须完成
1. 对SG-only backup闭环计算可独立重算的控制不变/鲁棒不变集合 \(\mathcal X_f\)。
2. 所有延迟/能力顶点的终端预测必须进入 \(\mathcal X_f\)。
3. 给出以下至少一种严格结论：
   - 有限时域鲁棒约束满足；
   - 在注册初始可行域内的递归可行性；
   - backup切换后的正不变性。
4. 若无法证明递归可行，只允许声称：
   ```text
   finite-horizon robust feasibility plus empirically validated backup
   ```
5. 明确 assumptions、uncertainty coverage 和 theorem applicability。

### 输出
```text
05_THEORY/ASSUMPTIONS.md
05_THEORY/ROBUST_BACKUP_SET.npz
05_THEORY/ROBUST_BACKUP_SET_CERTIFICATE.json
05_THEORY/THEOREMS_AND_PROOFS.md
05_THEORY/NUMERICAL_CERTIFICATE_REPRODUCTION.py
tests/phase_f/test_f5_certificates.py
```

### 成功判据
- 证书可由独立脚本重算；
- 代码实际使用同一个集合；
- 不变性/包含误差低于预注册容差；
- 理论不依赖未来信息或真能力标签。

### 失败与自动处理
- 允许收缩理论声明，不允许伪称定理；
- 若终端集合为空：扩大prediction horizon或重新设计SG backup，最多两轮；
- 仍为空则停止为 `NO_NONEMPTY_ROBUST_BACKUP_SET`。

### 衔接
通过后进入F6。

---

## F6：development/validation 定型

### 研究目标
在未使用final seeds前决定方法是否值得进入final。

### 基线
必须实际实现并公平运行：

1. SG-only ACE PI；
2. fixed-allocation ACE PI；
3. nominal rolling MPC；
4. RLS adaptive rolling MPC；
5. single-worst-delay robust MPC；
6. capability-floor MPC without delay set；
7. CDSR-MPC；
8. current-capability rolling NMPC Oracle（evaluation only）。

### 实验
- Plant A全矩阵；
- Plant B代表矩阵；
- 2s/4s；
- 五种单机制变化；
- 300–600s事故；
- 1h正常净负荷；
- measurement noise、jitter、dropout；
- 连续两次能力变化；
- initial SoC变化；
- delay场景加密；
- 所有失败保留。

### Gate
- 方法成功率不低于最佳可部署基线2个百分点以上；
- failure-aware总体指标不劣化；
- 至少2/3核心指标改善≥8%，bootstrap CI下界>0；
- 物理硬约束违反0；
- primary+restoration action availability=100%；
- 未恢复的数学不可行率≤0.1%；
- backup/fallback率≤1%，且无连续级联；
- p99求解时间<0.5控制周期；
- Plant A/B方向一致；
- certificate范围内的episode满足证书。

### 自动处理
- 只允许两轮development/validation修复；
- 不得改变科学问题、事故范围或成功标准；
- 两轮后仍失败：输出完整负结果，停止，不消耗final seeds。

### 衔接
只有F6通过才锁定final。

---

## F7：final known/OOD预注册实验

### 研究目标
在冻结方法、权重、集合和阈值后进行一次性final评价。

### Known
- 单机制headroom/ramp/delay/energy/availability；
- 2/4s；
- 三种SG tension；
- 不同事故区域、符号和持续时间；
- 独立噪声/抖动/丢包因子。

### OOD
- headroom+delay组合；
- ramp+availability组合；
- 非对称充放电能力；
- 连续时变delay；
- 缓慢能力漂移；
- 新SoC和能量边界；
- Plant B未见接入位置或运行点。

### 统计
- success-first；
- scenario-balanced；
- paired bootstrap；
- paired failure表；
- solver/fallback原因；
- multiple-comparison控制；
- final seed firewall。

### 成功判据
- known和OOD分别报告，不混合；
- 不因某一OOD失败修改算法；
- 所有claim有对应结果表和失败反例；
- final完成后代码和配置只允许修复打包错误，不得改控制逻辑。

---

## F8：论文级分析、图表和审稿防线

### 研究目标
形成可以交给IEEE Transactions审稿人的完整证据链。

### 必须生成
- 科学问题框图；
- capability envelope示意；
- delay scenario预测结构；
- action-history/fallback状态机；
- Plant A/B；
- materiality；
- robust performance；
- solver/fallback；
- known/OOD；
- failure cases；
- ablation；
- certificate；
- computation time；
- claim-evidence matrix。

图形要求：
- SVG/PDF矢量；
- 600dpi PNG；
- 字体、单位和图例统一；
- 源数据和生成脚本齐全；
- 不使用只展示有利episode的图。

### 论文材料
```text
13_PAPER/PAPER_ROUTE.md
13_PAPER/CONTRIBUTIONS.md
13_PAPER/RESULTS_NARRATIVE.md
13_PAPER/REVIEWER_RISK_REGISTER.md
13_PAPER/SUPPORTED_AND_UNSUPPORTED_CLAIMS.md
```

---

## F9：完整可复现审查包

### 研究目标
生成一个真正可从解压目录运行的单一审查包。

### 成功判据
- 小于512MB；
- manifest和SHA256通过；
- 无环境目录、许可证、缓存和重复checkpoint；
- `reproduce_minimal`在全新临时目录中通过；
- `reproduce_all`命令完整；
- 源码、结果、失败、理论和论文材料齐全；
- Git clean；
- final状态不夸大。

最终文件名：

```text
DIRECTION1_PHASE_F_CDSR_MPC_SINGLE_REVIEW_PACKAGE.zip
```
