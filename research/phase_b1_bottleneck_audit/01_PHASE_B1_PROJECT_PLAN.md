# Phase B1 Project Plan — Scientific Bottleneck Audit

## 总目标

在不修改旧 SD-BMPC 核心算法的前提下，完成一次可审计的科学瓶颈分解，回答：

> 当前方向五没有形成优势，主要是因为黑箱 IBR 的价值不足、辨识模型不准确、闭环数据不可辨识，还是 belief/worst-case/fallback 控制设计不合理？

本轮完成后必须停止并输出审查包，等待外部评审后再进入新方法阶段。

---

## Phase B0 — 冻结第二版基线

### 任务

1. 在真实工作仓库中核验：
   - review ZIP SHA256：`2e1c3bfc380c57172a5d96663a6ab90cf95b79511f60cefce73ce4c38e2f04a9`；
   - frozen Phase-6 commit：`20f652f5f8b180a2518798d0ed85aa3f48212908`。
2. 审查包中的 Git status 不是干净状态，因此必须：
   - 核对未提交修改与审查包 `git/diff.patch` 一致；
   - 把 Phase-7 最终兼容性修改和报告提交为一个明确的 baseline commit；
   - 建立 tag：`phase-a-final-reviewed-v2`；
   - 从该 tag 创建分支：`phase-b1-bottleneck-audit`。
3. 将旧 `results/`、`artifacts/` 和 `figures/` 视为只读基线，禁止覆盖。
4. 运行 609 个基线测试并记录哈希。

### 输出

- `progress_phase_b1/PHASE_B0_REPORT.md`
- `artifacts_phase_b1/baseline_manifest.json`
- `logs_phase_b1/pytest_baseline.txt`

### 门槛

- 测试全部通过；
- baseline commit 清晰；
- 旧结果文件哈希不变。

---

## Phase B1 — 新增精确非线性评测 Oracle

### 任务

保留现有：

```text
B4 = truth-mode identified-ARX oracle
```

但必须将其名称解释修正为“真实模式选择的辨识 ARX”，不能再称为 exact oracle。

新增：

```text
B5 = simulator-exact nonlinear oracle benchmark
```

B5 仅存在于 evaluation-only 路径，可以读取当前真实模式、真实非线性 IBR 参数、真实延迟、限幅、速率和死区。B5 与其他方法必须使用：

- 相同控制周期；
- 相同 SG/IBR 命令约束；
- 相同频率安全约束；
- 相同扰动信息；
- 相同初始状态。

B5 可使用离线较慢的非线性 MPC、直接多重射击或 simulator-in-the-loop shooting，不要求实时，但必须报告近似误差和求解失败。

### 输出

- `src/d5freq/evaluation/exact_nonlinear_oracle.py`
- `tests_phase_b1/test_exact_oracle_isolation.py`
- `results_phase_b1/oracle_validation/`

---

## Phase B2 — Problem Materiality Audit

### 目的

判断黑箱 IBR 在研究场景中是否真的具有值得研究的频率控制价值。

### 预注册 SG 能力级别

不得根据结果临时修改：

| Level | SG command | SG ramp | 含义 |
|---|---:|---:|---|
| A | ±0.12 pu | 0.020 pu/s | 当前基线，SG充足 |
| B | ±0.08 pu | 0.012 pu/s | 中等同步机灵活性 |
| C | ±0.055 pu | 0.006 pu/s | 低同步机灵活性但应保持物理可行 |

若 Level C 对 B5 也不可行，必须报告不可行，不得事后放宽到有利数值。

### 比较

每个 Level 至少比较：

- B0 LQI-only；
- B2 RLS-MPC；
- B4 truth-mode identified-ARX；
- B5 exact nonlinear oracle。

### 必须回答

1. B5 相比 B0 能否显著改善 frequency IAE、最大频差或恢复时间？
2. B5 能否在不恶化频率安全的情况下明显减少 SG mileage？
3. IBR 的价值只在极端人为弱 SG 场景出现，还是在合理 Level B 也出现？

### 决策门

若 B5 在所有物理可行 Level 中均不能满足任一条件：

- frequency IAE 相比 B0 改善至少 10%，且最大频差不恶化超过 2%；
- 或 SG mileage 改善至少 20%，且 frequency IAE 不恶化超过 2%；

则结论必须为：

```text
PROBLEM_NOT_MATERIAL
```

并停止新方法开发。

---

## Phase B3 — Model Adequacy Audit

### 任务

逐真实模式、逐 SG Level、逐场景计算：

- ARX 一步预测误差；
- 5/10/20 步开环 IBR 功率预测误差；
- 频率与 RoCoF 传播误差；
- 闭环滚动预测误差；
- 饱和、rate limit、deadband、delay 激活比例；
- B4 与 B5 的配对性能差距。

### 核心判断

如果 B5 明显优于 B4，则离线 ARX 模型失配是重要瓶颈：

```text
MODEL_MISMATCH_DOMINANT
```

不得仅通过增加 GMM 组件数量解决连续模型失配。

---

## Phase B4 — Passive Identifiability Audit

### 任务

只使用控制器在正常闭环运行中可获得的数据，针对 2/5/10/20 s 窗口计算：

- 回归 Gramian 最小特征值；
- condition number；
- pairwise predictive log-likelihood margin；
- mode/regime 间 Jensen-Shannon divergence；
- 切换后达到可区分阈值的最短时间；
- 信息不足窗口比例；
- 负荷扰动与设备模式变化的混淆率。

同时构建一个 evaluation-only Bayes classifier，在拥有正确候选模型但只能使用被动闭环测量时评估可达到的识别上限。

### 核心判断

若正确模型可用，但被动测量在关键控制时限内仍无法区分模式，则结论为：

```text
IDENTIFIABILITY_DOMINANT
```

此时后续应研究安全主动辨识/双重控制，而不是继续改分类器结构。

---

## Phase B5 — Control-Design Decomposition

### 目的

在模型和诊断条件受控时，分解 sticky prior、worst-mode cost、constraint tightening 和 binary fallback 的影响。

### 必须实现的 counterfactual controllers

1. `C0_true_arx_expected`：真实模式选择 ARX，只用 expected cost；
2. `C1_true_arx_worst`：同一模型，加入旧 worst-mode cost；
3. `C2_perfect_belief_current_mpc`：perfect belief + 当前 MPC；
4. `C3_current_belief_expected`：当前 belief + expected cost，无 worst term；
5. `C4_gradual_authority`：当前诊断 + 连续权限收缩，不使用二元 full fallback；
6. `C5_no_sticky_prior`：窗口似然或无 sticky prior 的对照。

这些控制器只用于 audit，不得用 final seeds 调参。

### 核心判断

若 B4/诊断上限足够好，但当前 P 仍明显差，则：

```text
CONTROL_DESIGN_DOMINANT
```

---

## Phase B6 — 形成正式瓶颈决策

输出：

```text
progress_phase_b1/BOTTLENECK_DECISION.md
```

只允许以下主结论：

```text
PROBLEM_NOT_MATERIAL
MODEL_MISMATCH_DOMINANT
IDENTIFIABILITY_DOMINANT
CONTROL_DESIGN_DOMINANT
COMBINED:<primary>+<secondary>
```

报告必须包含：

- 证据表；
- 置信区间；
- 配对统计检验；
- 场景分层；
- 反例和失败案例；
- 下一方法分支建议。

### 后续分支建议，但本轮不得实现

- `MODEL_MISMATCH_DOMINANT`：控制等效模型库 + library-regularized online adaptation；
- `IDENTIFIABILITY_DOMINANT`：安全主动辨识 / dual MPC；
- `CONTROL_DESIGN_DOMINANT`：简化的 trust-aware adaptive MPC + gradual authority contraction；
- `PROBLEM_NOT_MATERIAL`：重新定义物理场景或终止该方向。

---

## Phase B7 — 打包审查

最终只输出：

```text
D5_PHASE_B1_BOTTLENECK_AUDIT_REVIEW_PACKAGE.zip
```

必须小于 512 MB，并符合 `05_REVIEW_PACKAGE_SPEC.md`。
