# DCSV-CR-MPC方法规范

## 1. 控制分量

\[
u_b=u_b^g+u_b^s
\]

- \(u_b^g\)：合同保证部分；
- \(u_b^s\)：在线能力提供的可撤销surplus。

## 2. 场景树

### Stage 0
当前动作必须对所有场景共同：

\[
u_{0}^{g,(s)}=u_0^g,\quad
u_{0}^{s,(s)}=u_0^s.
\]

### Delivered branch
surplus按照在线模型集合交付。

### Loss branch
surplus为0、部分交付或额外延迟；下一周期起SG和慢速备用可使用branch-specific recourse。

## 3. 约束

所有分支：
- frequency；
-ACE；
-tie；
-SG power/ramp；
-BESS contract power/ramp；
-SoC energy；
-delay pipeline；
-terminal或bridge；
-slow reserve。

在线surplus不得用于缩小合同硬安全集合，除非它在loss branch中也不需要交付。

## 4. 目标

最坏情景epigraph：

\[
\min t+\rho_\epsilon\|\epsilon\|_1+\rho_u\|u\|^2
\]

\[
J_s\le t,\quad\forall s.
\]

可加入期望性能作为次级目标，但必须先最小化最坏风险。

## 5. Feasibility restoration

只允许放松frequency/ACE/tie性能目标，不放松资源硬约束。

## 6. Bridge和slow reserve

-remaining time逐周期递减；
-slow reserve有状态、ramp和capacity；
-energy用actual predicted power；
-handoff后进入sustainable terminal。

## 7. Contract violation

不声称同瞬间保证。触发：
- SG emergency；
-slow reserve；
-可选load shedding（若注册）；
-单独结果。

## 8. 实现要求

-真正滚动；
-完整时域；
-actual action commit；
-all attempted calls logged；
-DPP/稀疏QP；
-2s/4s实时。
