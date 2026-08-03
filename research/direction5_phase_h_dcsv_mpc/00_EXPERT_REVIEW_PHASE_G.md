# Phase G 专家审查结论

## 1. 完整性与可复现性

独立核验结果：

- ZIP SHA256：
  ```text
  018dc05b6d78bec9069114b19986b21fbfdba6d04f5caeb42d9c563f03c53d79
  ```
- ZIP 内文件约 282 个；
- manifest 记录 281 个受管文件；
- 281/281 个受管文件存在且 SHA256 一致；
- `verify_manifest.py`、`reproduce_minimal.py` 和
  `verify_negative_boundary.py` 可以运行；
- final seeds 未使用；
- G0/G1 通过，G2 失败，G3–G8 未执行。

该包的治理和诚实报告值得保留。

## 2. 总体科学裁决

```text
SCIENTIFIC_QUESTION: CONTINUE
PHASE_G_G2_NEGATIVE_CONCLUSION: INVALIDATED
CURRENT_TERMINAL_DATASET: NOT_TERMINAL-CONSISTENT
CURRENT_LOAD_UNCERTAINTY_MODEL: MISSPECIFIED
CURRENT_OBSERVER: DELAY/CAPABILITY-CONFLATING
CURRENT_CDSR_METHOD: NOT_EVALUATED
OVERALL_ACTION: MAJOR MODEL-ESTIMATION-TERMINAL REBUILD
```

应把当前状态从：

```text
LOCAL_TERMINAL_MODEL_NOT_CERTIFIABLE
```

改为：

```text
TERMINAL_SET_CALIBRATION_PREMATURE_AND_MISSPECIFIED
```

这不等于方向5、黑箱能力问题或鲁棒 MPC 失败。

## 3. 致命问题

### 3.1 near-terminal 筛选不符合注册规范

注册规范要求：

- 距离新事件至少一个完整 prediction horizon；
- 位于 terminal neighborhood；
- 无执行器饱和；
- 无 GRC 切换；
- observer 已完成 warm-up；
- 无 solver/fallback 异常。

实际 `run_g2_uncertainty.py` 只检查：

- warm-up；
- 频率、ACE、tie 阈值；
- 距离事件大于 `6*period`。

没有检查：

- SG 阀门边界；
- SG 机械功率边界；
- GRC 激活；
- BESS 功率/爬坡/能量限制；
- command saturation；
- fallback；
- 与负荷相关平衡点的距离。

因此局部终端样本混入了受限执行器、桥接状态和不可持续状态。

### 3.2 阶段顺序错误

Phase G 先在 G2 构造终端局部集合，后在 G3 才计划划分：

```text
SUSTAINABLE
BRIDGE_ONLY
PHYSICALLY_INFEASIBLE
```

这是逆序的。

终端集合必须围绕可持续负荷相关平衡点构造。桥接状态和物理不可行状态不能被用于校准无限时域终端扰动。

### 3.3 负荷误差的动态语义错误

当前将负荷估计误差区间通过 \(E_d\) 映射，并在每个控制周期作为可独立重复的新冲击加入。

而增广观测器假设：

\[
d_{k+1}=d_k+\nu_k.
\]

此时主要不确定量应是：

- 持续负荷偏差；
- 负荷变化率 \(\nu_k\)；
- 估计误差状态 \(\tilde d_k\)。

不能把一个持续偏差每周期重复作为新 load step 注入。

终端模型应围绕：

\[
x^\star(\hat d)
\]

建立，并将 \(\tilde d_k\) 作为增广参数/状态处理。

### 3.4 观测器把 BESS 执行失配吸收到负荷估计

当前 observer 以历史 issued command 作为输入，使用不含完整 delay/capability dynamics 的 nominal model 预测 BESS 状态。

但公共测量已经包含实际 BESS POI 功率。更合理的负荷/电网状态观测器应把实际测得的 \(p_b\) 当作已知外部输入，从而避免把：

- 延迟；
- 降额；
- 爬坡；
- 能量限制；
- 服务退出

误认为净负荷变化。

能力估计应在独立的 command-to-actual-power 通道中完成。

### 3.5 小样本经验覆盖被过度解释

部分 4 s/horizon 组合的 validation near-terminal 窗口只有个位数。即使 6/6 全覆盖，也不能作为总体覆盖率不低于 95% 的有力统计证明。

需要：

- 更大独立 validation 样本；
- split conformal；
- 或二项分布下界/Clopper–Pearson 置信下界。

### 3.6 审查包不是完整重跑快照

Phase G 的脚本导入：

```text
scripts.phase_e.run_e3_materiality
scripts.phase_f.run_f3_model_sets
```

但当前 ZIP 的 `06_SOURCE/scripts/` 只包含 Phase G。最小状态重放能运行，但无法从该 ZIP 独立重新生成完整 G2 数据。

下一包必须包含完整可安装源码快照和所有依赖脚本。

## 4. 重大问题

1. 终端 Gate 使用“零状态一步半径小于所有性能阈值”作为必要条件，未围绕负荷依赖平衡点；
2. current local set 同时包含 observer error、model mismatch 和 persistent load bias，语义仍不清；
3. observer 的 4 s 采样模型可观测但可能病态，需报告 observability conditioning；
4. H1 材料性直接继承 Phase F，未在纠正估计器/场景分类后重新验证；
5. G3/G4 本应先于局部终端标定；
6. 没有 Plant B 核心验证；
7. 缓存文件仍出现在 ZIP；
8. literature registry 含 2026 preprint，核心创新不能主要依赖预印本。

## 5. 可保留内容

- 科学问题和信息边界；
- Plant A 的标幺频率、ACE、tie-line 框架；
- BESS 共享 PFR/SFR 物理能力结构；
- 因果公共测量接口；
- delay vertex 思路；
- global vs local uncertainty 的分离原则；
- sustainable/bridge/infeasible 的计划概念；
- 失败保存、Gate、manifest 和 final seed firewall；
- H1 初步材料性结果，作为待重新验证的先验证据。

## 6. 下一步固定路线

不继续调当前 observer 或 terminal threshold。采用：

```text
外部扰动/负荷估计器：
    使用 actual SG mechanical power 与 actual BESS POI power 作为已知输入

设备能力集合估计器：
    单独使用 issued command、actual BESS power、local frequency、SoC
    维护 power/ramp/delay/energy capability set

场景物理分类：
    sustainable / bridge-only / physically infeasible

控制方法：
    DCSV-MPC
    sustainable: parameterized-equilibrium robust MPC + terminal RCI
    bridge: finite-horizon viability MPC + energy/slow-reserve contract
    infeasible: truthful emergency/failure classification
```
