# 文献调研锚点（Codex必须进一步核验并扩展）

以下只作为检索锚点，不替代 E1 的正式数据库检索：

1. Huang et al., “Learning to Model the Dynamics of Black-Box Inverter-Based Resources with Multiple Unknown Control Modes,” IEEE, 2025.
2. Rezaei, Wang, Geng, “Data-Driven Koopman Predictive Control for Frequency Regulation of Power Systems using Black-Box IBRs,” 2026 preprint；只能作为前沿邻近，不作为正式期刊首要证据。
3. Nestor et al., “Data-driven Communication and Control Design for Distributed Frequency Regulation with Black-box Inverters,” 2025 preprint；需要检查正式发表状态。
4. Parsi, Iannelli, Smith, “Active Exploration in Adaptive Model Predictive Control,” IEEE CDC, 2020.
5. Parsi et al., “Dual Adaptive MPC Using an Exact Set-Membership Reformulation,” 2022/后续正式版本状态需核验。
6. Self-Tuning Tube-Based Model Predictive Control, 2023.
7. Robust/adaptive tube MPC、set-membership identification、safe exploration 的 Automatica/IEEE TAC/IJRNLC 正式工作。
8. NERC/FERC 关于 IBR model validation、model quality、frequency support 和post-disturbance ramp requirements的正式文件。

E1必须检索并对比：

- 是否已有工作直接研究“未通知能力变化 + 多区域ACE + 控制关键窗口 + 安全主动能力信息”；
- black-box model identification 与 capability identification 的区别；
- passive adaptation、dual control和worst-case robust control的选择边界；
- 现有频率控制工作是否考虑功率/爬坡/延迟/能量共同变化；
- 是否有现场数据或OEM模型验证可支持参数范围。
