# 正式价值信息边界与选择性VOI-ACCR-MPC数学推导

## 1. 注册预测模型

令增广状态：

\[
z_k=
[x_k^\top,h_k^\top,E_k^\top]^\top,
\]

其中 \(x_k\) 包含频率、ACE相关状态、联络线、SG和BESS实际功率；\(h_k\) 为已执行命令管线；\(E_k\) 为BESS能量。

对候选能力模型：

\[
\theta\in\Theta_k
\]

有：

\[
z_{j+1}
=
A_\theta z_j+B_\theta u_j+Gd_j+w_j,
\quad
w_j\in\mathcal W.
\tag{1}
\]

测量：

\[
y_j=Cz_j+v_j,
\quad v_j\in\mathcal V.
\tag{2}
\]

所有安全与价值计算必须使用相同的：

- 模型；
- 能力候选；
- delay pipeline；
- energy state；
- disturbance/noise sets；
- objective scales。

## 2. 归一化控制目标

为了避免tie weight为0却以tie作为论文终点，使用有物理尺度的目标：

\[
\ell(z,u)
=
\left(\frac{\Delta f}{f_s}\right)^2
+
\left(\frac{ACE}{a_s}\right)^2
+
\left(\frac{p_{\mathrm{tie}}}{t_s}\right)^2
+
\lambda_g\left(\frac{\Delta u_g}{g_s}\right)^2
+
\lambda_b\left(\frac{\Delta u_b}{b_s}\right)^2.
\tag{3}
\]

尺度 \(f_s,a_s,t_s,g_s,b_s\) 在development前锁定。论文同时报告三组运行偏好敏感性，但不能对每个场景单独调权重。

## 3. 合同鲁棒基线

定义N步鲁棒策略集 \(\Pi_N\)。

合同基线代价：

\[
J^{R}(z,\Theta)
=
\min_{\pi\in\Pi_N}
\max_{\theta\in\Theta,\ w\in\mathcal W}
L(z,\pi,\theta,w),
\tag{4}
\]

其中：

\[
L
=
\sum_{j=0}^{N-1}\ell(z_j,u_j)+V_f(z_N).
\tag{5}
\]

对应策略：

\[
\pi^R(z,\Theta).
\tag{6}
\]

## 4. 注册控制器族内的完美信息代价

\[
J^{PI}(z,\Theta)
=
\max_{\theta\in\Theta}
\min_{\pi_\theta\in\Pi_N}
\max_{w\in\mathcal W}
L(z,\pi_\theta,\theta,w).
\tag{7}
\]

由minimax不等式：

\[
J^{R}(z,\Theta)
\ge
J^{PI}(z,\Theta).
\tag{8}
\]

定义注册控制器族内的完美信息价值：

\[
V^{PI}(z,\Theta)
=
J^{R}(z,\Theta)-J^{PI}(z,\Theta)
\ge0.
\tag{9}
\]

必须称为：

```text
registered-formulation perfect-information value
```

不得称为任意控制器的全局上界。

## 5. 安全探测

探测序列：

\[
q=(q_0,\ldots,q_{L-1})\in\mathcal Q.
\tag{10}
\]

SG–BESS命令层分配：

\[
u_{g,j}^{q}=u_{g,j}^{R}-q_j,
\tag{11}
\]

\[
u_{b,j}^{q}=u_{b,j}^{R}+q_j.
\tag{12}
\]

因此：

\[
u_{g,j}^{q}+u_{b,j}^{q}
=
u_{g,j}^{R}+u_{b,j}^{R}.
\tag{13}
\]

式(13)只表示命令中性。SG和BESS动力学不同，实际功率并不中性，必须进入预测。

安全探测集合：

\[
\mathcal Q_{\mathrm{safe}}(z,\Theta)
=
\left\{
q:
z_j^{\theta,w,q}\in\mathcal X,\;
u_j^{\theta,w,q}\in\mathcal U,\;
\forall\theta,w,j
\right\}.
\tag{14}
\]

## 6. 周期归一化

探测以物理时长：

\[
T_p
\tag{15}
\]

而不是固定控制步数定义。

对控制周期 \(T_s\)：

\[
L(T_s)=\left\lceil T_p/T_s\right\rceil.
\tag{16}
\]

探测序列必须在物理时间和能量上可比。若4s周期下最短零和探测为8s，其代价应自然反映在价值边界中，不能直接复用2s设计并宣称同一方法。

## 7. 探测观测管

给定 \(q\)，候选 \(\theta\) 的可能观测集合：

\[
\mathcal Y_\theta(q)
=
\left\{
Y_\theta(z,q,w,v):
w\in\mathcal W,\;
v\in\mathcal V
\right\}.
\tag{17}
\]

收到观测 \(y\) 后：

\[
\Theta_y(q)
=
\left\{
\theta\in\Theta:
y\in\mathcal Y_\theta(q)
\right\}.
\tag{18}
\]

所有非空可能后验构成：

\[
\mathfrak P(q)
=
\left\{
\Theta_y(q):
y\in\bigcup_{\theta}\mathcal Y_\theta(q),\;
\Theta_y(q)\ne\varnothing
\right\}.
\tag{19}
\]

有限候选时可以通过观测管重叠图或精确分区计算。

## 8. 完美后续控制下的探测价值上界

探测期间代价：

\[
L_p(z,q,\theta,w).
\tag{20}
\]

探测结束状态：

\[
z_L^{q,\theta,w}.
\tag{21}
\]

即使探测后立即获得真实候选，任何探测策略的代价也不可能低于：

\[
\underline J_q^{PI}(z,\Theta)
=
\max_{\theta,w}
\left[
L_p(z,q,\theta,w)
+
\min_{\pi_\theta}
L_{\mathrm{rem}}(z_L^{q,\theta,w},\pi_\theta,\theta)
\right].
\tag{22}
\]

因此探测净收益上界：

\[
\overline V_q(z,\Theta)
=
J^R(z,\Theta)-\underline J_q^{PI}(z,\Theta).
\tag{23}
\]

### 定理1：无探测必要区域

若：

\[
\max_{q\in\mathcal Q_{\mathrm{safe}}}
\overline V_q(z,\Theta)
\le0,
\tag{24}
\]

则任何使用该探测库和注册控制器族的因果后验策略都不可能优于合同基线。

证明：真实后验控制不优于式(22)的完美信息控制，因此其代价不低于 \(\underline J_q^{PI}\)。

式(24)给出严格的：

```text
no-probe region
```

## 9. 实际后验鲁棒追索代价

对每个后验集合：

\[
\Theta'\in\mathfrak P(q),
\]

定义：

\[
J^R(z_L,\Theta')
=
\min_{\pi_{\Theta'}}
\max_{\theta\in\Theta',w}
L_{\mathrm{rem}}(z_L,\pi_{\Theta'},\theta,w).
\tag{25}
\]

探测的实际最坏代价：

\[
J^q(z,\Theta)
=
\max_{\theta,w,v}
\left[
L_p(z,q,\theta,w)
+
J^R
\left(
z_L^{q,\theta,w},
\Theta_{Y_\theta(q,w,v)}(q)
\right)
\right].
\tag{26}
\]

净价值：

\[
V^q(z,\Theta)
=
J^R(z,\Theta)-J^q(z,\Theta).
\tag{27}
\]

最优净价值：

\[
V^\star(z,\Theta)
=
\max
\left\{
0,\;
\max_{q\in\mathcal Q_{\mathrm{safe}}}
V^q(z,\Theta)
\right\}.
\tag{28}
\]

## 10. 正值区域、零值区域与边界

\[
\mathcal R_+
=
\left\{
(z,\Theta):
V^\star(z,\Theta)>0
\right\},
\tag{29}
\]

\[
\mathcal R_0
=
\left\{
(z,\Theta):
V^\star(z,\Theta)=0
\right\},
\tag{30}
\]

\[
\partial\mathcal R
=
\overline{\mathcal R_+}
\cap
\overline{\mathcal R_0}.
\tag{31}
\]

边界依赖：

\[
\zeta
=
[
r_g,\,
T_s,\,
d,\,
\operatorname{diam}\Theta_P,\,
\operatorname{diam}\Theta_R,\,
\operatorname{diam}\Theta_\tau,\,
\sigma_y,\,
SOC,\,
p_{\mathrm{tie}}
].
\tag{32}
\]

论文的核心科学结果是：

\[
V^\star(\zeta)
\]

及其符号边界。

## 11. 选择性策略

\[
q^\star
=
\arg\max_{q\in\mathcal Q_{\mathrm{safe}}}
V^q(z,\Theta).
\tag{33}
\]

若：

\[
V^{q^\star}\le\eta,
\tag{34}
\]

则：

\[
q=0,\qquad
\pi=\pi^R.
\tag{35}
\]

### 定理2：零值区域基线等价

若控制器使用完全相同的基线对象、状态估计和求解器，且式(34)成立，则当前动作及后续无探测策略与合同MPC一致。

这条性质必须用bitwise/numerical回归测试验证。

## 12. 候选集合包含性

初始：

\[
\theta^\star\in\Theta_0.
\tag{36}
\]

若真实误差满足注册观测管，则递推：

\[
\Theta_{k+1}
=
\left\{
\theta\in\Theta_k:
y_{k+1}\in\mathcal Y_\theta(u_k)
\right\}
\tag{37}
\]

保证：

\[
\theta^\star\in\Theta_k.
\tag{38}
\]

若集合为空，必须：

- 声明change/OOD；
- 撤销证书；
- 返回合同能力；
- 不能从旧候选中选一个“最接近”模型继续保证。

## 13. 探测安全定理

若：

\[
q\in\mathcal Q_{\mathrm{safe}}(z,\Theta)
\]

且：

\[
\theta^\star\in\Theta,\quad
w\in\mathcal W,\quad
v\in\mathcal V,
\]

则探测预测时域内：

\[
z_j\in\mathcal X,\quad
u_j\in\mathcal U.
\tag{39}
\]

该定理只覆盖注册时域和集合。

## 14. 决策相关等价

若所有候选的最优第一动作近似相同：

\[
\max_{\theta,\theta'}
\left\|
u_\theta^\star-u_{\theta'}^\star
\right\|
\le\epsilon_u,
\tag{40}
\]

且完美信息价值满足：

\[
V^{PI}\le\epsilon_J,
\tag{41}
\]

则候选不确定性在当前状态下为decision-irrelevant。

这可作为计算筛选，但最终探测仍以式(27)为准。

## 15. 价值回收率

仅在：

\[
J^R-J^{PI}>J_{\min}^{\mathrm{mat}}
\]

时定义：

\[
\rho
=
\frac{
J^R-J^{\mathrm{selective}}
}{
J^R-J^{PI}
}.
\tag{42}
\]

若分母非正或过小，标记为：

```text
NOT_MATERIAL / NA
```

不得要求回收率。

## 16. 边界统计估计

对development样本 \(\zeta_m\)，计算：

\[
\hat V^\star_m.
\]

使用自适应采样重点逼近：

\[
|\hat V^\star|\approx0
\]

的边界区域。

Validation中固定边界预测：

\[
\hat c(\zeta)\in\{\mathrm{probe},\mathrm{abstain}\}.
\]

必须报告：

- false-positive probe rate；
- positive-region precision；
- boundary calibration；
- net benefit conditional on predicted positive region；
- baseline equivalence conditional on predicted no-probe region。

## 17. 预计结果边界

基于当前M2的方向性证据，预期但不保证：

- 2s周期比4s更容易出现正值区域；
- power/ramp uncertainty比delay-only更有价值；
- 大候选能力差异、较高ACE/tie敏感度更可能进入正区；
- 4s、delay-only、高噪声和小Oracle gap大多属于无探测区；
- 正区的ACE/tie净改善可能只有0.5%–3%，但应为统计正值；
- 全局平均应接近合同MPC，而不是追求大幅提升。
