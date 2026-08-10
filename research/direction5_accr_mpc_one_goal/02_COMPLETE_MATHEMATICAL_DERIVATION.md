# ACCR-MPC完整数学推导

## 1. 连续时间两区域模型

对区域 \(i\in\{1,2\}\)，令：
- \(\omega_i=\Delta f_i/f_0\)；
- \(p_{m,i}\)：同步机机械功率增量；
- \(p_{b,i}\)：IBR/BESS实际POI有功增量；
- \(p_{r,i}\)：慢速备用；
- \(d_i\)：净负荷增量；
- \(p_{12}\)：区域1流向区域2的联络线增量；
- \(s_1=1,s_2=-1\)。

摆动方程：

\[
2H_i\dot\omega_i
=
p_{m,i}+p_{b,i}+p_{r,i}
-d_i-D_i\omega_i-s_ip_{12}.
\tag{1}
\]

联络线：

\[
\dot p_{12}
=
2\pi f_0T_{12}(\omega_1-\omega_2).
\tag{2}
\]

ACE：

\[
ACE_1=B_1f_0\omega_1+p_{12},
\tag{3a}
\]

\[
ACE_2=B_2f_0\omega_2-p_{12}.
\tag{3b}
\]

同步机：

\[
T_{g,i}\dot p_{v,i}
=
-p_{v,i}-R_i^{-1}\omega_i+u_{g,i}+u_{aw,i},
\tag{4}
\]

\[
\dot p_{m,i}
=
\operatorname{sat}_{[-G_i^-,G_i^+]}
\left(
\frac{p_{v,i}-p_{m,i}}{T_{t,i}}
\right).
\tag{5}
\]

anti-windup项可写为：

\[
u_{aw,i}
=
K_{aw,i}(p_{v,i}^{\mathrm{sat}}-p_{v,i}).
\tag{6}
\]

慢速备用：

\[
T_{r,i}\dot p_{r,i}
=
-p_{r,i}
+
\operatorname{sat}_{[-P_{r,i}^-,P_{r,i}^+]}(u_{r,i}),
\tag{7}
\]

并施加：

\[
-G_{r,i}^-
\le \dot p_{r,i}
\le G_{r,i}^+.
\tag{8}
\]

## 2. BESS本地PFR与SFR

固定本地PFR：

\[
p_{\mathrm{PFR},i}
=
-K_{e,i}\Delta f_i.
\tag{9}
\]

上层SFR命令：

\[
u_{b,i}.
\tag{10}
\]

总目标：

\[
r_{b,i}
=
p_{\mathrm{PFR},i}+u_{b,i}.
\tag{11}
\]

能量符号约定：\(p_b>0\)表示向电网放电。引入：

\[
p_b=p_b^+-p_b^-,
\quad
p_b^+,p_b^-\ge0.
\tag{12}
\]

能量：

\[
E_{i,k+1}
=
E_{i,k}
-
\frac{T_sS_B}{3600}
\left(
\frac{p_{b,i,k}^+}{\eta_{d,i}}
-
\eta_{c,i}p_{b,i,k}^-
\right).
\tag{13}
\]

\[
E_i^{\min}\le E_{i,k}\le E_i^{\max}.
\tag{14}
\]

## 3. 黑箱执行器候选模型

在上层采样时刻，候选模型 \(h\) 定义为：

\[
h=(a,b,d,P^+,P^-,R^+,R^-).
\tag{15}
\]

模型：

\[
\bar p_{k+1}^{h}
=
a p_k
+
b r_{k-d}.
\tag{16}
\]

功率投影：

\[
\tilde p_{k+1}^{h}
=
\Pi_{[-P^-,P^+]}
(\bar p_{k+1}^{h}).
\tag{17}
\]

爬坡投影：

\[
F_h(p_k,r_{k-d})
=
\Pi_{[p_k-T_sR^-,\,p_k+T_sR^+]}
(\tilde p_{k+1}^{h}).
\tag{18}
\]

真实测量：

\[
p_{k+1}
=
F_{h^\star}(p_k,r_{k-d^\star})
+
e_k,
\qquad
|e_k|\le\epsilon.
\tag{19}
\]

## 4. 因果可行模型集合

初始候选集合：

\[
\mathcal H_0
=
\mathcal A\times\mathcal B\times\mathcal D
\times\mathcal P^\pm\times\mathcal R^\pm.
\tag{20}
\]

新测量到达后：

\[
\mathcal H_{k+1}
=
\left\{
h\in\mathcal H_k:
|p_{k+1}-F_h(p_k,r_{k-d})|
\le\epsilon
\right\}.
\tag{21}
\]

若能力可能变化，使用滑动窗口：

\[
\mathcal H_{k}^{(W)}
=
\bigcap_{t=k-W}^{k-1}
\left\{
h:
|p_{t+1}-F_h(p_t,r_{t-d})|
\le\epsilon
\right\}.
\tag{22}
\]

当集合为空时，触发change reset，但不得把旧能力作为新安全下界。

## 5. 合同与认证能力

合同集合：

\[
\mathcal C^c
=
\{P_c^\pm,R_c^\pm,\mathcal D_c\}.
\tag{23}
\]

认证下界：

\[
\underline P_k^+
=
\min_{h\in\mathcal H_k}P_h^+,
\quad
\underline P_k^-
=
\min_{h\in\mathcal H_k}P_h^-,
\tag{24}
\]

\[
\underline R_k^\pm
=
\min_{h\in\mathcal H_k}R_h^\pm.
\tag{25}
\]

认证剩余能力：

\[
S_{P,k}^\pm
=
\left(
\underline P_k^\pm-P_c^\pm
\right)_+,
\tag{26}
\]

\[
S_{R,k}^\pm
=
\left(
\underline R_k^\pm-R_c^\pm
\right)_+.
\tag{27}
\]

证书有效期：

\[
t\in[t_k^{\mathrm{cert}},t_k^{\mathrm{cert}}+T_{\mathrm{cert}}],
\tag{28}
\]

且任何残差违约立即撤销：

\[
|p_{k+1}-F_h(\cdot)|>\epsilon
\Rightarrow
S_{P,k+1}=S_{R,k+1}=0.
\tag{29}
\]

## 6. 区域总SFR与分配中性探测

令区域虚拟SFR总命令为：

\[
v_i=u_{g,i}^{0}+u_{b,i}^{0}.
\tag{30}
\]

探测信号 \(q_i\) 重新分配：

\[
u_{g,i}=u_{g,i}^{0}-q_i,
\tag{31}
\]

\[
u_{b,i}=u_{b,i}^{0}+q_i.
\tag{32}
\]

因此命令层面：

\[
u_{g,i}+u_{b,i}=v_i.
\tag{33}
\]

矩阵形式：

\[
\begin{bmatrix}1&1\end{bmatrix}
\begin{bmatrix}-q_i\\q_i\end{bmatrix}=0.
\tag{34}
\]

这称为**分配中性**，不声称实际动态功率严格为零。

实际净探测影响：

\[
\Delta p_i^{h}
=
G_{b,i}^{h}(q_i)-G_{g,i}(q_i).
\tag{35}
\]

它必须进入鲁棒频率预测。

## 7. 探测序列约束

对长度 \(L_p\) 的探测：

\[
\sum_{\ell=0}^{L_p-1}q_{i,\ell}=0,
\tag{36}
\]

\[
|q_{i,\ell}|\le q_i^{\max},
\tag{37}
\]

\[
|q_{i,\ell+1}-q_{i,\ell}|
\le \Delta q_i^{\max}.
\tag{38}
\]

还必须满足SG和BESS合同功率、爬坡、能量及ACE约束。

## 8. 信息指标

对候选 \(h,h'\) 和探测 \(q\)，预测输出轨迹：

\[
Y_h(q)
=
[p_{1|k}^{h},\ldots,p_{L_p|k}^{h}]^\top.
\tag{39}
\]

加权分离：

\[
D_{h,h'}(q)
=
\|Y_h(q)-Y_{h'}(q)\|_{W_y}^2.
\tag{40}
\]

最坏候选分离：

\[
\mathcal I(q)
=
\min_{h\not\sim h'}
D_{h,h'}(q),
\tag{41}
\]

其中 \(h\sim h'\) 表示二者具有相同控制相关认证能力。

也可定义回归Gramian：

\[
G(q)
=
\lambda I
+
\sum_{\ell=0}^{L_p-1}
\phi_\ell(q)\phi_\ell(q)^\top,
\tag{42}
\]

\[
\mathcal I_{\log\det}(q)
=
\log\det G(q)-\log\det G(0).
\tag{43}
\]

## 9. 探测代价

相对无探测轨迹：

\[
C_{\mathrm{probe}}(q)
=
\max_{h\in\mathcal H_k}
\sum_{\ell=1}^{L_p}
\left[
\|x_{\ell|k}^{h,q}
-x_{\ell|k}^{h,0}\|_{Q_p}^2
+
\|q_\ell\|_{R_p}^2
\right].
\tag{44}
\]

## 10. 安全探测优化

从有限库 \(\mathcal Q\) 或连续集合中选择：

\[
q^\star
=
\arg\max_{q\in\mathcal Q}
\left[
\mathcal I(q)
-\lambda_pC_{\mathrm{probe}}(q)
\right].
\tag{45}
\]

约束对所有候选和“不交付”分支成立：

\[
x_{\ell|k}^{h,q}\in\mathcal X_{\mathrm{safe}},
\quad
\forall h\in\mathcal H_k,
\tag{46}
\]

\[
u_{\ell|k}^{h,q}\in\mathcal U_{\mathrm{physical}},
\tag{47}
\]

\[
E_{\ell|k}^{h,q}\in[E^{\min},E^{\max}],
\tag{48}
\]

\[
|\Delta f_i|\le\bar f,
\quad
|ACE_i|\le\overline{ACE},
\quad
|p_{12}|\le\bar p_{12}.
\tag{49}
\]

仅当：

\[
\mathcal I(q^\star)\ge I_{\min},
\quad
C_{\mathrm{probe}}(q^\star)\le C_{\max}
\tag{50}
\]

时执行。

## 11. 事件触发

定义模型集合宽度：

\[
W_k
=
\operatorname{diam}(\mathcal H_k).
\tag{51}
\]

触发条件：

\[
\mathrm{Trigger}_k
=
\mathbf1
\{
W_k>W_{\max}
\ \lor\
T_{\mathrm{cert}}\text{过期}
\ \lor\
r_k>r_{\max}
\}
\tag{52}
\]

并且：

\[
x_k\in\mathcal X_{\mathrm{probe}},
\tag{53}
\]

\[
\text{SG/BESS headroom充足}.
\tag{54}
\]

## 12. ACCR-MPC控制问题

### 12.1 状态与场景

对每个候选 \(h\)、延迟和能力交付场景 \(s\)：

\[
x_{j+1|k}^{s}
=
A_sx_{j|k}^{s}
+
B_su_{j|k}^{s}
+
E_s\hat d_k
+
w_{j|k}^{s}.
\tag{55}
\]

当前动作非预见：

\[
u_{0|k}^{s}=u_{0|k},
\quad
\forall s.
\tag{56}
\]

未来可允许SG/慢速备用追索：

\[
u_{g,j|k}^{s},
u_{r,j|k}^{s},
\quad j\ge1.
\tag{57}
\]

### 12.2 合同与认证分量

\[
u_{b,j}
=
u_{b,j}^{c}
+
u_{b,j}^{\mathrm{cert}}
+
q_j.
\tag{58}
\]

合同分量在所有场景交付：

\[
|u_{b,j}^{c}|
\le P_c.
\tag{59}
\]

认证分量满足：

\[
|u_{b,j}^{\mathrm{cert}}|
\le S_{P,k},
\tag{60}
\]

并考虑“认证能力正常”和“认证能力突然丢失”两类分支。

### 12.3 最坏情景目标

\[
J_s
=
\sum_{j=0}^{N-1}
\left(
\|f_j^s\|_{Q_f}^2
+
\|ACE_j^s\|_{Q_a}^2
+
\|p_{12,j}^s\|_{Q_t}^2
+
\|u_j^s\|_{R}^2
\right)
+
V_f(x_N^s).
\tag{61}
\]

引入：

\[
J_s\le t,\quad\forall s.
\tag{62}
\]

优化：

\[
\min
t
+
\lambda_{\mathrm{probe}}C_{\mathrm{probe}}(q)
+
\rho_\epsilon\|\epsilon\|_1.
\tag{63}
\]

资源硬约束无slack，性能目标可有限slack恢复。

## 13. 信息价值回收率

对于指标 \(J\)，合同、Oracle和ACCR分别为：

\[
J_c,\quad J_o,\quad J_a.
\tag{64}
\]

当 \(J_c>J_o\) 时，定义：

\[
\rho_J
=
\frac{J_c-J_a}{J_c-J_o}.
\tag{65}
\]

\[
\rho_J=0
\]
表示没有回收完美信息价值，

\[
\rho_J=1
\]
表示达到Oracle。

## 14. 定理1：分配命令中性

由式(31)–(33)直接得：

\[
\Delta u_g+\Delta u_b=0.
\]

因此探测不改变调度层区域总SFR命令。实际动态影响由式(35)约束。

## 15. 定理2：可行集合包含性

假设真实 \(h^\star\in\mathcal H_0\)，且所有测量误差满足式(19)。由集合交递推式(21)可知：

\[
h^\star\in\mathcal H_k,\quad\forall k
\]

直到真实能力发生变化或误差界被违反。

## 16. 定理3：安全探测

若探测优化式(45)–(49)可行，并且真实模型属于候选集合，误差属于注册集合，则执行 \(q^\star\) 的预测时域内：

- 频率/ACE/tie约束满足；
- SG/BESS功率、爬坡和能量约束满足。

该定理是条件性有限时域结果。

## 17. 定理4：有限可区分性

若存在探测 \(q\)，使任意两个不同控制能力类的输出集合间距离满足：

\[
\operatorname{dist}
(\mathcal Y_h(q),\mathcal Y_{h'}(q))
>
2\epsilon_y,
\tag{66}
\]

则一次探测窗口结束后，集合成员更新不能同时保留这两个能力类。

## 18. 定理5：证书与能力突降边界

若能力在证书有效期内保持不变且真实模型始终属于可行集合，则式(24)–(27)给出的认证下界有效。

若能力无预警突降，则同瞬间不能保证依赖旧认证剩余能力的命令可执行；控制器必须通过loss branch和下一周期追索处理。

## 19. 定理6：条件性递归可行

若：
1. 合同MPC具有非空鲁棒终端集；
2. 每个探测候选通过安全门；
3. 下一周期loss branch存在可行追索；
4. 实际动作历史正确提交；
5. 误差和延迟属于注册集合；

则从认证可行域内，ACCR-MPC保持条件性递归可行。

若无法完成全部证明，论文必须收缩为：
- 有限时域安全探测；
- 合同分支局部递归；
- 经验追索验证。
