# CDSR-MPC 数学与实现规范

## 1. 方法定位

**CDSR-MPC**：

> Capability-and-Delay-Set Robust Model Predictive Control with Feasibility Restoration

该方法不识别内部模式，也不使用真能力标签。它只使用：

- 公共状态/输出估计；
- 历史已执行命令；
- 因果负荷估计；
- 预注册的IBR保证能力包络；
- 有界执行延迟集合；
- 由development残差校准的模型误差集合。

## 2. 增广状态

Plant A预测状态：

\[
x_k =
[\omega_1,\omega_2,p_{12},p_{v1},p_{v2},p_{m1},p_{m2},p_{b1},p_{b2}]^\top.
\]

为表示延迟和能量：

\[
z_k =
[x_k^\top,u_{k-1}^\top,E_{b1,k},E_{b2,k}]^\top.
\]

若最大延迟跨越多个控制周期，则继续加入完整command pipeline，不得截断。

## 3. 延迟集合

\[
\mathcal D=\{\tau_1,\ldots,\tau_Q\}.
\]

每个顶点：

\[
z_{i+1|k}^{(q)}
=
\bar A_qz_{i|k}^{(q)}
+
\bar B_qv_{i|k}
+
\bar E_q\hat d_k
+
w_{i|k}^{(q)}.
\]

同一控制序列必须用于全部顶点：

\[
v_{i|k}^{(1)}=\cdots=v_{i|k}^{(Q)}.
\]

## 4. 保证能力包络

\[
-\underline P_b^- \le p_{b,i}^{(q)} \le \underline P_b^+
\]

\[
-T_s\underline R_b^-
\le
p_{b,i+1}^{(q)}-p_{b,i}^{(q)}
\le
T_s\underline R_b^+.
\]

能量使用充放电分裂：

\[
p_b=p_b^+-p_b^-,
\qquad p_b^+,p_b^-\ge0
\]

\[
E_{i+1}
=
E_i-\frac{T_sS_B}{3600}
\left(
\frac{p_{b,i}^+}{\eta_d}
-
\eta_cp_{b,i}^-
\right).
\]

\[
E_{\min}^{\rm guaranteed}\le E_i\le E_{\max}^{\rm guaranteed}.
\]

必须约束总 BESS 功率，包含本地PFR与上层SFR。

## 5. 性能约束

对每个延迟/能力顶点：

\[
|\Delta f_i^{(q)}|
\le
\bar f+\epsilon_{f,i}
\]

\[
|ACE_i^{(q)}|
\le
\overline{ACE}+\epsilon_{{ACE},i}
\]

\[
|p_{{tie},i}^{(q)}|
\le
\bar p_{\rm tie}+\epsilon_{{tie},i}.
\]

性能slack有高惩罚但允许用于恢复；资源物理约束无slack。

## 6. 目标函数

引入最坏情景上界 \(t\)：

\[
J_q(v)\le t,\quad\forall q
\]

\[
\min
t
+\rho_f\|\epsilon_f\|_1
+\rho_a\|\epsilon_{\rm ACE}\|_1
+\rho_t\|\epsilon_{\rm tie}\|_1
+\rho_r\sum_i\|v_i-v_i^{ref}\|_2^2.
\]

其中 \(v^{ref}\) 可由稳定ACE PI给出，但不直接执行。

## 7. 终端与备份

所有顶点必须满足：

\[
z_{N|k}^{(q)}\in\mathcal X_f^{SG}.
\]

\(\mathcal X_f^{SG}\)必须由SG-only backup闭环计算，并证明/数值验证为控制不变或鲁棒正不变集合。

## 8. 可行性恢复与fallback

顺序固定：

```text
primary CDSR QP
→ alternate numerical solver
→ lexicographic performance-slack restoration
→ SG-only backup
```

所有实际动作在最终选择后统一commit。

## 9. 明确禁止

- 读取true capability/regime；
- 用单一最坏delay冒充delay-set预测；
- 用手工disturbance radius冒充数据校准；
- 叫tube MPC但不应用ancillary反馈/不变管束；
- 把经验terminal box称为不变集；
- 用SG-only基线冒充robust MPC；
- final后调整集合、权重或阈值。
