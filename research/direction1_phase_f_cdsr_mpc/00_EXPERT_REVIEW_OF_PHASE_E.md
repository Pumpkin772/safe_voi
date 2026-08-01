# Phase E 专家审查与下一步裁决

## 1. 当前包的可信部分

- ZIP 自身完整，文件清单哈希可验证。
- Plant A 的频率单位、两区域 ACE、联络线、SG GRC 和 BESS 共享 PFR/SFR 能力结构基本合理。
- Plant B 已改为原生 ANDES Kundur RMS/DAE 闭环接口，BESS 通过原生网络注入功率；包内报告的动态接口误差和代数残差处于较小量级。
- E3 给出了“知道当前真实能力可能具有显著控制价值”的证据。
- E4/E5 没有删除不利结果，且没有在失败后临时切换到未预注册算法。
- E6 的成功 episode 中，当前方法相对固定比例 PI 在频率、ACE 和联络线 IAE 上有明显改善。

## 2. Phase E 结论需要修正

### 2.1 G6 不是科学问题的致命失败

唯一失败 Gate 是：

```text
solver_infeasibility = 1.846% > 1%
```

但当前控制架构本来包含 SG-only fallback。该指标没有区分：

- QP 真正数学不可行；
- OSQP 数值不收敛；
- CLARABEL 二次求解失败；
- 求解结果残差超限；
- 预测终端状态被 box 拒绝；
- fallback 后下一周期的历史动作不同步；
- 连续多个 fallback 形成的级联问题。

因此，应将 Phase E 最终状态改为：

```text
METHOD_IMPLEMENTATION_AND_CERTIFICATE_INCOMPLETE
```

而不是把它外推为：

```text
METHOD_CLASS_NOT_SUPPORTED
```

### 2.2 决定性的代码缺陷：实际动作未提交给预测器

`FiniteHorizonMPC.solve()` 在 QP 成功时立即把候选第一动作写入 `previous_action`。

随后 `CapabilitySetRobustTubeMPC.update()` 可能因为终端 box 不通过而执行 SG-only fallback。此时：

- 物理系统执行的是 fallback 动作；
- MPC 内部保存的却是被拒绝的候选动作。

若 QP 本身未解出，MPC 又保留更早的旧动作。

下一周期的延迟模型和 slew 约束于是使用错误的“上一周期已执行动作”。这会特别破坏 delay 场景，并可造成连续不可行。

必须改成“提议—接受/回退—提交”三阶段接口：

```text
proposal = optimizer.propose(...)
applied = supervisor.accept_or_fallback(proposal)
optimizer.commit_applied_action(applied)
```

任何求解器对象不得在提议尚未被最终采用前修改物理动作历史。

### 2.3 当前所谓 tube MPC 还没有形成严格 tube 控制

当前 `finite_horizon_reachable_tube()`：

- 只对一个固定 nominal model 构造有限时域 axis-aligned box；
- disturbance radius 为手工常数，未由预测残差或物理误差校准；
- 得到的 LQR ancillary gain 并没有在线实际作用于控制输入；
- 没有 robust positively invariant error set；
- 没有递归可行性证明；
- `SGTerminalBackupSet` 只是一个经验 box，没有证明受 SG-only backup 控制不变。

因此当前方法最多应称为：

> 采用经验约束收紧和终端筛查的鲁棒化 MPC 原型。

本轮禁止继续使用 “tube guarantee” 或 “recursive feasibility” 声明，除非 F5 完成可独立重算的证书。

### 2.4 能力集合没有完整进入预测约束

当前方法以 0.03 pu 功率、0.012 pu/s 爬坡和 2 s 延迟作为保守值，但：

- 只用一个最坏延迟模型，不显式覆盖延迟集合；
- BESS预测状态的资源约束被延后到 horizon 之外；
- 没有在 MPC 内显式传播最低可持续能量；
- availability/headroom 主要被压缩为固定功率上限；
- 真实执行器受 delay、ramp、energy 和 PFR/SFR共享约束，预测模型并未全部一致表示。

后续必须采用“保证能力包络”而不是物理模式标签：

\[
\underline{\mathcal C}
=
\{\underline P^\pm,\underline R^\pm,\bar\tau,\underline E_{\rm avail}\}.
\]

该包络应有明确物理来源，并在所有预测场景中一致约束总 BESS 功率。

### 2.5 H1、H2、H3 的表述需收缩

- E3 的最佳基线使用全部 development+validation 数据选择，存在验证集泄露。
- E3 连续指标只比较双方成功的 episode；个别 cell 中 Oracle 成功率更低仍被判 material。
- H2 只能写成“已测试的三类被动估计器在注册自然激励下未通过”，不能写成所有被动辨识均不可能。
- H3 只能写成“已测试的 0.04 pu 交替探针不安全/成本过高”，不能写成所有主动辨识均不可能。

本轮需重新生成 failure-aware、development-only 的科学状态表。

### 2.6 审查包的最小复现脚本不能直接在解压包中运行

`reproduce_minimal.py` 仍按原仓库目录寻找：

```text
research_outputs_phase_e/
results_phase_e/
progress_phase_e/
```

但审查包把它们重排到了 `09_RAW_RESULTS`、`16_FINAL_STATUS` 等目录。下一审查包必须：

- 要么保持可直接运行的仓库相对路径；
- 要么提供 review-package-aware 路径映射；
- 并在一个全新临时目录中实际执行最小复现测试。

## 3. 当前方向裁决

```text
SCIENTIFIC_QUESTION: CONTINUE
PHYSICAL_PLATFORMS: RETAIN_WITH_TARGETED_FIXES
PASSIVE/ACTIVE IDENTIFICATION: RETAIN_AS_LIMITED_NEGATIVE_EVIDENCE
CURRENT TUBE CLAIM: WITHDRAW
CURRENT G6 FATAL INTERPRETATION: WITHDRAW
NEXT METHOD: CDSR-MPC
OVERALL_ACTION: MAJOR METHOD REBUILD, NOT NEW DIRECTION
```
