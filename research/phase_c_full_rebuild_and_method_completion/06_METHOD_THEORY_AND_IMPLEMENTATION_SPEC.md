# 最终方法、理论与实现规范

本文件定义三个互斥分支。Codex不能自由发明第四种方法，也不能同时堆叠三个分支。C5 Gate决定唯一分支。

## A. Control-Relevant Set-Adaptive MPC（被动可辨识）

### A1. 模型

预测模型：

\[
x_{k+1}=A(\theta_k)x_k+B(\theta_k)u_k+Ew_k,
\qquad \theta_k\in\Theta_k.
\]

离线能力库提供先验中心 \(\bar\theta_j\) 和协方差/集合；在线用窗口数据更新：

\[
\hat\theta_k=\arg\min_\theta
\sum_{i=k-L+1}^{k}\lambda^{k-i}
\|y_i-\phi_i^\top\theta\|_{R^{-1}}^2
+\mu\|\theta-\theta_{0,k}\|_{W}^2.
\]

其中：

\[
\theta_{0,k}=\sum_j b_{j,k}\bar\theta_j.
\]

### A2. 能力集合更新

\[
\Theta_{k+1}=
\{\theta\in\Theta_k:
\|y_{k+1}-\hat y_{k+1}(\theta)\|\le\epsilon_k\}
\oplus\mathcal Q_\theta.
\]

必须防止集合因噪声错误排除真值；使用统计置信膨胀或set-membership噪声界。

### A3. Robust/tube MPC

\[
\min_{U}\sum_{i=0}^{N-1}
\|ACE_{k+i}\|_Q^2+\|u_{k+i}\|_R^2+\|\Delta u_{k+i}\|_S^2
+V_f(x_{k+N})
\]

对所有 \(\theta\in\Theta_k,w\in\mathcal W\)：

\[
x_{k+i}\in\mathcal X\ominus\mathcal E_i,
\quad
u_{k+i}\in\mathcal U(\Theta_k)\ominus K\mathcal E_i.
\]

使用terminal invariant set和backup controller保证递归可行。

## B. Safe Dual Frequency MPC（需要主动辨识）

### B1. 双重目标

\[
J=J_{reg}+\lambda_I J_{info},
\]

其中可用：

\[
J_{info}=-\log\det(F_k+\epsilon I)
\]

或候选模型预测分布的期望KL/互信息。

### B2. 安全激励条件

只有当：

1. 当前状态位于robust safe set；
2. backup controller从所有候选模型下均可行；
3. 激励后预测约束仍满足；
4. 信息收益超过预注册阈值；
5. 激励能量/里程预算未超限；

才允许辨识动作。

否则令 \(\lambda_I=0\)，退化为robust regulation MPC。

### B3. 责任转移

IBR不确定时不应二元退出，而使用连续权限系数：

\[
0\le\alpha_k\le1,
\quad
u_{b,k}=\alpha_k\nu_{b,k}^{MPC},
\]

\(\alpha_k\)由能力集合、可靠度和backup裕度决定。

## C. Capability-Set Robust MPC（结构不可辨识）

不建立模式概率，不声称诊断真实状态。维护：

\[
\mathcal C_k=\{P^\pm,R^\pm,\tau,E^{avail},a\}
\]

并求解：

\[
\min_U\max_{c\in\mathcal C_k,w\in\mathcal W}J(U;c,w)
\]

满足所有能力集合下的频率、ACE、资源约束。随着外部数据到来，集合只在保证覆盖的条件下收缩。

## 共同的负荷/状态估计

部署方法不能读取真实负荷。应联合估计：

\[
\hat x_k,\hat d_k,P_k
\]

并把估计不确定性加入 \(\mathcal W\) 或tube。

## Backup控制器

必须实现一个低复杂度、可证明约束安全的PI/LQI/robust state feedback backup。任何MPC超时、不可行、估计发散时切换；切换逻辑必须有滞回，避免抖振。

## 理论最低要求

### 定理1：集合覆盖

在噪声界/置信假设下，若 \(\theta^\star_k\in\Theta_k\) 且参数漂移 \(q_k\in\mathcal Q_\theta\)，则更新后以确定性或至少 \(1-\alpha\) 概率满足 \(\theta^\star_{k+1}\in\Theta_{k+1}\)。

### 定理2：递归可行性

若当前MPC可行、终端集对backup不变、真实模型属于集合且扰动属于集合，则下一采样时刻问题仍可行。

### 定理3：约束安全

在上述条件和求解器成功下，频率、ACE、SG和IBR物理约束对整个闭环成立；求解失败时backup保持安全。

### 主动分支附加命题

辨识动作只在robust safe set内执行，因此不改变安全定理的有效性。

## 实现限制

- 不得使用真实regime标签训练在线分类器后直接部署，除非标签仅用于离线评估；
- 不得把neural network作为必要组件，除非线性/LPV模型明确不足且验证数据支持；
- 不得为了“AI创新”额外加入PPO、Transformer或GNN；
- solver应优先凸QP/SOCP；若使用NMPC，必须满足实时性和收敛审计。
