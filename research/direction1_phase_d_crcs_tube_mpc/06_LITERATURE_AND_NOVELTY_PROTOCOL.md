# 文献调研与创新性对照协议

## 1. 目标

围绕“黑箱IBR未通知能力变化下的多区域频率控制”建立可审计综述，而不是泛泛罗列AI/MPC论文。

## 2. 数据库与来源优先级

1. IEEE Xplore；
2. Elsevier/ScienceDirect；
3. IET；
4. Automatica、IEEE TAC、TCST、L-CSS等控制期刊；
5. NERC、ENTSO-E、AEMO、National Grid等正式文件；
6. arXiv只用于2025–2026尚未正式发表的最前沿，并必须标注预印本。

## 3. 至少覆盖的主题

- 黑箱IBR多模式/切换动态建模；
- IBR动态状态估计和事件检测；
- 黑箱/数据驱动频率预测控制；
- 多区域AGC和ACE责任分配；
- BESS功率、能量、头寸和SFR能力建模；
- set-membership adaptive MPC；
- robust/tube MPC与递归可行性；
- 未知输入/负荷估计；
- 变化检测和结构可辨识性；
- IBR模型验证、现场性能与模型质量。

## 4. 已核实的关键锚点

必须在综述中准确对照：

- Huang et al., *Learning to Model the Dynamics of Black-Box Inverter-Based Resources With Multiple Unknown Control Modes From Noisy Measurement Data*, IEEE TSG, 2025/2026卷期；
- Huang et al., *Switching Dynamic State Estimation and Event Detection for Inverter-Based Resources With Multiple Control Modes*, IEEE TPWRS, 2024/2025；
- Rezaei et al., *Data-Driven Koopman Predictive Control for Frequency Regulation of Power Systems using Black-Box IBRs*, 2026 preprint；
- Lu et al., *Robust Adaptive Tube Model Predictive Control*, IEEE TCST, 2019；
- 2026 robust adaptive NMPC/set-membership最新正式文献；
- NERC 2024–2026 IBR模型质量、动态模型验证和EMT/positive-sequence交叉验证文件。

## 5. 创新性矩阵字段

每篇文献记录：

- 年份、期刊、DOI；
- 电力系统/一般控制；
- 黑箱动态；
- 多模式/能力变化；
- 是否在线变化；
- 是否只用外部I/O；
- 是否多区域ACE/tie-line；
- 是否定义time-to-harm；
- 是否维护能力集合；
- 是否有硬约束/递归可行；
- 是否有原生网络验证；
- 与CRCS-TMPC的重叠与差异。

## 6. 数量和质量门

- 总计至少50篇；
- 2021年后至少30篇；
- 正式同行评审至少80%；
- IEEE Transactions、Applied Energy、IJEPES等高水平来源占主体；
- 每条核心创新声明至少有2篇最接近工作对照；
- 不允许把“未检索到”写成“首次”。

## 7. 最终创新定位

论文创新应写成：

1. 将黑箱IBR的不确定对象从离散OEM标签改为控制相关能力集合；
2. 建立因果能力集合更新时间与控制损失时间的联合问题；
3. 在多区域ACE/联络线责任下设计能力集合自适应管束MPC；
4. 给出条件性递归可行和约束满足；
5. 在透明Plant和原生RMS/DAE网络上验证。

不得写成“首次使用MPC/AI/模式识别”。
