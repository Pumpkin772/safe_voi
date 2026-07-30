# Phase B2 项目计划：科学模型加固、强 Oracle 与证伪

## 总目标

建立一套可用于决定方向五是否值得继续的、物理可解释、统计无歧义的验证体系。完成后必须给出以下唯一结论之一：

- `PROBLEM_NOT_MATERIAL`
- `MODEL_MISMATCH_DOMINANT`
- `PASSIVE_IDENTIFIABILITY_DOMINANT`
- `CONTROL_DESIGN_DOMINANT`
- `COMBINED:<primary>+<secondary>`
- `INCONCLUSIVE_REQUIRES_MORE_EVIDENCE`

禁止在没有触发任何预注册条件时强制选择 bottleneck。

## Phase B2-0：冻结与完整性核验

任务：

1. 从 Phase B1 commit 建新分支 `phase-b2-scientific-hardening`。
2. 保存 Phase B1 ZIP SHA256、commit、配置和结果摘要。
3. 不覆盖原 `results/`、`artifacts/`、`figures/`。
4. 新输出统一写入：
   - `results_phase_b2/`
   - `artifacts_phase_b2/`
   - `figures_phase_b2/`
   - `logs_phase_b2/`
5. 运行旧 609 tests 和新 tests。

验收：基线测试全部通过；旧结果 hash 不变。

## Phase B2-1：修正统计与判决

任务：

1. 删除 `active or list(evidence)` 逻辑。
2. 增加 `INCONCLUSIVE_NO_DOMINANT_BOTTLENECK` 内部状态；最终映射为 `INCONCLUSIVE_REQUIRES_MORE_EVIDENCE`。
3. 以 paired difference 和 ratio-of-aggregate-means 为主要效果量。
4. 对场景进行等权聚合，避免重复场景数量改变总体结论。
5. 引入 success-first 比较。
6. 材料性 gate 不再使用 SG mileage 单项，改为：
   - 频率性能非劣 + 总成本改善；或
   - 总成本非劣 + 频率性能改善。
7. 对资源成本比 `c_ibr/c_sg ∈ {0.25, 0.5, 1.0, 2.0}` 做敏感性分析。
8. 仅用现有 Phase B1 CSV 重新生成 corrected audit，不重新运行 episode。

必须输出：

- `corrected_phase_b1_materiality.csv`
- `corrected_phase_b1_oracle_gap.csv`
- `corrected_phase_b1_control_decomposition.csv`
- `corrected_phase_b1_decision.json`
- `phase_b1_decision_bug_regression_test.txt`

验收：当前三个 trigger 全 false 时，不得输出 COMBINED。

## Phase B2-2：明确频率服务边界

任务：

1. 保留当前单区域 Plant A，仅作代码回归和概念验证。
2. 新建两区域 Plant B，作为主要科学验证对象。
3. 固定本地一次调频/下垂，不由上层控制器优化。
4. 上层控制器每 2 s 输出 supplementary/secondary commands：
   - `u_g,i`：常规资源补充调频命令；
   - `u_b,i`：黑箱 IBR 补充调频命令。
5. 使用 ACE：
   - `ACE_1 = B_1 Δf_1 + ΔP_12`
   - `ACE_2 = B_2 Δf_2 - ΔP_12`
6. 论文术语统一为“supplementary/secondary frequency regulation”，不把 0.5 s 集中动作误称标准 AGC。

验收：无扰动平衡、单区域功率平衡、联络线符号、ACE 恢复均通过单元测试。

## Phase B2-3：建立物理化黑箱 IBR Plant B

任务：

建立独立于当前二阶 surrogate 的平均值 BESS/IBR plant，至少包含：

- 集中命令延迟与执行滤波；
- 实际有功输出状态；
- 运行基点和上下调功率头寸；
- SoC/能量状态；
- 充放电效率；
- 功率和实际输出变化率约束；
- 可选视在功率/电流头寸；
- 服务 enable/disable；
- 通信延迟/丢包状态。

定义具有物理来源的状态变化：

1. nominal available；
2. headroom/current limited；
3. energy limited；
4. communication degraded；
5. service disabled；
6. recovery/reenable；
7. held-out structural OOD。

控制器仍只能获得外部测量，不得读取内部 regime、SoC 或限幅原因，除非在单独的“可用遥测”对照实验中明确开放。

验收：每种 regime 的输出能力、时延、速率和能量行为与配置一致；模式切换不重置物理状态。

## Phase B2-4：实现可信 Oracle 层级

实现：

- `O0`: LQI/PI baseline；
- `O1`: truth-regime identified linear/ARX MPC；
- `O2`: current-regime exact nonlinear NMPC，知道当前 plant state/parameters，不知道未来负荷和未来 regime；
- `O3`: optional clairvoyant NMPC，知道未来 load/regime，仅作为不可部署绝对 ceiling。

O2 必须是多动作优化，而不是单个动作在 horizon 内保持：

- horizon 8–12 s；
- 2 s command interval 或 control blocking；
- CasADi/IPOPT multiple shooting；
- warm start；
- 至少 3 个初始化用于代表场景；
- 记录 KKT residual、约束违反、状态积分误差和 solver status。

验收：

- O2 在当前模型已知的确定性代表场景中不得系统性差于一个粗动作网格；
- 延长 horizon 不应因“固定一动作”结构而反常退化；
- O2 的内部 plant rollout 与独立 simulator 在同一动作序列下误差满足预注册容差。

## Phase B2-5：控制相关 regime 与被动可辨识性

任务：

1. 不以物理标签数量作为模型库 K 的正确性标准。
2. 定义 control-relevant distance：

   `d_ab = α d_prediction + β d_optimal_action + γ d_capability_set`

3. 如果两个物理状态对未来频率、最优动作和可行控制集合影响足够接近，允许合并为同一 regime。
4. 定义 control-critical window：从变化发生到使用错误 regime 导致频率/成本差超过阈值的最早时间。
5. 比较：
   - load-only；
   - regime-only；
   - regime-before-load；
   - coincident；
   - regime-after-load；
   - gradual degradation；
   - recovery；
   - repeated changes。
6. 计算被动数据下的信息 Gramian、预测似然间隔、regime detection delay 和 source confusion。

验收：结论必须区分：

- 可区分但旧诊断器差；
- 在控制关键时间窗内本质上不可被动区分；
- 物理标签不可区分但控制上等效；
- OOD 与已知 regime 重叠。

## Phase B2-6：预注册最终实验

至少包括：

- Plant A regression；
- Plant B 两区域主实验；
- 3 个 SG reserve/GRC level；
- 7 类 regime/event；
- load-only、mode-only、错开和重合事件；
- 3 个噪声水平；
- 30 个 known seeds；
- 50 个 OOD/extreme seeds。

final seeds 禁止调参。所有失败 episode 保留。

## Phase B2-7：决策与停止

根据 `06_EXPERIMENT_AND_DECISION_PROTOCOL.md` 输出一个结论，并停止：

- 如果 O2 无实质价值：停止本方向或重新定义资源场景；
- 如果 O2 有价值但 O1 明显差：模型失配主导；
- 如果 O2/O1 有价值且正确模型可用，但被动数据无法及时判别：下一论文方法应转向安全主动辨识/双重控制；
- 如果被动可辨识但旧控制器差：下一阶段可做 regime-adaptive MPC；
- 如果证据不足：输出 INCONCLUSIVE，不得强制选择。

本阶段不实现下一种 proposed controller。
