# 锁定科学问题和论文目标

## 1. 科学问题

> 在多区域二次频率调节中，当黑箱IBR的可交付功率、爬坡和延迟不确定时，能否根据这些不确定性对当前控制决策的影响，只在“信息收益超过探测代价”的状态下，执行安全的SG–IBR分配探测，并回收部分完美能力信息对ACE、联络线责任和同步机调节成本的价值，同时保持频率安全不劣于合同MPC？

该问题的关键词是：

```text
decision relevance
value of information
safe active certification
selective abstention
multi-area frequency responsibility
```

## 2. 核心科学对象：探测值得区域

定义候选能力集合 \(\Theta_k\)、状态估计 \(\hat x_k\)。

合同MPC动作：

\[
u_k^c.
\]

候选模型 \(\theta\) 下的完美模型最优代价：

\[
J_\theta^\star(\hat x_k).
\]

合同动作在候选模型下的遗憾：

\[
\mathcal R_k
=
\max_{\theta\in\Theta_k}
\left[
J_\theta(u_k^c)-J_\theta^\star
\right].
\]

探测 \(q\) 后可能得到不同测量结果 \(y\)，产生后验候选集合：

\[
\Theta_{k+L}^{y,q}.
\]

探测后的最坏残余遗憾：

\[
\overline{\mathcal R}_k^+(q)
=
\max_{y}
\max_{\theta\in\Theta_{k+L}^{y,q}}
\left[
J_\theta(u_{k+L}^{\Theta_{k+L}^{y,q}})
-
J_\theta^\star
\right].
\]

探测最坏控制代价：

\[
\overline C_{\mathrm{probe},k}(q).
\]

净信息价值下界：

\[
\underline V_k(q)
=
\mathcal R_k
-
\overline{\mathcal R}_k^+(q)
-
\overline C_{\mathrm{probe},k}(q).
\]

定义：

\[
\mathcal X_{\mathrm{probe}}
=
\left\{
(\hat x_k,\Theta_k):
\max_q\underline V_k(q)>\eta
\right\}.
\]

只在该集合中探测。

## 3. 方法名称

> **VOI-ACCR-MPC：Value-of-Information-Gated Active Capability Certification and Recourse MPC**

中文：

> **价值信息门控的主动能力认证–追索模型预测多区域二次频率控制**

## 4. 目标论文结果

### 全场景安全目标
相对合同MPC：

- 成功率下降不超过1个百分点；
- 物理硬约束违反为0；
- 最大频差非劣，绝对差不超过0.02 Hz；
- fallback不高于合同MPC超过1个百分点；
- p99求解时间小于控制周期的一半。

### 探测值得子集性能目标
在预注册的 `probe-worthwhile` 场景中：

- ACE或tie至少一个改善不低于4%，置信区间下界大于0；
- 回收完美信息价值至少30%，置信区间下界大于0；
- SG机械里程不恶化；
- 探测引起的增量频差不超过0.02 Hz；
- 候选集合直径降低至少50%；
- false optimism不超过1%。

### 探测不值得子集
方法必须主动放弃探测，并在数值误差范围内退化为合同MPC。

## 5. 大致预期结果

基于当前包，合理预测为：

| 场景 | 预期行为 |
|---|---|
| power uncertainty + SG高紧张度 | 最可能触发探测并产生ACE/tie收益 |
| power uncertainty + SG低紧张度 | 部分触发，收益较小 |
| ramp uncertainty + SG低紧张度 | 可能有正价值 |
| ramp uncertainty + SG高紧张度 | 多数应放弃探测 |
| delay-only uncertainty | 多数应放弃探测，按鲁棒延迟处理 |
| Oracle gap很小 | 不探测，退化为合同MPC |
| OOD或contract violation | 撤销证书并进入合同/应急控制 |

这些是方向性预测，不是可以通过修改数据强制得到的事实。
