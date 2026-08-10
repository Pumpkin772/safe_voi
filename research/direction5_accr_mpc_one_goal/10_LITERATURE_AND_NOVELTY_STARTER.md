# 文献与创新性启动清单

Codex必须重新检索并核验正式来源。以下仅作为起点：

1. Safe Data-Driven Secondary Control of Distributed Energy Resources, IEEE TPWRS, 2021, DOI 10.1109/TPWRS.2021.3084440  
   重点：安全持续激励、nullspace excitation。必须作为最接近基线，不得忽略。

2. Active Exploration in Adaptive Model Predictive Control, IEEE CDC, 2020, DOI 10.1109/CDC42340.2020.9304303  
   重点：set-membership、主动探索、最坏代价和鲁棒约束。

3. Probing Signal Design for Power System Identification  
   重点：低幅、多正弦、功率系统主动探测。

4. A Review of Active Probing-Based System Identification Techniques With Applications in Power Systems, 2022  
   重点：功率系统主动探测类别和工程限制。

5. Adaptive Control Allocation for Constrained Systems, Automatica, 2020  
   重点：执行器有效性变化和约束分配。

6. Learning to Model the Dynamics of Black-Box IBRs With Multiple Unknown Control Modes, IEEE TSG, 2025/2026, DOI 10.1109/TSG.2025.3647551  
   重点：黑箱多模式建模已有。

7. Fault-Tolerant Event-Triggered Load Frequency Control for Multi-Area Power Systems, IEEE TII/related, 2022  
   重点：执行器故障LFC已有。

8. 当前历史方向5负结果包中的正式文献。

## 最接近工作的区别必须写清

### 与Safe Data-Driven Secondary Control
- 对方学习系统灵敏度；
- 持续/随机nullspace激励；
- 不针对设备可交付power/ramp/delay突变；
- 不形成有限有效期能力证书；
- 不区分合同floor和在线剩余能力；
- 不研究能力突降追索。

### 与Active Exploration MPC
- 一般LTI参数学习；
- 本项目利用SG–IBR分配冗余；
- 关注多区域ACE/tie与设备可交付能力类；
- 事件触发而非持续探索。

### 与Adaptive Control Allocation
- 一般过驱动执行器；
- 本项目包含频率、ACE、联络线、能量和多时间尺度资源。

若检索发现正式工作已经同时覆盖这些差异，则必须收缩或终止创新声明。
