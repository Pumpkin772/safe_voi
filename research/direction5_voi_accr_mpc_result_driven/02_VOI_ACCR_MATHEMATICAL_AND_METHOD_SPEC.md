# VOI-ACCR-MPC数学与实现规范

## 1. 保留的基础模型

保留当前包中已经通过审计的：

- 两区域Plant A；
- 原生Plant B接口；
- 实际POI功率负荷观测器；
- 合同能力；
- SoC能量模型；
- 慢速备用；
- 候选power/ramp/delay模型；
- 合同MPC；
- 完美能力Oracle。

## 2. 必须删除的旧逻辑

### 删除固定探测基准

禁止：

```python
base_bess = ±0.05
```

新的探测必须围绕当前已接受的合同MPC分配：

\[
u_{b,k}=u_{b,k}^{c}+q_k,
\]

\[
u_{g,k}=u_{g,k}^{c}-q_k.
\]

完整的责任转移都必须计入探测代价。

### 删除“无证书就自动探测”

探测必须经过：

1. decision relevance；
2. value-of-information；
3. 当前状态安全；
4. cooldown/hysteresis；
5. 预测probe cost；
6. 候选集合可区分性。

### 删除固定周期重复探测

同一能力事件最多主动探测一次。只有满足以下条件才允许再次探测：

- 已检测到新能力变化；
- 证书过期；
- 被动数据不能续期；
- 新的净VoI下界仍为正；
- cooldown已结束。

## 3. 探测候选

从有限库开始：

- biphasic；
- staircase；
- alternating；
- zero-mean PRBS；
- 围绕当前分配的优化序列。

幅值应依据当前headroom自动裁剪：

\[
|q_k|
\le
\min
\{
q_{\max},
P_g^{\mathrm{headroom}},
P_b^{\mathrm{request\ headroom}}
\}.
\]

## 4. 集成安全评价

每个候选探测必须在完整滚动控制环境中评价：

- 完整300–600秒episode；
- 只允许一次探测；
- capability和load事件；
- 证书使用；
- 证书撤销；
- 全部候选能力和contract-only交付；
- Plant A开发；
- Plant B代表场景验证。

A3式的短局部仿真只作为预筛选，不能作为最终安全结论。

## 5. 候选集合和后验分区

对有限候选集合：

\[
\Theta_k=\{\theta_1,\dots,\theta_M\}.
\]

对探测 \(q\) 和可能输出区间，预计算候选的可区分分区：

\[
\Pi(q)=
\{
\Theta_k^{(1)}(q),\ldots,\Theta_k^{(L)}(q)
\}.
\]

若探测后所有分区对应的最优第一动作几乎相同：

\[
\max_{\ell,\ell'}
\|
u^\star_{\Theta^{(\ell)}}-
u^\star_{\Theta^{(\ell')}}
\|
\le\epsilon_u,
\]

则该不确定性不是decision-relevant，禁止探测。

## 6. VoI近似

允许使用有限候选近似：

\[
\hat{\mathcal R}_k
=
\max_{\theta\in\Theta_k}
\left[
J_\theta(u_c)-J_\theta^\star
\right].
\]

\[
\hat{\mathcal R}_k^+(q)
=
\max_{\Theta'\in\Pi(q)}
\max_{\theta\in\Theta'}
\left[
J_\theta(u_{\Theta'}^\star)-J_\theta^\star
\right].
\]

\[
\hat V_k(q)
=
\hat{\mathcal R}_k
-
\hat{\mathcal R}_k^+(q)
-
\hat C_{\mathrm{probe},k}(q).
\]

触发：

\[
q_k^\star
=
\arg\max_{q\in\mathcal Q}\hat V_k(q),
\]

仅当：

\[
\hat V_k(q_k^\star)>\eta.
\]

## 7. 证书使用

探测后的候选集合：

\[
\Theta_k^+.
\]

有限有效期内的能力下界：

\[
\underline P_k
=
\min_{\theta\in\Theta_k^+}P_\theta,
\]

\[
\underline R_k
=
\min_{\theta\in\Theta_k^+}R_\theta,
\]

\[
\overline\tau_k
=
\max_{\theta\in\Theta_k^+}\tau_\theta.
\]

安全声明条件：

- 候选集合包含真实模型；
- 有效期内能力不发生新突变；
- 残差界成立。

检测到change/reset时，立即撤销证书并退回合同MPC。

## 8. 证书模式MPC

在证书有效且无change evidence时，使用认证下界作为有限时域能力约束。

不必在每一步同时假设认证剩余能力完全消失；该突然消失属于不可能性边界外的contract-violation-like事件，下一周期退回合同MPC。

必须清楚声明：

> 证书安全是“能力在有效期内保持于候选集合”的条件性保证，不是任意突降保证。

## 9. 防止无收益探测的性质

若：

\[
\max_q\hat V_k(q)\le0,
\]

则：

\[
u_k^{\mathrm{VOI-ACCR}}
=
u_k^{\mathrm{contract}}.
\]

这应作为软件回归测试和方法核心性质。

## 10. 需要证明或数值验证

1. 分配命令中性；
2. 候选集合包含性；
3. 探测有限时域安全；
4. VoI非正时的主动放弃性质；
5. 证书有效期内的条件性资源约束；
6. change reset后的合同回退；
7. 探测值得区域的非空性；
8. 价值回收率。

## 11. 价值回收率

对某指标 \(J\)：

\[
\rho_J
=
\frac{
J_{\mathrm{contract}}
-
J_{\mathrm{VOI-ACCR}}
}{
J_{\mathrm{contract}}
-
J_{\mathrm{oracle}}
}.
\]

仅在分母为正且大于最小材料性阈值时评价。

不允许在Oracle无正价值的场景中要求价值回收。
