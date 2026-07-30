# CRCS-TMPC 完整方法规范

## 1. 方法概览

CRCS-TMPC不是模式分类器外接MPC，而是一体化的：

1. 因果状态/未知负荷估计；
2. 黑箱IBR外部动态与能力集合更新；
3. 延迟和能力不确定下的管束MPC；
4. 终端SG备份和责任平滑转移。

唯一推断对象是控制相关能力集合，不要求恢复真实模式标签。

## 2. 因果状态和未知负荷估计

采用所有部署方法共享的增强状态估计器：

\[
x_{k+1}=Ax_k+Bu_k+Gd_k+w_k,
\]

\[
d_{k+1}=d_k+\nu_k,
\]

\[
y_k=Cx_k+v_k,
\]

其中 \(d_k\) 为未知净负荷。可实现为增强Kalman滤波或约束MHE，但全方法必须共享同一估计器，禁止用无噪声差分直接恢复真负荷。

估计输出：

\[
\hat x_k,\quad \hat d_k,\quad \mathcal W_k,
\]

其中 \(\mathcal W_k\) 是估计误差集合。

## 3. 因果变化检测

对每个候选延迟/动态集合计算一步预测残差：

\[
r_k=y_k-\hat y_{k|k-1},
\]

\[
z_k=r_k^\top S_k^{-1}r_k.
\]

使用单边递推CUSUM/GLR：

\[
g_k=\max(0,g_{k-1}+z_k-\nu),
\]

\[
g_k>h\Rightarrow \text{change alarm}.
\]

- 所有窗口只能使用 \(0{:}k\) 数据；
- 不得使用 `mode='same'` 中心卷积；
- 不得使用报警后的未来数据分类；
- 不需要输出headroom/ramp/delay标签。

报警后执行能力集合扩张/重置，而不是硬切换模式。

## 4. 外部动态参数集合更新

对于每个候选延迟 \(d\in\mathcal D_k\)：

\[
\Theta_{k+1}^{(d)}=\Theta_k^{(d)}\cap
\{\theta:|p_{b,k+1}-\phi_k^{(d)\top}\theta|\le\epsilon_k\}.
\]

无报警时采用交集收缩；报警时：

\[
\Theta_{k+1}^{(d)}=\Theta_{\mathrm{global}}^{(d)}\cap
\mathbb B(\hat\theta_k,\rho_{\mathrm{reset}}).
\]

若所有候选集合为空，则：

- 标记模型失配；
- 使用全局物理能力集合；
- 调用SG安全备份；
- 不得伪造一个标签。

## 5. 功率、爬坡、延迟和能量能力集合

维护：

\[
\mathcal C_k=
[P_k^{+,L},P_k^{+,U}]
\times[P_k^{-,L},P_k^{-,U}]
\times[R_k^{+,L},R_k^{+,U}]
\times[R_k^{-,L},R_k^{-,U}]
\times\mathcal D_k
\times[E_k^L,E_k^U].
\]

功率和爬坡边界由实际命令/输出的集合一致性更新；能量区间根据POI功率、效率边界和初始SoC区间传播；禁止读取真SoC。

## 6. 不确定延迟增强模型

对每个 \(d\in\mathcal D_k\) 建立命令队列状态：

\[
q_{k+1}=egin{bmatrix}u_k&q_{k,1}&\cdots&q_{k,d_{\max}-1}\end{bmatrix}^\top,
\]

并构造顶点模型：

\[
x_{k+1}=A_jx_k+B_ju_k+E_jw_k,
\quad j\in\mathcal V(\Theta_k,\mathcal C_k,\mathcal D_k).
\]

顶点数过大时使用支持函数/约束生成，不允许随意只选均值模型。

## 7. 管束MPC

名义系统：

\[
\bar x_{i+1|k}=A_0\bar x_{i|k}+B_0v_{i|k}.
\]

实际控制：

\[
u_{i|k}=v_{i|k}+K(x_{i|k}-\bar x_{i|k}).
\]

误差管束：

\[
e_{i+1}\in(A_j+B_jK)e_i\oplus\mathcal W_k\oplus\mathcal M_k,
\]

其中 \(\mathcal M_k\) 是模型/能力不确定误差集合。计算鲁棒正不变集 \(\mathcal Z_k\)。

约束收紧：

\[
\bar x_{i|k}\in\mathcal X\ominus\mathcal Z_k,
\]

\[
v_{i|k}\in\mathcal U(\mathcal C_k)\ominus K\mathcal Z_k.
\]

目标：

\[
\min \sum_{i=0}^{N-1}
\left(
\|ACE_{i|k}\|_{Q_a}^2+
\|p_{12,i|k}\|_{Q_t}^2+
\|\Delta f_{i|k}\|_{Q_f}^2+
\|v_{i|k}\|_R^2+
\|\Delta v_{i|k}\|_{R_\Delta}^2
\right)+\|x_{N|k}\|_P^2.
\]

必须显式控制：

- SG备用和GRC；
- BESS总PFR+SFR功率；
- BESS爬坡、能量和电流；
- 频率、ACE与联络线；
- 延迟候选；
- 终端备用。

## 8. 终端备份与递归可行

设计SG-only局部备份：

\[
u=K_fx,
\]

计算终端鲁棒控制不变集 \(\mathcal X_f\)，满足：

\[
(A_j+B_jK_f)\mathcal X_f\oplus\mathcal W\subseteq\mathcal X_f,
\]

对所有声明顶点成立，并满足SG备用/GRC约束。

MPC不可行、估计无效或能力集合为空时，平滑过渡到备份；不得直接不连续撤回产生二次扰动。

## 9. 真正基线

每个名称必须与实现一致：

1. `sg_only_ace_pi`：只用SG的ACE PI；
2. `fixed_allocation_pi`：固定SG/IBR比例；
3. `nominal_linear_mpc`：固定nominal模型的真实滚动MPC；
4. `rls_adaptive_mpc`：真正RLS参数更新+滚动MPC；
5. `worst_case_tube_mpc`：固定全局能力集合的真实管束MPC；
6. `crcs_tube_mpc`：本文方法；
7. `current_capability_nmpc_oracle`：evaluation-only滚动NMPC。

禁止仅用代数规则冒充MPC。

## 10. 计算预算

- Plant A：控制周期2/4 s，预测时域32–60 s；
- Plant B：可使用降阶预测器，但plant rollout必须为原生RMS/DAE；
- QP/SOCP优先；
- 开发阶段允许离线多面体计算；
- P99在线时间必须小于控制周期一半；
- 所有求解失败必须记录并调用备份。
