# CODEX 总 Goal：方向1 Phase E 科学恢复与能力感知频率控制

## 0. 唯一目标

在当前方向1真实代码仓库中，连续完成 E0–E9，不等待用户逐阶段再次发送消息。你的任务不是继续调 Phase D 的 CUSUM，也不是直接堆叠新算法，而是：

1. 独立复现并修复 Phase D 的闭环和评价缺陷；
2. 建立稳定、物理合理、跨 Plant A/B 验证的多区域频率平台；
3. 先用可信 rolling current-capability Oracle 验证黑箱 IBR 当前能力知识是否具有控制材料性；
4. 再判断自然闭环被动数据是否能在控制关键时间前更新能力集合；
5. 若被动不足，判断安全主动辨识是否可行；
6. 按预注册 Gate 只选择一个最终方法分支；
7. 完成理论、代码、基准、消融、敏感性、鲁棒性、known/OOD、失败实验和论文级材料；
8. 生成小于512MB的单一完整审查包。

## 1. 必须先完整阅读

按顺序阅读：

```text
research/direction1_phase_e_science_recovery_and_capability_control/
  README_FIRST.md
  00_CURRENT_PACKAGE_EXPERT_REVIEW.md
  01_MASTER_EXECUTION_PLAN.md
  02_CORRECTED_SCIENTIFIC_QUESTION_AND_HYPOTHESES.md
  03_MODEL_AND_BASELINE_REBUILD_SPEC.md
  04_ORACLE_MATERIALITY_AND_CAUSAL_INFORMATION_PROTOCOL.md
  05_PASSIVE_AND_ACTIVE_CAPABILITY_IDENTIFICATION_SPEC.md
  06_FINAL_METHOD_BRANCH_SPEC.md
  07_THEORY_AND_PROOFS_SPEC.md
  08_EXPERIMENT_AND_STATISTICS_PROTOCOL.md
  09_SOFTWARE_ARCHITECTURE_AND_STAGE_CONTRACTS.md
  10_GATES_FAILURE_AND_AUTO_REPAIR.md
  11_FINAL_REVIEW_PACKAGE_SPEC.md
```

然后创建：

`progress_phase_e/READING_ACKNOWLEDGEMENT.md`

列出已读文件、理解的致命问题、阶段顺序、停止条件和最终输出。

## 2. Git和结果隔离

- 旧 Phase D 只读归档，不覆盖。
- 创建 tag：`direction1-phase-d-negative-reviewed`。
- 创建 branch：`direction1-phase-e-science-recovery`。
- 新结果只能写入：

```text
research_outputs_phase_e/
results_phase_e/
figures_phase_e/
logs_phase_e/
progress_phase_e/
```

## 3. 阶段执行

严格执行：

`E0 → E1 → E2 → E3 → E4 → E5（按需）→ E6 → E7 → E8 → E9`

每阶段必须输出 `progress_phase_e/E#.json`，包含：目标、输入哈希、命令、测试、Gate、失败、修复、输出哈希和下一阶段。

### E0

冻结旧证据并运行独立审计，复现：

- Phase D 名义闭环自激；
- delay能力候选已更新但`update_time`未记录；
- 原`control_loss_time`非实际控制损失；
- 全部候选失败时错误选择最后候选。

将旧结论标记为：

`PHASE_D_GATE_INVALIDATED_BY_CLOSED_LOOP_AND_EVALUATION_DEFECTS`

### E1

完成≥50篇正式文献的可审计综述和创新矩阵，锁定科学问题、H1–H5、信息边界和声明边界。不得伪造引用，不得用“首次MPC/AI”作为创新。

### E2

重建稳定名义闭环、Plant A/B、统一延迟、BESS共享能力和SG anti-windup。Phase D的 `Kp=1.4, Ki=0.18, 35/65` 不得直接沿用。

在进入任何辨识实验前，必须通过：

- 小扰动衰减；
- 1h背景负荷无自激；
- 2/4s闭环稳定；
- dt收敛；
- 功率/能量守恒；
- Plant B BESS有功真实进入原生网络；
- ANDES同扰动/同控制交叉验证。

### E3

实现真正的SG-only、fixed allocation、nominal MPC、RLS adaptive MPC、worst-case capability-set tube MPC和evaluation-only current-capability rolling NMPC Oracle。

所有称为MPC的实现必须有prediction horizon、序列决策变量、动力学、约束、目标、solver和receding execution。

先验证H1材料性。合格Oracle在Plant A/B均无材料性时，停止为 `PROBLEM_NOT_MATERIAL`，不要继续辨识研究。

### E4

修正被动可辨识性：

- `update_time`由实际控制相关集合变化和覆盖恢复定义，不得只由alarm定义；
- `Tcrit`由旧模型控制与current-capability Oracle的匹配反事实控制损失定义；
- 使用稳定自然闭环、完整公共测量和因果负荷估计；
- 实现至少三种合理被动基线；
- 测试headroom/ramp/delay/energy/availability；
- 区分结构不可辨识、激励不足、有限样本和算法失败。

Passive Gate通过则E6选择分支P；失败但H1通过则进入E5。

### E5

验证安全主动能力辨识是否可行。设计有限功率、有限能量、具有SG backup的探测/调频联合动作。不得用未来真值或不安全饱和制造信息。

Active Gate通过则E6选择分支A；失败则E6选择分支R。

### E6

只实现一个最终分支：

```text
P: Passive capability-set adaptive tube MPC
A: SACID-TMPC, safe active capability identification dual tube MPC
R: Capability-set robust tube MPC without identification
```

选择写入 `06_METHOD/SELECTED_BRANCH.json` 后不得改变。所有方法必须公平共享信息、约束、控制周期和状态估计。

### E7

完成与实际代码一致的能力集合、tube/RPI、约束收紧、SG终端backup、递归可行/有限时域安全证明。若无法认证，收缩为empirical，不得伪称stability-guaranteed。

### E8

锁定final manifest、seeds、指标和哈希后运行全部基准、Oracle、proposed、消融、known/OOD、敏感性、鲁棒性和失败案例。final开始后不得修改算法、权重、阈值或场景。

### E9

生成论文级图表、表格、解释、复现命令、源码、原始结果、失败记录、清单和单一审查ZIP。

## 4. Gate分支逻辑

必须严格使用：

```text
if not G2_PHYSICS:
    STOP_FATAL
elif not G3_MATERIALITY:
    STOP_PROBLEM_NOT_MATERIAL
elif G4_PASSIVE:
    SELECT_BRANCH_P
elif G5_ACTIVE:
    SELECT_BRANCH_A
else:
    SELECT_BRANCH_R
```

分支选定后不得更换。

## 5. 失败处理

任何失败先按：

`代码 → 数值/求解器 → 物理参数 → 模型 → 方法 → 科学假设`

诊断并记录。

禁止：

- 无依据大范围调参；
- 删除不利结果；
- 降低频率/ACE/约束标准；
- 用final seeds调参；
- 把not_evaluated记成失败或把solver failure隐藏；
- 把代数规则命名为MPC；
- 在全部trigger为false时强制输出dominant结论；
- 因一个估计器失败就宣称普遍不可辨识。

## 6. 普通控制器信息安全

部署控制器严禁读取：

- true capability/regime；
- hidden parameters/state；
- true load；
- future load/switch/dropout；
- Oracle action/trajectory。

Oracle只能在evaluation namespace中使用。

## 7. 最终输出

生成：

`DIRECTION1_PHASE_E_SCIENCE_RECOVERY_AND_CAPABILITY_CONTROL_SINGLE_REVIEW_PACKAGE.zip`

严格符合 `11_FINAL_REVIEW_PACKAGE_SPEC.md`，小于512MB。

完成后在最终回复报告：

- ZIP绝对路径；
- 大小和SHA256；
- Git branch/commit/status；
- E0–E9全部Gate；
- H1–H5状态；
- 选定分支；
- 最佳可部署基线；
- Plant A/B known/OOD结果；
- solver与实时性；
- 最严重失败和限制；
- 最终研究状态。

除遇到治理文件规定的fatal stop外，不要在内部阶段结束后等待用户再次发Goal。
