# Phase C 完整多阶段执行计划

## 总目标

一次性完成从科学问题重构、数学模型重建、代码修复、科学门验证、最终方法选择与实现、理论推导、完整实验、论文级图表到可复现审查包的全过程。Codex不得在各阶段等待用户再次发送Goal。

## 阶段总览

| 阶段 | 名称 | 核心产出 |
|---|---|---|
| C0 | 基线冻结与证据归档 | 只读旧包、Git基线、差异清单 |
| C1 | 文献与科学问题锁定 | 文献矩阵、假设、可证伪标准、禁止声明 |
| C2 | 单位统一与物理模型重建 | Plant A、Plant B、完整公式、参数来源 |
| C3 | 数学—代码一致性与物理验证 | 单元测试、能量守恒、步长收敛、跨模型校核 |
| C4 | 材料性与强Oracle验证 | 公平上界、材料性Gate、Pareto与失败分析 |
| C5 | 控制相关可辨识性与关键窗口 | Tcrit、Tdet、混淆、结构可辨识性Gate |
| C6 | 自动选择并实现最终方法 | 被动自适应 / 主动辨识 / 集合鲁棒三分支之一 |
| C7 | 理论硬化 | 递归可行性、安全性、估计/集合更新定理 |
| C8 | 完整实验与统计 | 基线、消融、OOD、鲁棒性、Plant A/B验证 |
| C9 | 论文级整理与审查包 | 图表、论文草案、复现材料、单一ZIP |

---

## C0：冻结当前基线与证据

### 研究目标

确保Phase B2所有结果只读保留，后续任何修正可追溯。

### 具体任务

1. 核验旧ZIP SHA256和文件清单。
2. 在真实仓库建立：
   - tag：`direction5-phase-b2-reviewed-invalidated`
   - branch：`direction5-phase-c-full-rebuild`
3. 保存旧结果、旧结论和本专家审查。
4. 生成完整仓库状态、依赖、求解器和硬件清单。
5. 建立阶段状态机 `progress/phase_status.json`。

### 输入文件

- 当前真实仓库；
- `D5_PHASE_B2_SCIENTIFIC_HARDENING_REVIEW_PACKAGE.zip`；
- 本启动包全部文件。

### 新建/修改文件

```text
research/phase_c_full_rebuild_and_method_completion/
progress/phase_status.json
progress/decision_ledger.md
artifacts_phase_c/baseline/
```

### 必须运行

- 旧包哈希验证；
- 旧测试重跑；
- 全新临时环境下导入检查。

### 成功判据

- 旧证据100%归档；
- 工作树基线清楚；
- 不覆盖任何Phase B2文件；
- 当前完整源码可枚举。

### 失败判据与自动处理

- 若旧仓库缺失：从审查包、Git diff和现有源码重建最小基线，记录所有缺口；
- 若旧测试不能运行：先修复环境/路径，不修改科学逻辑；
- 若核心源码不可恢复：标记 `FATAL_SOURCE_BASELINE_MISSING`，仍输出失败包后停止。

### 衔接

C0通过后自动进入C1。

---

## C1：文献调研、科学问题与创新边界锁定

### 研究目标

把方向五锁定为“控制相关能力变化的诊断与安全自适应”，避免退化成模式分类或方法堆叠。

### 具体任务

1. 优先检索 IEEE Transactions、Applied Energy、Automatica/TCST、Electric Power Systems Research 等正式来源；预印本只用于补充前沿。
2. 至少覆盖：
   - 黑箱IBR多模式建模；
   - 数据驱动频率控制/DeePC/Koopman MPC；
   - 在线变化检测与多模型控制；
   - set-membership/robust adaptive MPC；
   - dual control/安全主动辨识；
   - 多区域AGC和ACE责任；
   - IBR模型验证与OEM黑箱模型工程指南。
3. 建立至少40篇高相关文献的矩阵，至少25篇为正式期刊/会议原文，至少一半来自2021年以后。
4. 对每篇记录：问题、模型、是否多模式、是否在线变化、是否闭环频率控制、是否多区域、是否有安全保证、数据需求、局限。
5. 明确本文不可声称的创新。
6. 锁定主假设H1–H5和可证伪Gate。

### 输入文件

- `02_SCIENTIFIC_QUESTION_AND_NOVELTY.md`
- 当前代码和模型说明
- 可访问的IEEE/期刊/官方资料

### 输出文件

```text
research_outputs/science/SCIENTIFIC_QUESTION.md
research_outputs/science/HYPOTHESES_AND_FALSIFICATION.md
research_outputs/literature/LITERATURE_REVIEW.md
research_outputs/literature/LITERATURE_MATRIX.csv
research_outputs/literature/NOVELTY_COMPARISON_TABLE.md
research_outputs/literature/SOURCE_BIBLIOGRAPHY.bib
research_outputs/literature/SEARCH_LOG.md
```

### 必须运行/检查

- DOI/题目/年份自动校验；
- 引用存在性检查；
- 不得虚构文献、页码或结论。

### 成功判据

科学问题必须同时满足：

1. 真实：对应未通知能力变化与模型过时；
2. 明确：输入、隐藏量、可测量量、控制目标和部署边界明确；
3. 可证伪：Oracle材料性和Tdet/Tcrit均可使其失败；
4. 有价值：在至少一类合理紧约束场景中，正确能力知识有明确控制价值；
5. 与现有工作区分：不只是“模式发现+MPC”或“Koopman+MPC”。

### 失败判据与自动处理

- 若已有工作已完整覆盖相同问题：缩小到“多区域ACE责任+控制关键窗口+能力集合不确定性”的未覆盖交叉点；
- 若无法找到足够正式来源：记录检索限制，但不得虚构；继续模型验证，最终状态不得写“创新已证实”。

### 衔接

C1通过后进入C2，文献定义成为后续模型和实验的约束。

---

## C2：单位统一与物理模型重建

### 研究目标

建立物理量纲一致、能量守恒、服务分层清楚的 Plant A 和独立 Plant B。

### 具体任务

1. 采用统一的内部频率标幺变量 `omega_i = Delta f_i/f0`。
2. 按 `03_CORRECTED_PHYSICAL_MATHEMATICAL_MODEL.md` 实现两区域Plant A。
3. 重新实现SG governor/turbine、机械GRC、备用和抗积分饱和。
4. 重新实现共享PFR/SFR能力的BESS模型：功率、视在功率、电流、爬坡、能量、SoC、通信和服务可用性全部一致。
5. 已知训练regime一次只改变一个能力机制；复合变化只作为OOD。
6. 建立外部测量模型和未知负荷估计器，普通控制器不得读取真值。
7. 建立独立Plant B：优先ANDES原生Kundur/IEEE39 RMS/DAE，保留多机、网络、原生governor与母线级IBR；若环境确实无法支持，使用经基准验证的多机网络DAE替代并标记限制。
8. 参数全部注明来源、单位、范围和为何适用。

### 输入文件

- `03_CORRECTED_PHYSICAL_MATHEMATICAL_MODEL.md`
- `04_UNITS_PARAMETERS_AND_VALIDATION.md`
- 当前两区域代码可保留的软件结构

### 修改/新建

```text
src/d5freq/models/plant_a_two_area.py
src/d5freq/models/plant_b_native_rms.py
src/d5freq/models/bess_capability.py
src/d5freq/models/sg_governor_turbine.py
src/d5freq/models/measurement_model.py
src/d5freq/estimation/load_estimator.py
configs/phase_c/*.yaml
research_outputs/model/FULL_MATHEMATICAL_MODEL.md
research_outputs/model/FORMULA_CODE_MAP.csv
research_outputs/model/PARAMETER_SOURCES.csv
research_outputs/model/ASSUMPTIONS_AND_LIMITATIONS.md
```

### 必须运行

- 零扰动平衡；
- 解析初始RoCoF与数值RoCoF对照；
- 单区域/双区域功率平衡；
- tie-line符号和ACE符号；
- GRC；
- 功率/爬坡/视在功率/能量/SoC；
- 延迟、丢包和regime连续性；
- Plant A/B无控制基线。

### 成功判据

- 所有变量有明确单位；
- 解析RoCoF与细步长数值误差<1%；
- 能量守恒残差<1e-6 pu·h或配置定义的等价容差；
- SoC边界不存在自由能量；
- 总PFR+SFR共同受同一能力集合约束；
- 2/4s上层SFR与固定本地PFR严格分离；
- Plant B可运行并保留原生网络/多机动态。

### 失败判据与自动处理

- 单位审计失败：禁止进入后续阶段，修正单位和配置后重跑；
- Plant B依赖安装失败：尝试锁定兼容版本；仍失败则建立替代原生多机模型并标记 `NATIVE_EXTERNAL_TOOL_UNAVAILABLE`；
- 若能量/约束无法一致：重写执行器模型，不得用硬投影掩盖。

### 衔接

通过后进入C3。

---

## C3：数学—代码一致性、数值与跨模型验证

### 研究目标

证明代码确实实现公式，而不是只通过少量轨迹。

### 具体任务

1. 建立公式编号到函数/测试的映射。
2. 使用自动微分或有限差分核对连续/离散Jacobian。
3. 对 `dt={0.005,0.01,0.02,0.05}` 做步长收敛。
4. RK4与高精度参考积分器交叉验证。
5. Plant A与Plant B在匹配参数下比较惯量中心频率、ACE、tie-line和资源功率。
6. 进行极限场景：空头寸、SoC边界、通信丢失、SG饱和、IBR退出。
7. 检查普通控制器无真值泄露。

### 输出

```text
research_outputs/verification/MODEL_VERIFICATION_REPORT.md
research_outputs/verification/UNIT_TEST_REPORT.xml
research_outputs/verification/DT_CONVERGENCE.csv
research_outputs/verification/CROSS_MODEL_VALIDATION.csv
research_outputs/verification/NO_LEAKAGE_REPORT.md
figures_phase_c/model_validation/
```

### 成功判据

- 主要频率/ACE指标在推荐步长相对细步长误差<1%；
- 约束激活时误差<2%；
- 公式—代码映射覆盖100%核心方程；
- 无真值泄露测试全部通过；
- Plant A/B定性机制一致，差异有物理解释。

### 失败自动处理

- 数值不收敛：减小步长或换刚性/隐式积分器，不改物理参数；
- Plant A/B机制不一致：定位网络/聚合假设，修正或缩小声明；
- no-leakage失败：立即阻断后续，重构接口。

### 衔接

通过后进入C4。

---

## C4：材料性与强Oracle验证

### 研究目标

在任何新方法设计前，证明“知道当前真实能力”确实能带来可重复、足够大的控制价值。

### 具体任务

1. 实现统一信息集的部署基线：PI、nominal MPC、RLS-MPC/在线自适应基线。
2. 实现evaluation-only Oracle：
   - O1：知道当前能力regime的线性/LPV MPC；
   - O2：知道当前状态与当前能力、但不知道未来负荷/未来变化的**滚动多步非线性NMPC**；
   - O3：可选clairvoyant upper bound，单独报告。
3. O2每2/4s滚动求解；使用multiple shooting、物理约束和warm start；不得通过状态投影制造可行。
4. 所有部署方法使用相同测量和负荷估计；Oracle真值只用于上界。
5. 设计三档SG备用/爬坡、三档IBR容量、已知单机制regime、连续AGC与事故场景。
6. 先比较安全/成功概率，再比较共同成功样本的频率IAE、ACE IAE、tie-line IAE、恢复时间和资源使用。
7. 经济成本单独进行有量纲参数敏感性与Pareto，不作为唯一材料性门。

### 必须输出

```text
research_outputs/materiality/ORACLE_VALIDATION.md
research_outputs/materiality/ORACLE_SOLVER_LOG.parquet
research_outputs/materiality/MATERIALITY_RESULTS.parquet
research_outputs/materiality/MATERIALITY_DECISION.json
research_outputs/materiality/PARETO_RESULTS.parquet
```

### 成功判据（材料性Gate）

在Plant A和Plant B中至少满足其一，且无新增物理越限：

1. Oracle相对最佳部署基线在至少两个核心控制指标上场景平衡改善≥10%，95%配对Bootstrap区间下界>0；或
2. 在至少一类合理紧约束场景中，Oracle把失败率降低≥20个百分点；或
3. Oracle在相同资源使用预算下显著改善频率/ACE/tie-line Pareto前沿。

同时 O2：

- ≥95%预注册场景求解成功；
- KKT/约束残差满足预设门；
- 网格/多初值/独立rollout验证通过；
- 不使用未来信息。

### 失败判据与自动处理

- Oracle求解失败：先修复数值尺度、平滑约束、warm start和多初值；不得改变场景降低难度；
- Oracle无价值且Plant A/B均如此：输出 `PROBLEM_NOT_MATERIAL`，停止C5–C9方法开发，但仍完成负结果报告和最终包；
- Plant A有价值、Plant B无价值：标记 `NATIVE_MODEL_NOT_VALIDATED`，继续C5但禁止论文强声明；
- 成本差但控制价值明显：保留Pareto，不以任意成本权重否决问题。

### 衔接

材料性通过后进入C5。

---

## C5：控制相关可辨识性与控制关键窗口

### 研究目标

判断仅靠正常外部I/O是否能在错误模型产生实质损失之前识别能力变化。

### 具体任务

1. 所有关键场景采用：正常运行预热 → 未通知能力变化 → 后续扰动/AGC，禁止一开始就处于异常模式。
2. 设计单机制能力变化：headroom、ramp、delay、energy、availability；复合作为OOD。
3. 建立未知负荷估计器，检测器不得使用真实负荷。
4. 定义控制相关距离：预测差、最优动作差、可行能力集合Hausdorff距离。
5. 定义控制关键时间：错误名义模型相对正确能力控制器首次造成安全越限或超过物理阈值的控制损失时间。
6. 实现被动多模型/集合残差检测，记录检测延迟、误报、混淆和删失。
7. 计算局部Fisher/信息矩阵或可辨识性Gramian；设置无激励负控制以证明结构不可辨识边界。
8. 比较 `P(Tdet<Tcrit)`。

### 输出

```text
research_outputs/identifiability/CONTROL_RELEVANT_REGIMES.md
research_outputs/identifiability/TCRITICAL.parquet
research_outputs/identifiability/TDETECT.parquet
research_outputs/identifiability/IDENTIFIABILITY_REPORT.md
research_outputs/identifiability/SOURCE_CONFUSION.csv
research_outputs/identifiability/INFORMATION_METRICS.parquet
research_outputs/identifiability/BRANCH_DECISION.json
```

### Gate与自动分支

- `MATERIAL_PASSIVE_IDENTIFIABLE`：在关键场景中 `P(Tdet<Tcrit)≥0.8`，误报率≤5%，进入C6-A；
- `MATERIAL_ACTIVE_IDENTIFICATION_NEEDED`：被动不足，但安全可行域允许有限辨识激励，进入C6-B；
- `MATERIAL_STRUCTURALLY_UNIDENTIFIABLE`：候选能力在允许输入下不可区分，进入C6-C；
- `INCONCLUSIVE_MODEL_OR_ESTIMATOR_LIMITED`：先改进负荷估计/模型集后重做一次，不得无限迭代；第二次仍不确定则进入C6-C保守方案。

### 失败自动处理

- 负荷与能力变化混淆：提高测量/估计结构，不得使用真值；
- 模式标签不可分但控制动作等效：合并为一个control-relevant regime；
- 无激励场景不可识别：保留为负控制，不得宣称通用识别。

### 衔接

自动选择且只选择一个C6分支。

---

## C6：实现最终方法（自动选择一个分支）

### C6-A：被动可辨识 → Control-Relevant Set-Adaptive MPC

- 模型/能力集合库；
- 窗口残差与集合收缩；
- library-regularized RLS/LPV更新；
- tube/constraint-tightened MPC；
- 渐进式调频责任转移；
- 终端安全/backup控制器。

### C6-B：需要主动辨识 → Safe Dual Frequency MPC

- 在安全可行域内同时优化调频与信息增益；
- 识别激励预算；
- 对ACE/频率/功率设置严格鲁棒约束；
- 只有预期信息收益超过阈值且backup可行时才激励；
- 超时/不确定时转为鲁棒backup。

### C6-C：结构不可辨识 → Capability-Set Robust MPC

- 不再分类模式；
- 直接维护能力参数集合；
- set-membership更新；
- 对整个集合做min-max/tube MPC；
- 随数据收缩集合但始终保留真实plant高概率覆盖。

### 共同要求

1. 最终方法必须是一个统一控制器，而不是分类器、MPC和启发式回退的松散堆叠。
2. 普通运行中不得读取真值。
3. 与PI、nominal MPC、RLS-MPC、robust MPC、Oracle比较。
4. 不能通过删除worst case或过度收缩权限换取表面安全。
5. 记录在线计算时间、不可行率和fallback占比。

### 输出

```text
src/d5freq/controllers/proposed_phase_c/
research_outputs/method/METHOD_SPEC.md
research_outputs/method/ALGORITHM_PSEUDOCODE.md
research_outputs/method/FORMULA_CODE_MAP.csv
research_outputs/method/COMPUTATIONAL_COMPLEXITY.md
```

### 成功判据

相对最佳可部署基线，在Plant A和Plant B中：

- 安全/科学成功率不低；
- 至少两个主要指标场景平衡改善≥8%，置信区间支持；
- 对已知和OOD能力变化均不发生系统性退化；
- 99百分位在线求解时间小于上层控制周期的50%；
- 求解不可行率≤1%；
- 不依赖真值标签。

### 失败自动处理

按顺序诊断：代码→数值尺度/求解器→模型预测→估计器→方法假设。最多允许两轮有依据修复；不得盲目大范围调参。两轮后仍失败，保留失败结果并将状态设为 `METHOD_NOT_SUPPORTED_BY_EVIDENCE`，继续C7–C9整理负结果。

---

## C7：理论推导与安全硬化

### 研究目标

给最终分支建立与实际实现一致的理论保证。

### 具体任务

- 建立离散预测模型和不确定集合；
- 证明集合更新不排除真值的条件或概率覆盖条件；
- 构造终端集/backup不变集；
- 证明递归可行性；
- 证明频率/ACE/资源约束在假设下满足；
- 对主动辨识分支证明激励只在安全域内发生；
- 明确非线性Plant上结论属于验证而非全局证明。

### 输出

```text
research_outputs/theory/FULL_THEORETICAL_DERIVATION.md
research_outputs/theory/THEOREMS_AND_PROOFS.md
research_outputs/theory/ASSUMPTION_SCOPE_TABLE.md
research_outputs/theory/NUMERICAL_CERTIFICATES/
```

### 成功判据

- 定理假设与代码一致；
- 不把线性/LPV结论夸大到全非线性OEM系统；
- 每个定理有数值证书或单元测试；
- 不存在依靠不可测真值的假设。

### 失败自动处理

若无法证明完整稳定性，至少给出递归可行性、约束安全和backup切换保证；若连这些都不成立，修改控制结构而不是弱化声明。最多一次结构修复。

---

## C8：完整论文级实验

### 研究目标

系统验证科学假设、方法优势、边界和失败模式。

### 必须实验

1. 正常连续净负荷/AGC：至少1 h；
2. 180–600 s阶跃、斜坡、脉冲、持续偏差；
3. 能力变化发生在扰动前、同时、之后；
4. headroom、ramp、delay、energy、availability单机制；
5. 未训练复合OOD与渐变漂移；
6. SG adequate/scarce/critical；
7. SoC、噪声、丢包、参数不确定性；
8. Plant A与原生Plant B；
9. 基准、消融、敏感性、鲁棒性、失败案例；
10. active分支需信息收益/激励成本消融；
11. passive/robust分支需模型库、集合大小、收紧程度消融。

### 统计

- 开发、验证、最终种子严格分离；
- known ≥30 final seeds/场景；OOD ≥50；
- 全因子或明确Latin hypercube，不能用seed隐式绑定SG/噪声；
- failure-first/hurdle分析；
- 配对Bootstrap；
- 场景平衡；
- 多重比较校正；
- 报告效应量和置信区间，不只报p值。

### 成功判据

- 结果支持C1假设；
- Plant A/B趋势一致；
- 所有不利结果保留；
- 核心结论不依赖单一权重、单一场景或少数seed；
- 失败边界被明确说明。

### 失败自动处理

若只在Plant A有效：降级为方法概念论文，不得声称工程普适；若对OOD系统性失败：缩小适用范围并把失败作为主要限制；若统计不显著：不得继续调final数据，保留负结论。

---

## C9：论文、图表与完整审查包

### 研究目标

形成一次性可审查、可复现、可判断投稿潜力的材料。

### 输出

- 科学问题、假设、文献、模型、定理、方法、实验和限制全套文档；
- 论文级主图、补充图、三线表；
- 论文结构草稿和结果叙事；
- 完整源码、配置、环境、测试；
- 原始逐episode指标和必要轨迹；
- 一键复现脚本；
- 单一ZIP及SHA256。

### 成功判据

符合 `09_FINAL_REVIEW_PACKAGE_SPEC.md`；ZIP<512MB；在全新环境通过最小复现和主要图表再生；文件清单和哈希完整。

### 失败自动处理

先删除缓存、环境、solver临时文件、重复图、checkpoint；对大轨迹使用Parquet/Zstd和float32；不得删除支撑结论的逐episode指标、失败日志和代表性原始轨迹。
