# 可持续性、终端集合与有限能量桥接规范

## 1. 负荷依赖平衡点

对于每个当前负荷估计 \(\hat d\)，先解静态功率平衡：

\[
p_{g1}^\star+p_{b1}^\star-\hat d_1-p_{12}^\star=0
\]

\[
p_{g2}^\star+p_{b2}^\star-\hat d_2+p_{12}^\star=0.
\]

终端误差定义为：

\[
e=x-x^\star(\hat d).
\]

禁止围绕与持续负荷无关的固定零平衡点构造终端集合。

## 2. 可持续域

无限时域证书要求：

\[
p_{b1}^\star=p_{b2}^\star=0
\]

即能量有限BESS不承担永久净功率。SG/tie必须在保证限制内平衡持续负荷。

定义：

\[
\mathcal D_{sus}=\{\hat d:\exists p_g^\star,p_{12}^\star\text{满足静态约束}\}.
\]

## 3. 桥接域

若当前SG备用不足但慢速接管将在 \(T_R\) 内发生，BESS可桥接：

\[
\mathcal D_{bridge}=\{\hat d:\text{在保证BESS能力和能量内可安全支撑到 }T_R\}.
\]

能量必要条件：

\[
E_{avail}\ge
\frac{S_B}{3600}
\int_0^{T_R}
\left(
\frac{[p_b]^+}{\eta_d}
+\eta_c[p_b]^-
\right)dt.
\]

若项目不建模慢速接管，只能报告固定 \(T_{bridge}\) 的有限时域生存性，不能声称递归可行。

## 4. 不可行域

若即使使用保证BESS功率、爬坡和能量也无法覆盖注册桥接时间，则该cell为物理不可行：

```text
PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY
```

不得通过放宽频率、ACE或能量标准把它变为成功。

## 5. 终端集合

可持续域中，对SG backup闭环：

\[
e_{k+1}=A_{cl,q}e_k+G_qw_k
\]

对全部delay和本地终端误差顶点计算共同RPI/RCI集合：

\[
\mathcal X_f\subseteq\bigcap_q Pre_q(\mathcal X_f).
\]

必须验证：频率、ACE、tie、SG机械/阀门、command约束。

## 6. 桥接证书

桥接域使用SG+BESS保证能力，并证明：

- 全桥接区间物理约束；
- 剩余能量非负；
- 慢速接管后进入可持续域终端集合；
- 若无慢速接管，则仅给有限时域安全。
