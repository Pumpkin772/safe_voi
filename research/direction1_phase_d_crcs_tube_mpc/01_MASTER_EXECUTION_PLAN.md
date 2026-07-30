# 方向1 Phase D 总体多阶段执行计划

本计划是一个总Goal内部的连续执行合同。Codex不得在正常阶段之间等待新指令。

## D0 — 当前分支冻结与错误撤回

**研究目标**：保存当前Phase C全部证据，撤回无效Gate，建立方向1新分支。

**输入文件**：当前完整审查ZIP、Git仓库、本启动包。

**具体任务**：

- 核对ZIP SHA256和Git commit；
- 归档当前C0–C9结果；
- 写出逐项错误映射；
- 将C5 passive-identifiable和C6/C8方法结论标记为invalidated-by-audit；
- 建立 `direction1-phase-d-crcs-tube-mpc`。

**新建/修改文件**：

`research_outputs_phase_d/D0/BASELINE_FREEZE.md`、`INVALIDATED_CLAIMS.json`、`CURRENT_CODE_AUDIT.csv`。

**必须运行**：当前包最小复现、哈希和Git检查。

**输出**：冻结标签、干净分支、旧结果只读目录。

**成功/失败/自动处理**：见 `09_GATES_FAILURE_AUTO_REPAIR.md`。

**衔接**：D0通过后进入D1。

## D1 — 文献调研、问题和假设锁定

**研究目标**：验证创新边界，冻结科学问题和声明。

**输入**：D0审查、`06_LITERATURE_AND_NOVELTY_PROTOCOL.md`。

**任务**：

- 系统检索≥50篇；
- 建立最接近工作逐维对比；
- 核实黑箱多模式建模、切换估计、数据驱动频率控制、鲁棒自适应MPC、多区域AGC；
- 更新H1–H4；
- 明确不支持声明。

**文件**：`LITERATURE_REVIEW.md`、`LITERATURE_MATRIX.csv`、`NOVELTY_TABLE.md`、`SEARCH_LOG.md`、BibTeX。

**实验**：无大仿真；运行DOI/元数据和重复文献检查。

**成功**：创新交叉未被完整覆盖，声明可证伪。

**衔接**：锁定文本和哈希后进入D2。

## D2 — Plant A/Plant B和物理约束重建

**研究目标**：建立物理闭合、单位一致、可交叉验证的两层模型。

**输入**：旧Plant A可保留代码、`03_CORRECTED_PLANT_MODELS.md`、ANDES标准系统。

**任务**：

- 重写SG、BESS、延迟和Plant A；
- 在Plant内部统一PFR/SFR共享能力；
- 用因果命令队列建模延迟；
- 建立原生ANDES Plant B控制接口；
- 若Kundur接口致命失败，只允许切换IEEE39一次；
- 完成参数来源。

**文件**：`src/direction1freq/models/*`、`configs/plant_*.yaml`、完整模型文档、参数表、公式映射。

**实验**：RoCoF、功率平衡、能量守恒、延迟脉冲、dt收敛、300s稳定、ANDES交叉验证。

**输出**：模型证书、轨迹、失败日志。

**成功**：D2所有数值门通过。

**衔接**：模型和配置哈希冻结后进入D3。

## D3 — 因果状态/负荷估计和能力集合更新

**研究目标**：只用公共测量构造真实可部署的能力集合。

**输入**：D2模型、development场景。

**任务**：

- 实现增强状态/未知负荷估计器；
- 离线确定外部ARX/状态空间阶数和初始全局集合；
- 实现严格因果CUSUM/GLR；
- 实现参数、功率、爬坡、延迟和能量区间更新；
- 设计负控制和load-vs-capability混淆实验。

**文件**：`estimation/*`、`identification/*`、`CAPABILITY_SET_MODEL.md`。

**实验**：无变化、单机制、同步事件、低激励、噪声和通信抖动。

**输出**：覆盖率、宽度、假警、更新时刻、结构不可辨识证书。

**成功**：H2通过。

**衔接**：冻结估计器后进入D4。

## D4 — 公平基线和滚动Oracle材料性

**研究目标**：先证明能力知识值得控制，再开发最终方法。

**输入**：D2 plant、D3公共估计器。

**任务**：

- 实现所有真实基线；
- 实现无未来信息、每个控制周期滚动的current-capability NMPC Oracle；
- 所有部署基线共享测量和估计器；
- Oracle单独标注信息优势；
- 做horizon、网格、初值和KKT审计。

**文件**：`controllers/*`、`ORACLE_QUALIFICATION.md`、求解日志。

**实验**：两Plant、资源A/B/C、单机制和复合机制、2/4s。

**成功**：Oracle≥95%可靠且H1在两Plant通过。

**失败**：可靠Oracle无价值则终止为`PROBLEM_NOT_MATERIAL`。

**衔接**：进入D5。

## D5 — CRCS-TMPC与理论完成

**研究目标**：实现一套真实、可证明的能力集合自适应管束MPC。

**输入**：D2模型、D3集合、D4基线。

**任务**：

- 延迟状态增强；
- 计算全局与在线管束；
- 计算SG终端鲁棒不变集；
- 实现约束收紧、备份和平滑责任转移；
- 完成Lemma/Theorem；
- 建立公式—代码—测试映射。

**文件**：`controllers/crcs_tube_mpc.py`、`optimization/*`、`THEOREMS_AND_PROOFS.md`、数值证书。

**实验**：随机顶点约束、递归可行性、覆盖失效和求解器故障。

**成功**：理论Gate通过、实现与名称一致。

**衔接**：进入D6。

## D6 — Development/Validation方法定型

**研究目标**：在不看final的情况下完成最多两轮有依据修复。

**输入**：D5方法、development/validation manifest。

**任务**：

- 一轮初始参数；
- 完整基线/消融；
- 根据误差分解只修具体问题；
- 最多第二轮；
- 冻结最终参数。

**实验**：Plant A全矩阵、Plant B核心矩阵、已知/OOD初步测试。

**成功**：H3验证门通过。

**失败**：两轮后输出负方法状态，不换算法；仍进入D7–D9完成负结果包。

## D7 — Final协议预注册

**研究目标**：生成独立、无混杂的final实验矩阵。

**输入**：D6冻结方法、`07_EXPERIMENT_AND_STATISTICS_PROTOCOL.md`。

**任务**：显式交叉因素、独立seed、锁定阈值、代码和配置SHA256；运行dry run。

**文件**：`FINAL_PROTOCOL_LOCK.json`、`SCENARIO_MANIFEST.csv`、`CONTROLLER_MANIFEST.csv`、`LOCKED_HASHES.json`。

**成功**：factor independence和seed firewall测试通过。

## D8 — Final完整实验与统计

**研究目标**：一次性运行全部基准、消融、敏感性、鲁棒性和失败案例。

**输入**：D7锁定内容。

**任务**：

- 运行全部episode；
- 失败分类；
- success-first、paired、scene-balanced统计；
- OOD、成本和Pareto；
- 生成代表时序和最差案例；
- final后不修改方法。

**输出**：Parquet原始结果、统计表、轨迹、求解日志。

**成功**：实验完整；方法是否成功按H3裁决，不强制正结果。

## D9 — 论文级结果和单一审查包

**研究目标**：形成可复现、可投稿判断的完整材料。

**任务**：

- 生成论文级模型图、机制图、时序图、集合图、结果表；
- 完整结果解释和限制；
- 形成论文提纲或草稿；
- 一键复现；
- 清单和哈希；
- 压缩<512MB。

**最终文件**：

`DIRECTION1_PHASE_D_CRCS_TUBE_MPC_SINGLE_REVIEW_PACKAGE.zip`。
