# 修正后的科学问题、假设与创新边界

## 1. 主科学问题

> 在多区域二次频率调节中，当黑箱 IBR 的对外可用能力集合——包括上下调功率头寸、爬坡率、响应时延、可持续能量和服务可用性——发生未通知变化时，控制中心能否仅根据外部可测的频率、ACE、联络线功率、命令和POI功率，在错误能力模型造成实质控制损失前识别控制相关变化，并安全重分配调频责任？

## 2. 研究对象不是“真实模式标签”

定义隐藏能力向量：

\[
c_k=\left[P_k^+,P_k^-,R_k^+,R_k^-,\tau_k,E_k^{\mathrm{avail}},a_k,\eta_k\right].
\]

两个物理状态即使标签不同，只要它们在允许输入/扰动集合内：

- 未来POI功率与频率预测近似相同；
- 最优调频动作近似相同；
- 可行能力集合近似相同；

就属于同一个 control-relevant regime。反之，同一OEM标签下若SoC、头寸或延迟变化足以改变控制决策，应属于不同regime。

## 3. 可证伪研究假设

### H1：材料性

在至少一类物理合理的SG备用紧张或IBR占比较高场景中，知道当前真实能力的无未来信息Oracle，相对最佳名义/在线自适应基线，可显著改善频率、ACE、联络线责任或失败率。

**否证条件**：在经过单位修正、强Oracle和Plant A/B验证后，Oracle仍没有达到预注册材料性门。

### H2：错误能力模型会在有限时间内造成控制相关损失

存在控制关键时间 `Tcrit`，在该时刻后继续采用名义能力模型会造成可测的频率、ACE、tie-line或约束损失。

**否证条件**：所有合理能力变化都不改变最优动作或性能，说明regime对控制不相关。

### H3：至少部分能力变化可从外部I/O在Tcrit前识别

对headroom、ramp、delay等具有足够自然激励的变化，被动数据可在可接受误报率下满足 `Tdet<Tcrit`。

**否证条件**：即使采用最优负荷估计和合理测量，信息矩阵退化且所有候选模型外部行为不可区分。

### H4：不可识别并不等于无法安全控制

若精确regime不可辨识，维护能力集合并进行鲁棒约束控制，仍可优于把设备永久视为最坏状态或名义状态。

### H5：最终方法的价值来自问题结构，而不是方法堆叠

- passive分支：模型库提供先验，在线更新解决变化，robust MPC处理集合不确定性；
- active分支：只有被动信息不足且安全激励可行时，才引入dual objective；
- unidentifiable分支：直接集合鲁棒控制，不做无意义分类。

## 4. 预期创新层级

1. **科学问题创新**：从“固定黑箱模型的频率控制”推进到“未通知能力变化下，诊断速度与控制关键窗口之间的闭环问题”。
2. **建模创新**：以可行能力集合和控制等效regime替代人工物理模式标签。
3. **方法创新**：由材料性/可辨识性Gate自动选择被动自适应、主动辨识或集合鲁棒控制，方法与问题一一对应。
4. **理论创新**：在明确假设下给出集合覆盖、递归可行性和约束安全条件。
5. **实验创新**：同时在两区域透明模型和原生多机RMS/DAE模型中，验证Tdet、Tcrit、责任重分配和失败边界。

## 5. 不能声称的创新

- “首次研究黑箱IBR多模式建模”；已有工作覆盖。
- “首次用Koopman/DeePC/MPC进行黑箱IBR频率控制”；已有邻近工作。
- “高模式分类准确率”；分类不是核心。
- “对任意OEM黑箱模型都有全局稳定保证”；理论仅覆盖明示模型族和假设。
- “完整EMT工程验证”；除非确实加入并验证OEM/EMT模型。

## 6. 文献调研的种子来源

Codex必须自行核验并扩展，禁止直接复制未核验条目：

- Huang et al., “Learning to Model the Dynamics of Black-Box Inverter-Based Resources With Multiple Unknown Control Modes From Noisy Measurement Data,” IEEE, 2025, document 11313680.
- Rezaei et al., “Data-Driven Koopman Predictive Control for Frequency Regulation of Power Systems using Black-Box IBRs,” 2026 preprint;只能作为前沿补充，不能替代正式期刊调研。
- NERC, “Electromagnetic Transient Analysis in Operations Planning for BPS-Connected IBRs,” 2025.
- NERC, “Findings from Inverter-Based Resource Model Quality Deficiencies,” 2025.
- 相关DeePC、set-membership adaptive MPC、robust/tube MPC、dual control、multi-model fault-tolerant control和multi-area AGC原始论文。
