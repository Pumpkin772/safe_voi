# 结果驱动的科研执行计划

本计划只有三个科研里程碑，不以大量阶段清单驱动。

## 总目标

获得以下论文级结果：

> VOI-ACCR-MPC能自动识别探测值得区域；在该区域回收部分完美能力信息对ACE或联络线的价值；在其他区域主动放弃探测并退化为合同MPC；全场景保持频率安全和物理约束非劣。

Codex在development中可以自主探索，但不得修改：

- 科学问题；
- 物理参数来源范围；
- validation/final场景；
- 成功标准；
- final seeds。

---

## 里程碑M1：形成集成正收益原型

### 在达到M1前禁止Git提交

Codex只能使用：

```text
scratch_direction5/
research_outputs_working/
progress_working.json
```

保存工作。

### 必须完成

1. 复现当前ACCR失败；
2. 删除固定0.05 BESS基准和盲目重复探测；
3. 实现VoI和decision-relevance门；
4. 探测围绕当前合同MPC动作；
5. 实现证书有效期、被动续期、cooldown和change reset；
6. 完整闭环评价，不使用孤立探测代替集成验证；
7. 自动搜索：
   - probe序列；
   - 幅值；
   - VoI阈值；
   - cooldown；
   - certificate validity；
   - estimator window；
   - MPC horizon/weights。

### 允许的探索

Codex可在development范围内持续运行自动搜索，直到：

- 满足M1目标；或
- 完成预注册设计空间并证明不存在正净收益区域。

### M1目标

在至少8个development场景、覆盖power/ramp和两种SG紧张度时：

- 物理硬约束0；
- 频率峰值相对合同MPC不劣，差值≤0.02 Hz；
- 至少4个场景被判定为probe-worthwhile；
- probe-worthwhile场景中：
  - ACE或tie平均改善≥3%；
  - 候选集合直径降低≥50%；
  - false optimism≤1%；
- probe-not-worthwhile场景中：
  - 探测次数为0；
  - 与合同MPC动作/性能近似一致；
- 不允许固定base造成未计量的责任跳变。

### M1提交规则

仅在M1通过后允许第一次Git提交：

```text
direction5-m1-integrated-positive-prototype
```

若穷尽设计空间仍无非空正收益区域，则生成决定性负结果并结束，不提交中间碎片。

---

## 里程碑M2：独立validation

### 固定M1方法

M1之后：

- 只允许修复代码错误；
- 不允许根据validation调整算法；
- 若需要设计修改，必须返回development并废弃该轮validation。

### Validation范围

- Plant A；
- 原生Plant B；
- power/ramp/delay；
- 2s/4s；
- low/high SG；
- known/OOD；
- capability与load前/后/同时；
- 300–600s完整闭环；
- 正常1h真实仿真；
- contract violation单独。

### M2论文Gate

#### 全场景
- 成功率下降≤1个百分点；
- 物理硬约束0；
- 最大频差非劣margin≤0.02 Hz；
- fallback不高于合同MPC超过1个百分点；
- p99求解时间<0.5控制周期。

#### Probe-worthwhile预注册子集
- ACE或tie至少一个改善≥4%，分层Bootstrap CI下界>0；
- 完美信息价值回收率≥30%，CI下界>0；
- SG机械里程不恶化；
- candidate diameter reduction≥50%；
- probe incremental frequency≤0.02 Hz。

#### Probe-not-worthwhile子集
- 探测率≤5%；
- 核心指标相对合同MPC绝对变化≤1%。

#### 跨模型
- Plant A和Plant B在probe-worthwhile子集的改善方向一致。

### M2提交规则

M2通过后允许第二次Git提交：

```text
direction5-m2-independent-validation
```

若M2失败，Codex不得立即停止。它必须判断：

- M1过拟合；
- VoI估计误差；
- 探测成本低估；
- Plant B模型差异；
- 统计样本不足；
- 代码错误。

允许回到development自动修复，但validation数据不能用于直接调参。需要新建新的validation split。

---

## 里程碑M3：Final与论文

只有M2通过才运行Final。

### Final规则

- 锁定代码、参数、manifest和hash；
- final seeds从未用于开发；
- 只运行一次；
- 不调参；
- 不删失败；
- known/OOD分开；
- contract violation单独。

### 最终状态

只允许：

```text
PAPER_READY_WITH_BOUNDED_CLAIMS
```

或：

```text
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```

### 最终Git

完成Final和审查包后才允许第三次提交和tag：

```text
direction5-final
```

---

## Codex不应频繁询问

Codex自行完成：

- 错误诊断；
- development自动搜索；
- 失败分类；
- M1/M2是否达到；
- 数据生成；
- 图表和论文。

只有遇到以下致命问题才允许停止：

1. 软件环境无法运行且无法修复；
2. 原生Plant B无法在任何正式系统上运行；
3. 材料性重新验证完全不成立；
4. 预注册探测设计空间中不存在安全正VoI区域；
5. validation和新的独立validation均否定M1结果。
