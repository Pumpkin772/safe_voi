# 方向1 Phase E 完整多阶段执行计划

## 总目标

在一个 Codex Goal 内，完成 Phase D 负结果的科学恢复，建立稳定、物理合理、因果可审计的多区域频率控制平台；先证明黑箱 IBR 当前能力知识的控制材料性，再判断自然闭环数据是否足以更新控制相关能力集合；依据预注册 Gate 自动选择并完成一个最终方法，完成理论、代码、实验、论文级结果和单一审查包。

## 总体顺序

`E0 → E1 → E2 → E3 → E4 → E5 → E6 → E7 → E8 → E9`

只有 Gate 指定的致命失败才允许提前停止。阶段失败时必须按“代码→数值/求解器→参数→模型→方法→科学假设”顺序诊断。

---

## E0：冻结旧证据并建立科学恢复基线

### 研究目标

保留 Phase D 全部证据，撤回无效 H2 科学外推，建立干净的新分支和不可覆盖的证据目录。

### 输入文件

- Phase D 完整审查包；
- 当前 Git 仓库；
- 本治理包全部文件。

### 具体任务

1. 核验 Phase D ZIP、文件清单、Git commit 和环境。
2. 创建 tag：`direction1-phase-d-negative-reviewed`。
3. 创建 branch：`direction1-phase-e-science-recovery`。
4. 将 Phase D 结果复制/链接为只读证据，不修改原 CSV/Parquet/JSON。
5. 运行 `reference/independent_audit_reproduction.py`，复现：
   - 名义闭环自激；
   - delay set 已更新但 update_time 未记录；
   - 原 control-loss time 的定义问题。
6. 建立 `progress_phase_e/E0.json`。

### 新建或修改文件

```text
research_outputs_phase_e/forensic/PHASE_D_INVALIDATION_REPORT.md
research_outputs_phase_e/forensic/INDEPENDENT_AUDIT_RESULTS.json
research_outputs_phase_e/forensic/PHASE_D_EVIDENCE_INDEX.csv
progress_phase_e/E0.json
```

### 必须运行的实验

- Phase D manifest 复核；
- 旧闭环 200 s 小扰动测试；
- delay seed 的 update-event 重放；
- 原 Gate 重算。

### 成功判据

- 旧证据 100% 可追溯；
- 三项决定性问题可由独立脚本复现；
- Phase D 文件未被覆盖；
- 新 Git 分支干净。

### 失败判据

- 无法恢复完整源码或关键原始数据；
- 哈希不一致且无法解释；
- 独立复现与包内代码不一致。

### 自动处理

先从 ZIP 恢复；再从 Git commit 恢复；仍无法恢复则输出 `FATAL_BASELINE_INCOMPLETE` 并进入 E9 负结果打包。

### 衔接

E0 通过后进入 E1。

---

## E1：文献、科学问题、假设和创新边界锁定

### 研究目标

把方向1锁定为控制问题，而不是 OEM 模式分类问题；建立可证伪假设和明确文献差异。

### 输入文件

- Phase D 文献矩阵；
- 本包 `02_CORRECTED_SCIENTIFIC_QUESTION_AND_HYPOTHESES.md`；
- 2020–当前的 IEEE Transactions、Automatica、Applied Energy、NERC/FERC 等正式来源。

### 具体任务

1. 执行可审计检索，优先正式期刊/标准；预印本只能标注为邻近前沿。
2. 至少纳入 50 篇高相关文献，其中：
   - 黑箱 IBR/多模式建模 ≥10；
   - 数据驱动/黑箱频率控制 ≥10；
   - set-membership/adaptive/tube MPC ≥10；
   - active/dual control 与安全辨识 ≥8；
   - 多区域 AGC、ACE、约束资源 ≥10。
3. 建立“已有工作解决了什么/未解决什么/本项目区别”矩阵。
4. 锁定 H1–H5、信息边界、停止规则、允许的最终方法分支。
5. 禁止以“首次使用 MPC/AI/集合估计”为创新声明。

### 新建文件

```text
01_SCIENCE/SCIENTIFIC_QUESTION_AND_HYPOTHESES.md
01_SCIENCE/CLAIM_BOUNDARY.md
02_LITERATURE/SEARCH_PROTOCOL.md
02_LITERATURE/SEARCH_LOG.csv
02_LITERATURE/LITERATURE_MATRIX.csv
02_LITERATURE/NOVELTY_COMPARISON.md
02_LITERATURE/REFERENCES.bib
02_LITERATURE/METADATA_VERIFICATION.json
progress_phase_e/E1.json
```

### 必须运行的检查

- DOI/题名/期刊/年份元数据校验；
- 重复文献检查；
- 至少3个最接近工作的逐项对比；
- 论文声明—证据映射。

### 成功判据

- 问题真实、明确、可证伪；
- 创新交叉未被现有工作完整覆盖；
- 所有声明不超出证据和服务范围；
- 文献无伪造、无元数据冲突。

### 失败判据

- 已存在工作同时完成“未通知能力变化、因果能力集合、材料性/关键窗口、多区域安全责任重分配”；
- 问题无法用可观测量定义；
- 只能依赖隐藏标签才能成立。

### 自动处理

只允许收缩科学声明和服务范围；不得仅更换算法制造新颖性。若收缩后仍无创新，输出 `NOVELTY_NOT_SUPPORTED` 并进入 E9。

### 衔接

E1 通过后进入 E2。

---

## E2：重建稳定名义闭环、Plant A 和 Plant B

### 研究目标

在任何可辨识性实验前，建立稳定、量纲一致、服务分层清楚、跨模型可验证的频率控制平台。

### 输入文件

- Phase D Plant A/B/BESS；
- `03_MODEL_AND_BASELINE_REBUILD_SPEC.md`；
- 参数来源表。

### 具体任务

1. 保留标幺频率摆动方程，统一全部单位与符号。
2. 固定本地 PFR；上层 SFR 主周期 4 s，2 s 作为敏感性。
3. 设计稳定的常规 ACE PI/LQI 基线：
   - 先在线性离散模型上检验闭环极点/谱半径；
   - 再在非线性饱和、GRC、延迟模型上验证。
4. 显式 anti-windup；禁止依靠状态硬投影掩盖不稳定。
5. Plant A：两区域透明聚合模型。
6. Plant B：ANDES Kundur 或 IEEE39 原生多机 RMS/DAE；BESS有功必须真正进入网络功率平衡。
7. 对 Plant A/B 做相同小扰动、阶跃、无扰动和控制输入试验。
8. 实现统一延迟模块，所有入口共享。
9. 对 BESS 做功率、爬坡、能量、SoC、PFR/SFR共享能力审计。

### 修改/新建文件

```text
src/direction1freq/models/plant_a_v2.py
src/direction1freq/models/plant_b_andes_v2.py
src/direction1freq/models/bess_capability_v2.py
src/direction1freq/controllers/ace_pi_aw.py
src/direction1freq/controllers/lqi_baseline.py
src/direction1freq/simulation/delay_channel.py
03_MODEL/MATHEMATICAL_MODEL.md
03_MODEL/EQUATION_CODE_MAP.csv
03_MODEL/UNITS_AND_PARAMETERS.csv
03_MODEL/PARAMETER_SOURCES.md
06_VERIFICATION/CLOSED_LOOP_STABILITY_REPORT.md
06_VERIFICATION/PLANT_A_B_CROSS_VALIDATION.md
progress_phase_e/E2.json
```

### 必须运行的实验

- 零扰动平衡点；
- `1e-6 pu` 小频率扰动 300 s；
- 0.0015 pu 背景负荷 1 h；
- 0.02/0.05/0.08 pu 阶跃 300–600 s；
- 2 s 与4 s SFR；
- dt 收敛：0.1/0.05/0.02/0.01 s；
- Plant B 原生事件 vs 外部控制接口；
- BESS能量守恒与边界事件；
- SG GRC/饱和/anti-windup。

### 成功判据

- 小扰动离散闭环谱半径 <0.98（按4 s控制步）或等价稳定裕度；
- 零负荷无自激振荡；
- 小背景负荷下SFR不劣化无SFR基线，且频率RMS处于合理量级；
- Plant A功率平衡残差 p99 ≤1e-8 pu；
- BESS能量残差 ≤1e-9 MWh/步；
- dt=0.02 与0.01 s主要频率指标差≤1%；
- Plant B外部控制与原生事件接口相同输入轨迹误差≤预注册阈值；
- 所有约束无硬投影“修复”痕迹。

### 失败判据

- 名义闭环仍自激；
- Plant B BESS功率不进入网络平衡；
- ANDES/Plant A趋势相反且无法解释；
- 能量或功率守恒失败。

### 自动处理

允许按顺序修复：符号/单位→离散化→anti-windup→控制增益（在预注册稳定域内）→模型接口。最多两轮。仍失败输出 `FATAL_PHYSICAL_OR_CLOSED_LOOP_MODEL_FAILURE`，进入 E9。

### 衔接

E2 通过后进入 E3。

---

## E3：可信 rolling Oracle 与科学材料性验证

### 研究目标

先回答“知道当前真实能力是否真的有控制价值”，再研究如何获得该信息。

### 输入文件

- E2合格 Plant A/B；
- 隐藏能力事件；
- `04_ORACLE_MATERIALITY_AND_CAUSAL_INFORMATION_PROTOCOL.md`。

### 具体任务

1. 建立以下公平基线：
   - SG-only ACE PI/LQI；
   - 固定比例 SG/IBR；
   - nominal-model linear MPC；
   - online RLS adaptive MPC；
   - worst-case capability-set robust MPC。
2. 建立 evaluation-only `O2 current-capability rolling NMPC`：
   - 只知道当前时刻真实能力和当前物理状态；
   - 不知道未来负荷、未来切换和未来通信；
   - 每个SFR周期滚动重求解；
   - multiple shooting、warm start、约束残差/KKT记录。
3. 单独测试 headroom、ramp、delay、energy、availability/service。
4. 定义材料性：成功率、频率IAE、ACE IAE、tie-line IAE、约束、总资源成本。
5. Plant A完整矩阵，Plant B代表矩阵。

### 新建文件

```text
src/direction1freq/controllers/nominal_mpc.py
src/direction1freq/controllers/rls_adaptive_mpc.py
src/direction1freq/controllers/robust_capability_mpc.py
src/direction1freq/controllers/oracle_current_capability_nmpc.py
04_ORACLE/ORACLE_FORMULATION.md
04_ORACLE/ORACLE_QUALIFICATION.csv
08_RESULTS/E3_MATERIALITY_EPISODES.parquet
09_SUMMARY/E3_MATERIALITY_SUMMARY.csv
progress_phase_e/E3.json
```

### 必须运行的实验

- SG reserve adequate/scarce/critical，全因子独立；
- 五类单机制能力变化；
- 变化前后无负荷、同步负荷、延迟负荷、连续扰动；
- 4 s主分析，2 s敏感性；
- Plant A每格≥20 seeds；Plant B每格≥5代表seeds；
- Oracle网格、预测时域和求解容差敏感性。

### 成功判据

- Oracle求解成功率≥95%，p99约束残差≤1e-5；
- 在至少两类物理机制和两类SG紧张度下，Oracle相对最佳可部署基线满足其一：
  - 物理成功率提高≥10个百分点；
  - 或频率/ACE/tie-line中至少两项改善≥10%，配对CI不跨0；
- Plant A和Plant B结论方向一致。

### 失败判据

- 合格Oracle相对简单鲁棒基线无材料收益；
- 只有极端/不合理参数下才有收益；
- Plant A有价值但Plant B完全无价值且无法解释。

### 自动处理

先修Oracle数值与信息公平；最多两轮。合格Oracle仍无材料性则输出 `PROBLEM_NOT_MATERIAL`，保存负结果并进入 E9，不再研究辨识。

### 衔接

材料性通过后进入 E4。

---

## E4：纠正后的因果被动可辨识性与控制关键窗口

### 研究目标

在稳定闭环和有材料性的前提下，判断自然运行数据是否足以在控制损失前更新能力集合。

### 输入文件

- E2稳定闭环；
- E3 Oracle及匹配重放；
- 五类能力事件；
- 允许的公共测量。

### 具体任务

1. 重新定义控制关键时间：
   - 从变化时刻起，旧模型控制与 current-capability Oracle 的反事实损失差首次达到预注册材料阈值；
   - 同时记录实际频率/ACE/tie-line/约束损失时间。
2. `update_time` 由能力集合发生控制相关变化且重新覆盖真值的时刻定义，不能只由alarm定义。
3. 实现至少三种合理被动基线：
   - 多步 set-membership capability estimator；
   - GLR/CUSUM change detector + set reset；
   - Bayesian/IMM或interval observer。
4. 使用全部允许的公共量和因果负荷估计，不读取真值。
5. 区分：
   - 结构不可辨识；
   - 激励不足；
   - 有限样本失败；
   - 估计器设计失败。
6. 测试2/4 s、Plant A/B、不同噪声和变化时刻。

### 新建文件

```text
src/direction1freq/identification/passive_set_membership.py
src/direction1freq/identification/causal_glr.py
src/direction1freq/identification/imm_capability.py
src/direction1freq/evaluation/control_critical_window.py
05_IDENTIFICATION/PASSIVE_IDENTIFIABILITY_REPORT.md
08_RESULTS/E4_PASSIVE_EPISODES.parquet
09_SUMMARY/E4_PASSIVE_COVERAGE_TIMING.csv
progress_phase_e/E4.json
```

### 必须运行的实验

- 五种单机制变化；
- no-excitation负控制；
- load-only与capability-only混淆；
- 随机变化时刻；
- 正常1 h与事故300–600 s；
- 估计集合覆盖、宽度、false alarm、更新时延、Tdet/Tcrit。

### 成功判据（Passive Gate）

- joint truth coverage ≥95%；
- no-change false alarm ≤5%；
- 因果 update-time 计算通过单元测试；
- 至少3/5机制满足 `P(Tdet<Tcrit)≥0.8`；
- 估计集合宽度相对全局集合有实质收缩；
- Plant A/B方向一致。

### 失败判据

- 在合理基线和自然闭环下 coverage/timing仍失败；
- upper capability在安全运行范围内结构不可辨识；
- 因果负荷与能力变化无法区分。

### 自动处理

允许两轮：模型误差界校准→多步窗口/集合更新修正。禁止只调阈值降低false alarm而牺牲覆盖。若通过，选择分支P；若失败但H1材料性通过，进入 E5 判断安全主动信息是否可行。

### 衔接

- Passive Gate通过：跳过主动探测可行性，E6选择分支P；
- 未通过：进入E5。

---

## E5：安全主动能力辨识可行性与最终分支选择

### 研究目标

当自然闭环信息不足时，判断能否在不破坏频率安全的条件下主动获取控制相关能力信息。

### 输入文件

- E3材料性结果；
- E4被动失败证据；
- 稳定SG备份控制器；
- 能力集合和安全约束。

### 具体任务

1. 构造零均值/补偿式探测：
   - IBR探测增量与可靠SG/其他资源补偿；
   - 明确动态不完全抵消误差。
2. 定义信息指标：预测集合直径缩减、Fisher/Gramian最小特征值、预期集合体积。
3. 设计安全备份轨迹：任一探测候选必须存在可行SG backup。
4. 比较：无探测、固定微扰、优化探测。
5. 记录探测导致的频率、ACE、tie-line、里程和能量代价。

### 新建文件

```text
src/direction1freq/identification/safe_probe_design.py
src/direction1freq/controllers/backup_safe_controller.py
05_IDENTIFICATION/ACTIVE_IDENTIFICATION_FEASIBILITY.md
08_RESULTS/E5_ACTIVE_FEASIBILITY.parquet
09_SUMMARY/E5_INFORMATION_SAFETY_TRADEOFF.csv
progress_phase_e/E5.json
```

### 必须运行的实验

- 探测幅值/时长/频带敏感性；
- 五类能力变化；
- 不同SG余量；
- Plant A全矩阵、Plant B代表矩阵；
- 探测同时发生负荷扰动的失败场景。

### 成功判据（Active Gate）

- 不增加物理失败率；
- 频率/ACE安全阈值无显著恶化；
- 至少3/5机制 `P(Tdet<Tcrit)≥0.8`；
- 相对被动估计显著提高信息量/集合收缩；
- 探测能量和里程低于预注册预算；
- 在合理SG余量下存在可行backup。

### 失败判据

- 所有安全探测都无法改善可辨识性；
- 探测导致不可接受频率/ACE风险；
- 只有读取隐藏参数才能设计有效探测。

### 自动处理

只允许两轮物理有据的探测设计修正。若通过，E6选择分支A；若失败，E6选择分支R（无辨识鲁棒能力集合控制）。不得临时切换到RL或神经网络。

### 衔接

进入E6，仅实现预注册选择的一个分支。

---

## E6：实现唯一最终方法

### 研究目标

依据 E4/E5 Gate，只实现一个方法，并与真实MPC基线公平比较。

### 分支P：被动能力集合自适应管束MPC

适用条件：Passive Gate通过。

核心：因果能力集合更新 + tube MPC + SG终端备份。

### 分支A：安全主动能力辨识双重管束MPC

适用条件：Passive Gate失败、Active Gate通过。

核心：同一滚动优化同时决定调频与安全探测，目标含控制代价和预期集合收缩；每个学习轨迹绑定backup安全轨迹。

建议名称：

`SACID-TMPC` — Safe Active Capability Identification Dual Tube MPC。

### 分支R：能力集合鲁棒MPC

适用条件：被动和主动辨识均不满足Gate，但H1材料性成立。

核心：不宣称识别当前能力，只在全局/在线可证集合上进行鲁棒责任分配。

### 共通任务

1. 真正滚动时域优化；
2. 状态/输入/频率/ACE/tie-line/功率/爬坡/能量约束；
3. disturbance/load estimator error tube；
4. terminal invariant/backup set；
5. solver status、fallback和不可行原因；
6. p99计算时间和控制周期约束。

### 新建文件

```text
src/direction1freq/controllers/proposed_<selected_branch>.py
src/direction1freq/optimization/tube_propagation.py
src/direction1freq/optimization/terminal_backup.py
06_METHOD/SELECTED_BRANCH.json
06_METHOD/FORMULATION.md
06_METHOD/IMPLEMENTATION_MAP.csv
progress_phase_e/E6.json
```

### 必须运行的实验

- 单步可行性；
- 递归闭环；
- 约束边界；
- 故意solver timeout/failure；
- fallback切换；
- development/validation矩阵。

### 成功判据

相对最佳可部署基线：

- 物理成功率不低超过2个百分点；
- 至少两项核心指标改善≥8%，配对CI支持；
- solver infeasibility≤1%；
- p99求解时间 <0.5×SFR周期；
- 无真值泄露；
- Plant A和Plant B方向一致。

### 失败判据

- 仅相对弱基线有效；
- 无法满足实时性或递归可行；
- 优势只存在于调过的开发场景；
- 违反安全/能力约束。

### 自动处理

最多两轮有依据的development/validation修复；不能使用final seeds。仍失败则保存 `METHOD_NOT_SUPPORTED_BY_EVIDENCE`，跳转E9，不更换分支。

### 衔接

通过后进入E7。

---

## E7：理论推导和证书

### 研究目标

使理论声明与实际代码一一对应，不写超出实现的定理。

### 具体任务

1. 建立离散增广频率模型和误差动力学。
2. 给出能力集合/参数集合更新的一致性条件。
3. 构造 tube/RPI 或有限时域可达集合。
4. 给出约束收紧、终端集和SG backup条件。
5. 证明递归可行性和鲁棒约束满足。
6. 分支A额外给出：探测轨迹与backup轨迹的安全切换条件；不声称全局双重最优。
7. 所有假设、定理、证明与代码对象建立映射。

### 新建文件

```text
03_MODEL/FULL_MATHEMATICAL_DERIVATION.md
07_THEORY/ASSUMPTIONS.md
07_THEORY/THEOREMS_AND_PROOFS.md
07_THEORY/NUMERICAL_CERTIFICATES.npz
07_THEORY/THEORY_CODE_TRACEABILITY.csv
progress_phase_e/E7.json
```

### 必须运行的验证

- RPI/terminal set数值证书；
- 随机顶点和最坏顶点约束验证；
- 代码与公式矩阵一致性；
- fallback可达性测试。

### 成功判据

- 每个定理的所有假设均有代码/参数证据；
- 数值证书可独立重算；
- 理论只覆盖实际实现的模型和约束；
- 无“有MPC名称但无优化器”或“有定理但代码未实现”的情况。

### 失败判据

- 递归可行性无法建立；
- 终端backup不存在；
- 实现依赖理论未包含的硬投影/隐藏信息。

### 自动处理

允许收缩理论声明和运行域；不得伪造全局稳定性。收缩后仍无法提供安全证书则将结果标记为 empirical method，不得声称 stability-guaranteed，并继续E8但降低论文定位。

### 衔接

进入E8。

---

## E8：预注册 final 实验、论文级分析与失败案例

### 研究目标

完成公平、独立、跨模型、可复现的最终证据。

### 具体任务

1. 在运行前冻结：控制器、参数、manifest、seeds、指标、统计脚本和哈希。
2. 运行所有基线、Oracle、proposed、消融。
3. 机制因素独立全因子或分层LHS，不通过seed取模编码多个因素。
4. 成功优先统计；not_evaluated、solver_failure、physical_failure分开。
5. Known/OOD、噪声、负荷、通信、SoC、SG余量、2/4s、Plant A/B。
6. 运行1 h正常工况与300–600 s事故/连续事故。
7. 输出完整代表性轨迹和最差失败轨迹。
8. 生成论文级图表与源数据。

### 新建文件

```text
07_EXPERIMENT/FINAL_MANIFEST.csv
07_EXPERIMENT/FINAL_LOCK.json
08_RESULTS/episode_metrics.parquet
08_RESULTS/control_grid_trajectories.parquet
08_RESULTS/failure_trajectories/
09_SUMMARY/baseline_comparison.csv
09_SUMMARY/ablation.csv
09_SUMMARY/sensitivity.csv
09_SUMMARY/robustness.csv
09_SUMMARY/known_ood.csv
10_FIGURES/paper/
10_FIGURES/source_data/
11_FAILURES/FAILURE_LEDGER.csv
12_ANALYSIS/RESULTS_INTERPRETATION.md
progress_phase_e/E8.json
```

### 必须运行的比较

- SG-only PI/LQI；
- fixed allocation PI；
- nominal MPC；
- RLS adaptive MPC；
- worst-case robust tube MPC；
- current-capability Oracle；
- selected proposed；
- 关键消融。

### 成功判据

- final矩阵100%完成或所有缺失有明确技术原因；
- proposed在known和至少一个OOD维度上满足E6性能门；
- 不以删除失败或宽松阈值制造优势；
- 结果跨Plant A/B方向一致；
- 统计CI、效应量和场景平衡均完整。

### 失败判据

- final优势消失；
- 安全/约束恶化；
- 结果只在单一Plant或单一seed成立；
- 方法计算时间不可部署。

### 自动处理

final运行后只允许修复代码崩溃、数据损坏或求解器配置错误，且必须重跑受影响的全部方法和场景。禁止修改算法、权重、阈值和场景。

### 衔接

进入E9。

---

## E9：论文材料、复现材料和单一审查包

### 研究目标

形成下一轮一次性统一审查所需的完整证据包。

### 具体任务

1. 撰写科学问题、文献、模型、方法、理论、实验和限制。
2. 生成论文级SVG/PDF/600dpi PNG及表格源数据。
3. 提供一键最小复现和全量复现命令。
4. 清理缓存、环境、checkpoint、重复文件。
5. 保留所有结论所需的原始指标；细步轨迹按保留政策压缩。
6. 生成完整文件清单、SHA256、Git status和最终状态。

### 最终输出

`DIRECTION1_PHASE_E_SCIENCE_RECOVERY_AND_CAPABILITY_CONTROL_SINGLE_REVIEW_PACKAGE.zip`

### 成功判据

- ZIP <512MB；
- 文件清单和哈希100%通过；
- 源码可安装、最小复现可运行；
- 失败、负结果和未评估均完整；
- 最终状态只使用预注册枚举值。

### 最终状态枚举

```text
SCIENTIFIC_QUESTION_NOT_NOVEL
FATAL_PHYSICAL_OR_CLOSED_LOOP_MODEL_FAILURE
PROBLEM_NOT_MATERIAL
PASSIVE_SET_ADAPTIVE_METHOD_SUPPORTED
SAFE_DUAL_METHOD_SUPPORTED
ROBUST_SET_METHOD_SUPPORTED
PASSIVE_CAPABILITY_SET_NOT_SUPPORTED
ACTIVE_IDENTIFICATION_NOT_SAFE
METHOD_NOT_SUPPORTED_BY_EVIDENCE
EMPIRICAL_ONLY_THEORY_NOT_CERTIFIED
FULL_RESEARCH_PACKAGE_READY
```
