# Phase H 专家审查与最终裁决

## 1. 审查完整性

独立核验：

- ZIP SHA256：
  ```text
  2b9f30edf455d98bebe3c34001d0b16ce5f7c1528b8dcea97fc405b6bf5e3da1
  ```
- 597个文件，约22MB；
- manifest校验成功；
-包内状态：H0–H6通过，H7失败，H8未运行，H9完成；
- final seeds未使用；
- 包内测试报告为40 passed；
- 当前外部审查环境缺少 `cvxpy/casadi/andes/pyarrow`，因此没有把包内测试声明冒充成独立完整复跑结果；
- manifest脚本可运行；
- `reproduce_minimal.py` 在当前外部环境因缺少Parquet引擎失败，说明最小复现仍依赖完整环境，而非纯标准库自包含。

## 2. 总体裁决

```text
SCIENTIFIC_QUESTION: VALID_AND_WORTH_CONTINUING
PHYSICAL_MODEL_A: RETAIN_WITH_REBUILD_OF_EXPERIMENT DRIVER
PHYSICAL_MODEL_B: NOT USED AS NATIVE FINAL VALIDATION
CAPABILITY_ESTIMATOR: NOT A VALID GUARANTEED CAPABILITY ESTIMATOR
DCSV_FORMULATION: STRUCTURALLY MPC BUT PHYSICAL/UNCERTAINTY SEMANTICS INCOMPLETE
H7_RESULTS: INVALID_FOR_METHOD CLAIMS
H5_NOVELTY: NOT SUPPORTED
OVERALL_ACTION: FINAL MAJOR REBUILD, NOT TERMINATION
```

IEEE Transactions审稿判断：

> 当前版本不具备投稿条件。问题本身可保留，但方法、最终实验和声明必须重建。属于拒稿后重构，而非普通大修。

## 3. 科学问题的有效部分

有效问题应收缩为：

> 黑箱IBR的**外部可交付能力**发生未通知变化时，控制中心能否从公共测量中把净负荷变化与设备执行能力退化分开，并基于“合同保证能力下界 + 因果更新的可交付能力集合 + 测得SoC/能量”安全协调多区域SFR？

不再把以下全部当作隐藏且可精确估计的独立变量：

```text
power, ramp, delay, energy, availability
```

正确语义为：

- power/ramp：由command-to-actual-power数据维护可交付集合；
- delay：维护有限候选/有界集合；
- energy：由测得SoC、电池容量和效率直接计算，不作为黑箱隐变量；
- availability：不单独估计，体现在power/ramp可交付包络中；
- 合同保证下界：用于安全硬约束；
- 在线估计的额外能力：只用于性能改善，不能作为未经认证的安全保证。

## 4. 致命问题

### 4.1 H7场景因素被seed取模混杂

`run_h7_validation.py:79–130` 使用同一个 `seed % n` 同时决定：

- domain；
- SG reserve；
- period；
- mechanism；
- load area/sign/magnitude；
- initial SoC；
- noise；
- dropout；
- jitter；
- repeated change。

因此机制效应、SG紧张度、采样周期和噪声无法独立解释。

### 4.2 1小时正常运行结果是人工零行，不是仿真

`run_h7_validation.py:570–616` 直接插入：

```text
physical_success=True
frequency_iae=0
ace_iae=0
tie_iae=0
controller_calls=0
```

这些不是正常净负荷仿真。任何“1h正常运行安全”声明必须撤回。

### 4.3 H7没有完整闭环运行

- sustainable场景默认只运行8个控制更新；
- bridge场景运行到60s handoff后4个更新；
- 随后300–600s保持最后动作，不再滚动控制。

这不是完整SFR闭环，也不能评价实时MPC可靠性、恢复性和长期SoC。

### 4.4 Plant B final并非原生ANDES闭环

H7对Plant B使用与Plant A相同的线性ZOH模型，并加高斯扰动，标为：

```text
native_residual_calibrated_reduced
```

它不是原生ANDES动态验证。`plant_a_b_direction_consistent`因此不能支持跨模型结论。

### 4.5 H7没有测试“未通知能力变化”

能力真值从episode起点就固定为异常状态。没有：

```text
nominal warm-up
→ capability change at unknown time
→ diagnosis/adaptation
→ responsibility reallocation
```

`repeated_change`改变的是负荷，不是设备能力。H7没有直接测试核心科学事件。

### 4.6 能力集合估计器的安全语义错误

`capability_set_estimator.py`：

- power/ramp下界只是历史已观察出力/爬坡的最大值，不等于未来保证能力；
- abrupt downward change后存在旧下界暂时过度乐观；
- energy lower bound使用“已经移动的能量”，并随能量使用增加，不是剩余可用能量；
- availability interval始终为 `[0,1]`，没有实际估计；
- delay使用启发式静态增益/偏置和固定±0.4s扩张，没有形式化覆盖。

因此H3“全部能力集合已覆盖”不能解释为获得了可用于安全约束的保证能力集合。

### 4.7 H7人为能力floor掩盖估计问题

`run_h7_validation.py:235–253` 强制：

```text
power >= 0.020 pu
ramp >= 0.008 pu/s
energy >= 0.40 MWh
```

这相当于公共合同下界。若设备可能跌破这些值，方法不安全；若合同保证这些值，安全主要来自合同，而不是在线估计器。论文必须明确二者的角色。

### 4.8 MPC能量模型与物理SoC不一致

`dcsv_mpc.py:320–332` 将充电和放电都作为正的累计“energy_used”：

\[
E_{\mathrm{used},k+1}
=
E_{\mathrm{used},k}
+
T_s(P^+/\eta_d+\eta_cP^-).
\]

这不是电池能量状态。物理Plant中充电会增加储能能量。MPC输入中的 `energy_state_mwh` 也没有实际进入预测约束。

### 4.9 availability没有实际作用

能力估计器始终输出 `[0,1]`。MPC只检查上界是否大于0，因此availability机制不会被直接识别或约束，只能间接表现为出力不足。

### 4.10 delay interval只取三点，没有连续集合外包证明

DCSV只使用：

```text
lower, midpoint, upper
```

三个延迟点。没有证明这些顶点包络整个连续延迟区间，也没有稠密网格验证误差。

### 4.11 bridge时钟与能量预算未正确递减

`DCSVInput.time_to_slow_reserve_s`在H7中每次仍传60s。控制器内部虽有 `bridge_state`，但下一周期输入没有使用其剩余时间。bridge terminal与energy budget因此没有形成一致的滚动接管模型。

### 4.12 H7成功标准过宽且无终端恢复

physical success主要检查：

```text
|f| <= 0.8 Hz
|ACE| <= 0.3 pu
|tie| <= 0.15 pu
energy within broad range
```

没有要求：

- 末端频率/ACE/tie回零；
- 恢复时间；
- 调频备用恢复；
- 正常运行品质；
- 连续事件可持续性。

所有方法100%成功并不能说明控制质量。

## 5. 重大问题

1. DCSV对延迟场景求和代价，不是明确的最坏情景epigraph目标；
2. `contract_robust_mpc`的固定能力可能高于某些注册真能力，不能称为覆盖全部场景的鲁棒基线；
3. `RLSAdaptiveMPC`本身没有完整RLS动态模型更新，名称过强；
4. H7只有16个paired validation场景，CI很宽；
5. bootstrap按场景行重采样，没有按seed/设计簇处理；
6. `failure_aware_cost`混合不同量纲且权重无物理来源；
7. slow reserve在60s瞬时减去负荷，没有动态接管模型；
8. capability change、load change、measurement noise没有全因子独立；
9. H6 Plant B理论只基于reduced layer，不是native DAE theorem；
10. bridge certificate采用简化冲量界和宽松安全阈值，不能代替完整动态证书；
11.审查包含重复源码/结果及历史ZIP，但仍低于512MB；
12.最小复现依赖环境中的Parquet引擎，需明确环境契约。

## 6. 可保留内容

- 高层科学问题；
- Plant A两区域频率、ACE和tie-line结构；
- actual BESS POI power进入负荷观测器的思想；
- sustainable/bridge/infeasible三域框架；
-共同控制序列的延迟场景MPC结构；
- action-history一致性修复；
-失败保存、manifest、final seed firewall；
- H4有限样本覆盖统计框架；
- Plant A条件性终端集合计算框架；
- H7 development-only基线选择原则。

## 7. 当前结果的正确解释

当前证据只能支持：

> 当前DCSV原型在一个小型、因素混杂、短时主动控制、后续保持动作的线性约束仿真中，没有在16个Plant-A validation pairs上达到预注册CI门。

不能支持：

- DCSV-MPC类别无效；
- 黑箱能力在线适应没有价值；
- 能力集合估计已被证明可靠；
- Plant B方向一致；
- 方法适合1h正常运行；
- 已形成投稿级创新。
