# Bottleneck Audit — Mathematical Definitions and Metrics

## 1. 统一性能代价

令每个 episode 的主要频率代价为：

\[
J_f=\int_0^T |\Delta f(t)|\,dt.
\]

安全指标包括：

\[
f_{\max}=\max_t|\Delta f(t)|,
\qquad
r_{\max}=\max_t|\dot f(t)|.
\]

资源使用指标包括：

\[
J_{sg}=\int_0^T|u_{sg}(t)-u_{sg}(t-\Delta t)|dt,
\]

\[
J_{ibr}=\int_0^T|u_{ibr}(t)-u_{ibr}(t-\Delta t)|dt.
\]

所有方法必须同时报告频率、安全、SG/IBR里程、求解失败和 fallback，不能只优化单一 IAE。

## 2. IBR 实质价值

对 SG capability level \(q\)，定义 exact Oracle 的 IBR 价值：

\[
V_f^{(q)}=
\frac{J_f^{B0,q}-J_f^{B5,q}}{J_f^{B0,q}},
\]

\[
V_{sg}^{(q)}=
\frac{J_{sg}^{B0,q}-J_{sg}^{B5,q}}{J_{sg}^{B0,q}}.
\]

必须给出 bootstrap 95% CI 和配对 sign-flip / Wilcoxon 检验。

若 exact Oracle 都没有实质收益，则任何黑箱自诊断算法都不可能建立强科学优势。

## 3. 受控的性能差距分解

定义：

- \(J_{B5}\)：真实非线性模型 Oracle；
- \(J_{B4}\)：真实物理模式选择的离线 ARX；
- \(J_{C2}\)：perfect belief + 当前 MPC结构；
- \(J_P\)：完整当前 SD-BMPC。

模型失配差距：

\[
G_{model}=J_{B4}-J_{B5}.
\]

诊断差距：

\[
G_{diag}=J_{P\mid\text{current MPC, current belief}}
-J_{C2}.
\]

控制设计差距：

\[
G_{ctrl}=J_{C2}-J_{B4},
\]

或通过 C0–C5 的受控消融进一步分解。

这些差距不是严格代数恒等式，必须在相同控制器结构和相同输入约束下构造 counterfactual，避免混淆不同架构。

## 4. 模型充分性

对真实模式 \(m\) 和预测 horizon \(h\)：

\[
E_{p,m}(h)=
\sqrt{\frac{1}{N}\sum_k
\left(p_{b,k+h}-\hat p_{b,k+h|k}^{(m)}\right)^2}.
\]

频率传播误差：

\[
E_{f,m}(h)=
\sqrt{\frac{1}{N}\sum_k
\left(\Delta f_{k+h}-\widehat{\Delta f}_{k+h|k}^{(m)}\right)^2}.
\]

同时记录 q95、最大误差和约束激活条件下的条件误差。

## 5. 被动可辨识性

窗口回归 Gramian：

\[
G_k(L)=\sum_{i=k-L+1}^{k}\phi_i\phi_i^\top.
\]

记录：

\[
\lambda_{min}(G_k),
\qquad
\kappa(G_k).
\]

模式 \(m,n\) 的窗口对数似然间隔：

\[
\Delta\mathcal L_{m,n}(k,L)=
\sum_{i=k-L+1}^{k}
\left[\ell_m(i)-\ell_n(i)\right].
\]

可区分时间定义为：

\[
T_{id}^{m\to n}=
\inf\left\{t\ge t_{sw}: P(m_t=n\mid y_{0:t})\ge0.8
\text{并持续 }3\text{步}\right\}-t_{sw}.
\]

若在频率控制最关键的前 5–10 s 内缺乏可区分信息，则必须明确报告“被动诊断不可用”，不能通过延长观察窗口掩盖控制时限。

## 6. 负荷变化与设备变化的混淆

构造配对事件：

- 纯负荷阶跃；
- 纯 IBR 模式变化；
- 二者同时发生。

定义来源分类混淆矩阵，并报告：

- false mode alarm under load event；
- missed mode change under small load；
- detection delay under coincident event。

## 7. 控制保守性

定义 IBR authority ratio：

\[
a_k=
\frac{|u_{ibr,k}^{allowed}|}
{|u_{ibr}^{physical,max}|}\in[0,1].
\]

记录：

- belief entropy 与 \(a_k\) 的关系；
- OOD状态与 \(a_k\) 的关系；
- full fallback 持续时间；
- 因 worst-mode term 造成的首个动作偏差；
- 相对 B5/B2 的 under-use 与 over-use。

## 8. 统计规范

- 所有比较必须按 `scenario_id + seed + SG_level` 配对；
- 95% bootstrap CI；
- 多重比较使用 Holm 校正；
- 失败、timeout、不可行、censored episode 全部保留；
- 不允许把缺失值填零；
- 总体结果和场景分层结果必须同时报告。
