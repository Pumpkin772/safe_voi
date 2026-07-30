# 当前 Phase C 完整压缩包专家审查与裁决

## 1. 审查范围

审查对象：

`DIRECTION5_PHASE_C_FULL_REBUILD_AND_METHOD_COMPLETION_SINGLE_REVIEW_PACKAGE.zip`

- ZIP SHA256：`28f64c4668a86c4d336619f27382c16766a0b425a6cd6895fd816f07aff809e9`
- 文件数：398；清单内文件哈希全部一致；
- Git commit：`86f982baeda32ee62f8a6117bfe66bc3a9e9bdbb`；
- 包内测试报告：629 passed、0 failed、2 warnings、68% coverage；
- 独立审查环境未安装 `cvxpy`，因此没有声称独立重跑全部 629 项测试；结论来自源码、结果、日志、图形和结构化数据交叉审计。

## 2. 总体裁决

```text
SCIENTIFIC_QUESTION: VALID_AND_POTENTIALLY_VALUABLE
CURRENT_PLANT_A: USEFUL_BUT_NEEDS_PROTOCOL_HARDENING
CURRENT_PLANT_B: PHYSICALLY_INVALID_FOR_PUBLICATION
CURRENT_IDENTIFIABILITY_GATE: INVALID
CURRENT_PROPOSED_METHOD: NOT_AN_MPC
CURRENT_BASELINE_COMPARISON: MISLABELED_AND_UNFAIR
CURRENT_FINAL_RESULT: NOT_SCIENTIFICALLY_DECISIVE
RECOMMENDATION: MAJOR_REBUILD_AND_CONTINUE
```

方向不应终止，但当前 C5–C8 结果应撤回为“实现审计证据”，不能用于论文主结论。

## 3. 科学问题

高层问题是真实、明确、可证伪且有价值的：当参与多区域二次调频的黑箱 IBR/BESS 的可用功率、爬坡、延迟、可持续能量或服务可用性发生未通知变化时，控制中心能否仅凭外部 I/O，在旧能力模型造成频率、ACE、联络线或物理约束损失前，更新控制相关能力集合并安全重分配调频责任？

现有研究已经分别覆盖：多控制模式黑箱 IBR 建模、切换状态估计、黑箱 IBR 数据驱动频率预测控制，以及一般鲁棒自适应 MPC。尚未被当前已核实文献完整覆盖的交叉点是：

```text
unannounced capability-set change
+ external-I/O-only causal update
+ multi-area ACE/tie-line responsibility
+ time-to-harm criterion
+ robust feasible responsibility reallocation
```

创新不能建立在“模式分类准确率”或“AI+MPC组合”上，而应建立在控制相关能力集合、因果更新时间和约束安全重分配上。

## 4. 致命问题

### F1. Plant B 的有功功率平衡不闭合

文件：`04_SOURCE/src/d5freq/models/plant_b_native_rms.py`

- 第 119–124 行把 BESS 功率放入一个 DC 角度代数求解；
- 第 131–138 行的发电机电气功率只由区域负荷、联络线及人工同步转矩构成；
- BESS 功率没有进入全部发电机摆动方程的总有功平衡。

因此，系统 COI 频率不直接接受 BESS 有功支撑，BESS 主要通过人为联络线路径间接作用。这违反基本功率守恒，足以使 Plant B 的材料性、Oracle和最终方法比较失效。

### F2. Plant B 不是经过交叉验证的原生多机 RMS/DAE

同一文件第 56–77 行只单独运行未修改的 ANDES Kundur PFlow/TDS，以证明 ANDES 可运行；没有把自定义 Plant B 与 ANDES 在相同扰动、相同参数、相同控制器下进行轨迹对比。第 94–100 行只是六节点线性 Laplacian，不能据此称为原生标准系统验证。

图 `C3/plant_a_b_trend.png` 中 Plant B 在约 20 s 后振荡幅值逐渐放大，说明当前“方向一致” Gate 过弱。

### F3. `SetAdaptiveMPC` 不是 MPC

文件：`04_SOURCE/src/d5freq/controllers/set_adaptive_mpc.py`

- 无预测模型；
- 无预测时域；
- 无优化问题；
- 无状态/输入序列；
- 无终端集或管束；
- 只根据指令—输出残差缩小一个标量功率区间，再以代数比例分配。

因此论文中不能称其为 set-adaptive MPC，也不能基于该实现宣称递归可行性。

### F4. 最终主要基线多数不是真实 MPC

文件：`04_SOURCE/scripts/phase_c/c8_final_experiment.py`

- 第 58 行：`fixed_allocation` 与 `nominal_mpc` 完全相同；
- 第 59–62 行：`rls_adaptive_mpc` 只是标量增益平滑，没有递归最小二乘参数向量和 MPC；
- 第 63 行：`robust_capability_set_mpc` 令 BESS 指令恒为零，本质是 SG-only 前馈/反馈，不是鲁棒集合 MPC；
- 第 64–65 行：proposed 也是代数分配。

因此“proposed 输给 robust capability-set MPC”并不是两种 MPC 的可信比较。

### F5. C5 可辨识性结果非因果

文件：`04_SOURCE/src/d5freq/identification/passive_capability_detector.py`

- 第 27 行使用 `np.convolve(..., mode='same')`；这是中心窗口，会使用未来残差；
- 第 33–45 行使用报警后未来 8 s 信号进行来源分类；部署时不可用；
- `tdet_vs_tcrit.png` 中多个报警时间早于 t=20 s 的真实变化时刻，直接暴露非因果泄露。

此外，`c5_identifiability.py` 第 11–18 行使用人为双正弦命令直接激励独立执行器，不含电网闭环、ACE、未知负荷或真实测量噪声，不能代表“被动闭环可辨识性”。

### F6. C4 材料性 Gate 不是公平上界

- 主要用极端不可用/低能力场景与仍假设 nominal BESS 的控制器比较；
- O2 预测模型是简化七状态模型，不包含完整能量、延迟、PFR共享能力和 Plant B 网络；
- Plant B 的 `tie_coefficient` 被设为 0；
- C8 中 O2 经常比简单方法差，说明它不是可信上界。

C4 只能说明“知道执行器不可用通常比继续向其分配命令好”，不能证明完整科学问题的材料性。

## 5. 重大问题

### M1. 未知负荷估计近似使用无噪声真值微分

C8 第 51–54 行用 `dt=0.01 s` 的无噪声频率差分和已知模型重构负荷。它不是现实可部署的未知输入估计器，且与 Plant B 的错误功率平衡不一致。

### M2. 实验因素完全混杂

最终场景由 seed 取模同时决定：场景、SG能力、事故幅值、区域和符号。已知场景与 SG 能力几乎固定绑定，没有独立交叉，无法区分场景效应与备用能力效应。

### M3. “随机种子”没有代表独立随机重复

C8 创建 RNG 但基本未使用；seed 只是确定性场景编码。对这些 seed 做 Bootstrap 不能解释为随机噪声或运行不确定性的置信区间。

### M4. 事件设置过于干净

能力变化固定在 30 s，负荷事故固定在 40 s，给出 10 s 完全分离；没有同期事件、随机时刻、正常负荷随机波动、测量噪声、通信抖动或丢包。

### M5. OOD 名称与物理实现不一致

- `current_limit_q` 实际只把 headroom 设为 0.45，没有 Q/电流事件；
- `asymmetric` 是区域不对称，不是正负功率能力不对称；
- `energy_low` 是低初始 SoC，不是未通知变化；
- `unknown_three_stage` 只是三段 headroom。

### M6. SFR 成功判据过弱

C8 第 78 行只要求最大频差 ≤0.8 Hz、最大 ACE ≤0.35 pu；没有要求尾段频率、ACE和联络线恢复，没有终端 SoC/备用、无约束违例、恢复时间和稳态误差判据。对 180 s 二次调频而言，这不构成科学成功。

### M7. 仅使用 2 s 控制周期

协议声称 2/4 s，但最终矩阵全部为 2 s；没有 4 s 主分析，也没有正常运行 1 h 数据。

### M8. Plant A 的 `delay_s` 不在 plant 内部执行

延迟由最终脚本外置队列实现，C4/C5 和其他入口可能忽略同一能力参数，导致模型接口和实验不一致。

### M9. 论文理论材料严重不足

- `FULL_MATHEMATICAL_MODEL.md` 只有一段摘要；
- `THEOREMS_AND_PROOFS.md` 只有条件性文字；
- 公式—代码映射只有 5 行；
- 参数来源只有 5 项；
- 没有实际 RPI 集、终端集、约束收紧或递归可行性计算。

### M10. 消融实验多数未实际运行

`ablation_status.csv` 中多项是 proxy 或 not evaluated，没有真正完成 no-update、no-tightening、no-backup、hard-label、no-prior 等方法消融。

### M11. 图形不具论文质量

`model_block_diagram.png` 为空白；主要图缺少真实时序、能力集合、责任转移、ACE、联络线和 SoC 的同轴机制展示；Pareto标注拥挤。

## 6. 可保留内容

- 科学问题的信息边界和可证伪意识；
- Plant A 的 p.u. 频率单位、ACE和 BESS 能量更新基础；
- 两区域 SFR 框架；
- SG GRC 和 BESS 总 PFR+SFR共享能力的代码雏形；
- Oracle/deployable 信息隔离测试思路；
- 失败记录、清单、Git和可复现结构；
- 将 OEM 标签替换为 control-relevant capability set 的方向；
- success-first 和场景平衡统计原则。

## 7. 最终路线决定

停止当前 `proposed_set_adaptive_mpc`。不再自动选择三种算法分支，也不再做“模式分类+MPC”。

后续固定为一条方法路线：

> **CRCS-TMPC：因果能力集合估计 + 延迟/能力不确定管束 MPC + SG终端备份。**

若自然闭环数据无法维持能力集合覆盖或及时收缩，则作为科学假设失败停止，不临时切换到另一套复杂算法。
