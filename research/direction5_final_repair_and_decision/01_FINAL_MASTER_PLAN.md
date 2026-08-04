# 方向5最终修复与裁决：R0–R8

## 唯一终态

完成后只允许：

```text
PAPER_READY_WITH_BOUNDED_CLAIMS
```

或：

```text
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```

禁止创建新的Phase继续迭代。

---

## R0：冻结Phase I并重算正确统计

### 目标
撤回错误终止，建立可信的当前证据基线。

### 输入
- Phase I review ZIP；
-当前Git仓库；
-I6逐episode与逐cycle结果。

### 任务
1. 建立：
   ```text
   tag: direction5-phase-i-reviewed
   branch: direction5-final-repair-and-decision
   ```
2. 重算：
   - paired failure table；
   -双方成功的绝对差；
   - scenario-balanced aggregate means；
   - aggregate-mean relative improvement；
   - seed/design-cell hierarchical bootstrap；
   -失败惩罚敏感性；
   - Plant A/B方向；
   -所有求解尝试的正确分母。
3. 诊断 normal1h >2Hz：
   - PI anti-windup；
   -积分饱和；
   -slow reserve；
   -domain分类；
   -Plant A稳定性。
4. 复现缺失contract-MPC对照的归因缺陷。

### 输出
```text
00_FORENSIC/PHASE_I_CORRECTION.md
10_RAW_RESULTS/R0/CORRECTED_PAIRED_STATISTICS.parquet
11_SUMMARY_TABLES/R0/PAIRED_FAILURE_TABLE.csv
11_SUMMARY_TABLES/R0/AGGREGATE_MEAN_IMPROVEMENTS.csv
11_SUMMARY_TABLES/R0/HIERARCHICAL_BOOTSTRAP.csv
11_SUMMARY_TABLES/R0/SOLVER_DENOMINATOR_AUDIT.csv
13_FAILURES/R0/NORMAL1H_STABILITY_DIAGNOSIS.md
tests/test_r0_statistics_and_phase_i_defects.py
```

### 必须实验
-只用现有Phase I数据完成；
-不得先改算法；
-独立复算所有Gate。

### 成功
-统计可由逐episode数据重算；
-所有失败分母定义明确；
-Phase I终止状态更正。

### 失败
原始数据不足以重算时，停止为：
```text
PHASE_I_EVIDENCE_NOT_AUDITABLE
```

### 衔接
R0给R1材料性和R5性能Gate提供基准。

---

## R1：锁定创新、材料性和安全边界

### 目标
证明科学问题值得做，并锁定不再变动的声明。

### 任务
1. 更新≥60篇正式文献/官方资料；
2. 明确closest works；
3. 重新验证H1：
   - true-capability rolling Oracle；
   - contract-only rolling MPC；
   -至少power/ramp/delay三机制；
   -两种SG tension；
   -完整能力变化事件；
   -成功率优先。
4. 形式化瞬时contract violation不可保证边界。
5. 锁定唯一方法DCSV-CR-MPC。

### 输出
```text
01_SCIENCE/LOCKED_QUESTION.md
01_SCIENCE/HYPOTHESES.md
01_SCIENCE/IMPOSSIBILITY_BOUNDARY.md
02_LITERATURE/LITERATURE_REVIEW.md
02_LITERATURE/NOVELTY_MATRIX.csv
02_LITERATURE/SEARCH_LOG.csv
11_SUMMARY_TABLES/R1/MATERIALITY_BY_MECHANISM.csv
```

### 成功
-至少2个能力机制、2个SG tension中，Oracle相对contract MPC有材料性价值；
-正式文献未完整覆盖交叉问题。

### 失败
-材料性不成立：终止 `PROBLEM_NOT_MATERIAL`；
-创新不足：终止 `NOVELTY_NOT_SUFFICIENT`。

---

## R2：重建估计器、合同语义和真实基线

### 目标
让负荷–能力分离和在线能力集合具有正确数学语义。

### 负荷观测器
候选：
- constrained MHE；
- unknown-input observer；
- augmented Kalman。

使用actual BESS POI power作为已知输入。

### 可交付集合
建立真正的模型可行集：

\[
p_{k+1}=a p_k+b u_{k-d}+e_k,
\quad |e_k|\le\epsilon.
\]

对每个delay candidate维护可行 \((a,b)\) 集和power/ramp约束。

输出：
- delay candidate set；
- robust online performance envelope；
- excitation/identifiability status；
- coverage diagnostics。

### 合同语义
-合同floor用于硬安全；
-online envelope只用于可撤销性能；
-contract violation进入应急域。

### 基线
实际实现并验证：
1. SG-only anti-windup PI；
2. fixed-allocation anti-windup PI；
3. nominal offset-free MPC；
4. contract-only rolling robust MPC；
5. model-adaptive/RLS MPC；
6. true-capability Oracle。

### 输出
```text
03_MODEL/LOAD_OBSERVER.md
03_MODEL/DELIVERABILITY_FEASIBLE_SET.md
03_MODEL/CONTRACT_SEMANTICS.md
04_METHOD/BASELINES.md
results/R2/ESTIMATOR_COVERAGE.parquet
results/R2/LOAD_CAPABILITY_CONFUSION.parquet
results/R2/BASELINE_STABILITY.parquet
tests/test_r2_estimators_and_baselines.py
```

### 成功
- delay coverage≥95% validation；
- online envelope false optimism≤1%；
-无激励不虚假收缩；
-PI正常运行稳定；
-所有MPC是真实滚动优化；
-无truth/future泄漏。

### 失败
最多两轮同框架修复。
结构不可辨识量转为鲁棒集合。
若在线集合不能比contract提供可用信息，方法必须退化为contract MPC；若无性能价值，终止。

---

## R3：实现DCSV-CR-MPC

### 目标
使在线能力真正影响控制，同时不把其当作无条件安全保证。

### 控制分解

\[
u_b=u_b^{g}+u_b^{s}
\]

- \(u_b^g\)：合同保证分量；
- \(u_b^s\)：在线性能剩余分量。

### 两类未来分支

1. **Delivered branch**
   - surplus按在线模型交付；

2. **Loss/recourse branch**
   - surplus不交付或延迟；
   - SG/慢速备用在下一控制周期进行追索；
   -所有分支共享当前动作；
   -未来追索动作允许分支化。

### 硬约束
-合同分量；
-SG/BESS power/ramp；
-实际SoC energy；
-delay pipeline；
-frequency/ACE/tie安全边界；
-terminal/bridge；
-所有分支。

### 优化
使用最坏情景epigraph：

\[
\min t+\text{slack penalty}+\text{control effort},
\quad J_s\le t.
\]

### Contract violation
跌破合同floor：
-不纳入合同安全定理；
-立即route到SG/slow reserve emergency；
-单独评价检测与恢复。

### 输出
```text
04_METHOD/DCSV_CR_MPC_FORMULATION.md
04_METHOD/PSEUDOCODE.md
04_METHOD/EQUATION_CODE_MAP.csv
06_SOURCE/src/direction5freq/controllers/dcsv_cr_mpc.py
06_SOURCE/src/direction5freq/controllers/recourse_tree.py
06_SOURCE/src/direction5freq/controllers/contract_violation_supervisor.py
tests/test_r3_dcsv_cr_mpc.py
```

### 成功
-真rolling MPC；
-在线能力改变可撤销性能分量而非仅成本；
-合同loss branch安全；
-actual-action commit正确；
-hard violations=0；
-action availability=100%；
-实时。

### 失败
最多两轮formulation/数值修复，不换算法。

---

## R4：理论与证书

### 必须完成

1. **不可保证边界**
   -能力无预警跌破任何已知下界时，同瞬间命令可执行性不可保证。

2. **合同分支有限时域鲁棒约束**
   -真实能力包含合同floor；
   -delay/model error属于注册集合。

3. **surplus loss recourse条件**
   -额外能力未交付时，SG/slow reserve可在检测后保持频率/ACE约束。

4. **可持续终端集合**
   -Plant A局部RPI/RCI；
   -load-parameterized equilibrium。

5. **bridge条件**
   -真实SoC、power/ramp和slow reserve动态。

6. **不可行证书**

### 输出
```text
05_THEORY/ASSUMPTIONS.md
05_THEORY/THEOREMS_AND_PROOFS.md
05_THEORY/CONTRACT_BRANCH_CERTIFICATE.*
05_THEORY/RECOURSE_CERTIFICATE.*
05_THEORY/SUSTAINABLE_TERMINAL_SET.*
05_THEORY/BRIDGE_CERTIFICATES.parquet
05_THEORY/INFEASIBILITY_CERTIFICATES.parquet
05_THEORY/REPRODUCE_CERTIFICATES.py
```

### 成功
-证书可重算；
-代码使用同一对象；
-无法证明递归时主动收缩声明。

### 失败
若有限时域合同/追索证书均无法建立，终止方法路线。

---

## R5：完整物理平台与开发/验证定型

### 场景
每个核心episode：
```text
nominal warm-up
→ randomized unannounced capability change
→ independent load event before/after/simultaneous
→ full rolling control through 300–600s
```

### Plant A
-完整非线性；
-因素显式独立；
-positive/negative load；
-2s/4s；
-不同SoC；
-noise/jitter/dropout；
-repeated capability changes。

### Plant B
原生ANDES：
-至少2种SG tension或运行点；
-positive/negative load；
-known/OOD；
-能力变化；
-部分noise/jitter；
-完整滚动。

### Normal1h
-使用公开实测负荷/净负荷窗口；若无法获得，只能明确标为synthetic；
-每方法≥6条；
-anti-windup；
-频率品质Gate。

### Gate
- success drop≤2pp；
- failure-aware不劣；
-相对**contract-only rolling MPC**至少2/3指标改善≥8%，cluster CI lower>0；
-相对PI也完整报告；
-terminal recovery不劣；
-hard violation=0；
-known contract域 backup≤1%；
-numerical failure≤0.1%；
-p99<0.5Ts；
-Plant A/B方向一致；
-normal1h不出现未解释的大频偏。

### 修复
最多两轮development/validation修复。

### 失败
仍失败：
```text
DIRECTION5_METHOD_NOT_SUPPORTED_AFTER_FINAL_CORRECTED_VALIDATION
```
停止，不运行final。

---

## R6：Final预注册和一次性运行

### 前提
R5全部通过。

### Final
-锁定config/hash；
-final seeds仅运行一次；
-known与OOD分开；
-contract violation单独；
-不回调算法；
-所有失败保留。

### OOD
-复合能力变化；
-非对称能力；
-连续delay；
-slow drift；
-新SoC；
-Plant B新运行点；
-合同违约；
-连续能力变化。

---

## R7：论文级结果、消融和审稿防线

### 消融
- no load/capability separation；
- no online surplus；
- no recourse branch；
- point-estimate delay；
- no bridge supervisor；
- contract-only MPC；
- oracle。

### 图表
-信息边界；
-能力集合；
-合同/在线双层结构；
-追索树；
-frequency/ACE/tie；
-SoC/energy；
-known/OOD；
-Plant A/B；
-solver/fallback；
-failure cases；
-theory certificates；
-computation。

### 论文文件
```text
14_PAPER_ANALYSIS/CONTRIBUTIONS.md
14_PAPER_ANALYSIS/RESULTS_NARRATIVE.md
14_PAPER_ANALYSIS/REVIEWER_RISK_REGISTER.md
14_PAPER_ANALYSIS/SUPPORTED_UNSUPPORTED_CLAIMS.md
14_PAPER_ANALYSIS/PAPER_ROUTE.md
```

---

## R8：最终统一审查包和终态

最终只能是：

```text
PAPER_READY_WITH_BOUNDED_CLAIMS
```

或：

```text
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```

最终ZIP：

```text
DIRECTION5_FINAL_REPAIR_AND_DECISION_SINGLE_REVIEW_PACKAGE.zip
```

小于512MB，fresh-extract minimal replay必须通过。
