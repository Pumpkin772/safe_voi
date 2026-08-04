# Phase I 专家审查

## 1. 完整性

独立核验：

```text
ZIP SHA256:
06c550b32d3c28fdbcec94344d57b6163a311d7b32409bb2773918589a0904c5
```

- ZIP约21MB；
- 解压约26MB；
- 文件约562个；
- 包内状态：I0–I5 PASS，I6 FAIL，I7 NOT_EVALUATED，I8 PASS；
- final seeds未使用；
- 包内测试报告为43个Phase-I测试通过；
- 外部审查环境缺少cvxpy/casadi/andes/pyarrow，因此没有把包内测试声明冒充为独立完整复跑。

## 2. 总体裁决

```text
SCIENTIFIC_QUESTION: VALID_AND_VALUABLE
PHASE_I_FINAL_TERMINATION: INVALIDATED
PLANT_A: RETAIN
PLANT_B_NATIVE: RETAIN_WITH_BROADER_DESIGN
LOAD_OBSERVER_CONCEPT: RETAIN
DELIVERABILITY_ESTIMATOR: REBUILD
DCSV_MPC: MAJOR REFORMULATION
STATISTICS: REBUILD
OVERALL_ACTION: ONE FINAL REPAIR_AND_DECISION PROGRAM
```

IEEE Transactions判断：

> 当前版本不能投稿。高层问题可保留，但“决定性负结论”由统计、对照和方法归因缺陷驱动，必须撤回。需要一次最终重建；修正后仍失败才允许终止方向5。

## 3. 致命问题

### 3.1 I6主统计使用不稳定的逐episode相对比值

代码：

```python
improvement = (baseline - proposed) / abs(baseline)
mean(improvement)
```

当某些baseline指标很小时，少数episode会产生极大比值并主导均值。

包内failure-aware aggregate means为：

| metric | DCSV | PI | aggregate-mean improvement |
|---|---:|---:|---:|
| frequency peak | 1.14428 | 1.33101 | +14.03% |
| ACE IAE | 70.7476 | 89.2710 | +20.75% |
| tie RMS | 0.119942 | 0.150058 | +20.07% |

但当前程序报告的“mean relative improvement”却分别为：

```text
-4.27%
-31.76%
-138.32%
```

这说明当前2/3指标Gate被统计定义而非总体性能驱动。

这并不自动证明DCSV优越；但足以使“决定性负证据”失效。

### 3.2 所谓cluster bootstrap并未按cluster重采样

代码只对scenario行独立抽样。Plant A中同一seed在多个factor cell重复使用，独立行bootstrap低估/扭曲相关性。

必须使用：
- paired absolute differences；
- scenario-balanced aggregate means；
- seed/design-cell hierarchical bootstrap；
- paired failure table。

### 3.3 最关键的公平基线没有进入I6

I4中已经存在：

```text
rolling_contract_mpc
```

它与DCSV具有相同模型、时域和硬约束，只关闭online performance envelope。

但I6锁定方法只有：

```text
dcsv_mpc
fixed_allocation_pi
```

缺少contract-only rolling MPC意味着不能回答：

> 在线能力集合究竟提供了什么增益？

这是归因创新的决定性缺口。

### 3.4 能力估计器不是MHE或严格set-membership

`DeliverabilitySetMHE`实际执行：

- 功率能力：历史最大实际出力减残差；
- 爬坡能力：历史最大爬坡减残差；
- delay：最后一次命令阶跃到阈值响应的启发式区间；
- upper bound长期固定为物理最大值。

没有：
- 参数可行集优化；
- MHE目标与约束；
- 动态模型集合；
- abrupt downward change后的保证更新；
- 在线集合的未来可交付证明。

因此H3的“60/60覆盖”主要源于：

- 真值始终位于宽物理上界内；
- 合同下界低于所有注册真值；
- 无激励时集合几乎不收缩。

它证明了宽集合覆盖样本，不证明当前可交付能力被有效识别。

### 3.5 在线能力只改变目标权重

当前DCSV硬约束始终使用合同floor。在线性能能力只通过：

```text
降低BESS输入二次成本权重
```

影响目标函数。

这导致在线能力的控制贡献很弱，也无法证明其安全/适应意义。

### 3.6 合同能力已经覆盖全部I6真值

I6 known/OOD中真实power、ramp、delay均未跌破合同floor/上界。

因此：
- 合同MPC理论上已经足以安全；
- 在线能力只能带来性能差异；
- 更必须比较contract-only MPC；
- contract-violation实验被排除在主Gate外，无法说明跌破合同后的闭环性能。

### 3.7 Delay鲁棒性不完整

DCSV只取：

```text
0 s
contract max delay
```

两个顶点，不使用在线delay interval，也没有把连续delay中间值的模型误差作为正式不确定性进入优化。

I5稠密delay测试只检查资源power/ramp/energy，不足以证明整个状态/频率/ACE预测被端点外包。

### 3.8 模型误差集合没有进入最终MPC

理论声明包含contract/delay/model-error assumptions，但I6 QP没有显式传播注册模型误差集合。理论与代码范围不一致。

### 3.9 BESS预测的hard constraints不完全使用contract语义

命令使用合同power/ramp，但预测actual BESS power使用物理rating和0.10pu/s ramp。

这意味着：
- hard safety并没有完全依赖合同保证的实际交付能力；
- 请求命令可行不等于实际POI功率在所有能力情景下按模型实现。

### 3.10 Domain supervisor不支持过频/负负荷

代码将load estimate截断为非负：

```python
load = maximum(load, 0)
```

负荷下降或发电过剩场景因此被错误分类。

Plant A manifest中已有负号场景，当前三域分类并不对称。

### 3.11 Solver/fallback统计分母错误

`solver_calls`只在返回非空预测序列时增加。QP失败并fallback时可能不进入solver_calls分母。

因此：

```text
unresolved_infeasibility / solver_calls
```

不是“全部尝试求解中的失败率”。

必须以每个控制决策的attempted optimization call为分母。

### 3.12 Baseline不充分

I6只用fixed allocation PI。

缺少：
- SG-only PI；
- anti-windup PI；
- nominal offset-free MPC；
- contract-only robust MPC；
- model-adaptive MPC；
- true-capability Oracle。

当前PI积分器无显式anti-windup，正常1小时出现超过2.2Hz的最大频差，需要首先诊断稳定性和饱和恢复。

### 3.13 Plant B验证范围过窄

Plant B仅覆盖：
- low SG tension；
- positive load；
- sustainable；
- no noise/jitter/dropout。

不能支持广义跨模型鲁棒性。

### 3.14 H1原始材料性证据在本包中不充分

FINAL_STATUS直接写H1 supported，但审查包未提供足够细的true-capability Oracle对照来独立验证每个机制的材料性。

### 3.15 当前H5负结论的正确解释

Phase I只能说明：

> 当前DCSV原型在现有比较与统计程序下未通过锁定Gate。

不能说明：
- 在线能力信息无价值；
- DCSV类别无效；
- 方向5应终止。

## 4. 可保留内容

- 科学问题及信息边界；
- actual BESS POI power用于负荷估计；
- 合同floor与online envelope双层语义；
- sustainable/bridge/infeasible三域；
- Plant A和原生ANDES Plant B基础；
- action transaction和full rolling；
- impossibility boundary；
-局部Plant A终端证书；
-失败保存、manifest和final firewall。

## 5. 最终建议

进行一次且仅一次最终修复与裁决。

最终方法应升级为：

> **DCSV-CR-MPC：合同安全–性能追索MPC**

其安全基础不是不可靠的在线能力点估计，而是合同floor；在线能力用于额外性能，并通过“额外交付/额外丢失”分支和未来SG/慢速备用追索控制吸收风险。
