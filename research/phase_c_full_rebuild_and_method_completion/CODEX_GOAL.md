# Codex 总 Goal：方向五 Phase C 完整重建与方法完成

你必须在当前真实项目仓库中，连续执行本Goal的全部内部阶段，不得要求用户在阶段之间重新发送Goal。只有出现本文件定义的致命停止条件时才提前停止；即使提前停止，也必须生成完整负结果审查包。

## 一、开始前必须阅读

完整阅读：

```text
research/phase_c_full_rebuild_and_method_completion/
```

下全部文件。它们是本阶段科学、数学、代码、实验和交付的权威来源。

## 二、当前结论的处理

1. 冻结并保留Phase B2全部结果。
2. 撤回当前 `PROBLEM_NOT_MATERIAL` 作为有效科学结论。
3. 不得沿用Phase B2中混用Hz与p.u.频率的参数。
4. 不得把当前O2称为可信最优Oracle。
5. 不得把RLS/旧SD-BMPC的未运行占位记录当作方法失败。

## 三、必须连续完成的阶段

严格按：

```text
C0 → C1 → C2 → C3 → C4 → C5 → C6(唯一自动分支) → C7 → C8 → C9
```

执行。每阶段必须：

- 写状态JSON和decision ledger；
- 运行规定测试；
- 检查成功/失败判据；
- 对可修复失败自动诊断、修复和重跑；
- 不改变预注册科学标准；
- 不等待用户确认。

详细任务以 `01_MASTER_EXECUTION_PLAN.md` 为准。

## 四、核心科学问题

锁定为：

> 当多区域二次频率调节中的黑箱IBR，其对外可用功率、爬坡、延迟、能量或服务可用性发生未通知变化时，控制中心能否仅根据外部可测I/O，在错误模型造成实质频率、ACE或联络线责任损失之前识别控制相关能力变化，并安全重分配调频责任？

不以恢复OEM真实标签为目标，而以 `control-relevant capability regime/set` 为目标。

## 五、物理模型硬要求

1. 内部频率统一使用 `omega=Delta f/f0`；报告转Hz。
2. 使用 `2H*dot(omega)` 形式，不再混用 `M=8 pu.s/Hz` 与Hz状态。
3. 本地PFR固定，上层SFR周期2/4s。
4. SG机械GRC施加在机械功率动力学。
5. BESS的PFR+SFR共享功率、视在功率、电流、爬坡、能量和SoC约束。
6. 禁止SoC硬投影产生自由能量。
7. known regime一次只改变一个物理机制；复合留作OOD。
8. 普通控制器不得读取true regime、真实SoC（除非明确设为可测）、内部参数、真实负荷或未来事件。
9. 建立两区域Plant A和至少一个原生多机RMS/DAE Plant B。

## 六、科学Gate

### Gate 1：材料性

先建立可靠滚动NMPC Oracle。若在修正模型的Plant A和Plant B中，Oracle均无预注册控制价值，则停止方法开发，输出 `PROBLEM_NOT_MATERIAL` 负结果包。

### Gate 2：可辨识性

材料性通过后，计算 `Tdet` 与 `Tcrit`：

- 被动可辨识 → 实现C6-A Set-Adaptive MPC；
- 被动不足但安全激励可行 → 实现C6-B Safe Dual MPC；
- 结构不可辨识 → 实现C6-C Capability-Set Robust MPC。

只能选择一个分支，不得把三种方法堆叠。

## 七、最终方法和理论

最终方法必须：

- 直接解决能力变化造成的预测/约束问题；
- 维护真值覆盖的模型/能力集合或概率集合；
- 使用负荷/状态估计，不读真值；
- 有backup控制器；
- 至少给出集合覆盖、递归可行性和约束安全条件；
- 在线计算满足2/4s周期。

## 八、实验硬要求

1. 正常1h和事故180–600s；
2. known final seeds每场景至少30，OOD至少50；
3. 全因子或明确LHS，不允许seed隐式绑定SG/noise；
4. PI、nominal MPC、RLS-MPC、robust MPC、proposed、Oracle；
5. 基准、消融、敏感性、鲁棒性、失败案例；
6. Plant A与Plant B；
7. failure-first、paired、scene-balanced统计；
8. final seeds不得调参；
9. 不得删除失败或降低标准。

## 九、自动失败处理

每次失败按顺序诊断：

```text
代码 → 数值/求解器 → 参数 → 模型 → 方法 → 科学假设
```

代码/数值错误修复后重跑；方法最多两轮有依据修复；若证据表明核心假设不成立，则停止当前路线并保存完整负结果，不得盲目换算法。

## 十、最终输出

生成：

```text
DIRECTION5_PHASE_C_FULL_REBUILD_AND_METHOD_COMPLETION_SINGLE_REVIEW_PACKAGE.zip
```

要求：

- 小于512MB；
- 内容严格符合 `09_FINAL_REVIEW_PACKAGE_SPEC.md`；
- 包含完整源码、配置、公式、文献、理论、全部逐episode指标、失败日志、代表/失败轨迹、图表源数据、Git、环境、SHA256和最终状态；
- 删除缓存、环境、checkpoint、重复文件和不必要中间数据；
- 不得删除支持结论的原始结果。

完成后在Codex最终消息中只需报告：

1. 最终ZIP绝对路径；
2. 大小；
3. SHA256；
4. Git commit；
5. 各科学Gate结果；
6. 选择的C6分支；
7. 最终研究状态；
8. 最严重的三项未解决限制。
