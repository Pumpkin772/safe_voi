# 模型、观测器与终端集合重建规范

## 1. Plant A

保留标幺频率模型：

\[
2H_i\dot\omega_i
=
p_{m,i}+p_{b,i}-d_i-s_ip_{12}-D_i\omega_i.
\]

必须：
- actual BESS power进入摆动功率平衡；
- SG valve/GRC/pm边界一致；
- PFR+SFR共享BESS功率/ramp/energy；
- delay只在一个公共物理通道实现；
- 2s/4s；
- dt收敛；
- energy守恒。

## 2. Plant B

使用原生 ANDES Kundur/IEEE39：
- 真实网络、机组、调速器；
- BESS母线注入；
-相同能力事件和控制周期；
-保存初始化警告；
-对照COI频率、tie、pm和BESS power。

## 3. Reduced-order disturbance observer

将实际测得的：
\[
p_b^{actual}
\]
作为已知输入。

推荐状态：
\[
x_g=[\omega_1,\omega_2,p_{12},p_{v1},p_{v2},p_{m1},p_{m2}].
\]

负荷增广：
\[
d_{k+1}=d_k+\nu_k.
\]

禁止由 issued command 推断实际 BESS power 后再估负荷。

## 4. Capability set

能力集合：
\[
\mathcal C_k=
[P^+,P^-,R^+,R^-,\mathcal D,E_{\rm avail},a].
\]

- power/ramp由命令和actual power约束；
- delay由因果command-output cross-correlation/模型集合更新；
- energy由SoC和效率传播；
- 无充分激励时集合不得虚假收缩；
- true capability只用于评价。

## 5. 负荷依赖平衡点

对可持续域：
\[
x^\star=x^\star(\hat d,p_{12}^\star).
\]

终端误差：
\[
e=x-x^\star(\hat d).
\]

负荷误差：
\[
\tilde d=d-\hat d,\quad
\tilde d_{k+1}=\tilde d_k+\nu_k.
\]

不得将 \(\tilde d\) 作为每周期独立新事故。

## 6. Terminal window

必须同时满足：
- sustainable；
-距事件≥完整horizon；
- \(\|e\|\) 在候选邻域；
- valve/pm不在边界；
- GRC inactive；
- BESS power/ramp/energy inactive；
- command未饱和；
- observer warm；
- no solver/fallback；
- no future data。

保存：
```text
included
primary_exclusion_reason
all_exclusion_reasons
```

## 7. 统计集合

优先使用 split conformal 或 finite-sample confidence lower bound。

经验覆盖必须注明：
- split；
- n；
- period；
- Plant；
- horizon；
- point estimate；
- confidence lower bound。
