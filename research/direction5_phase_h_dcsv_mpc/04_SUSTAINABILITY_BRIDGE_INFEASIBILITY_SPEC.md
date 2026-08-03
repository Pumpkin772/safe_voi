# 可持续域、桥接域与物理不可行域

## 1. 可持续域

存在长期平衡：

\[
p_{g1}^\star-d_1-p_{12}^\star=0,
\quad
p_{g2}^\star-d_2+p_{12}^\star=0
\]

且长期BESS净能量不耗尽。

默认长期：
\[
p_b^\star=0.
\]

若允许非零BESS稳态，必须有持续能源来源，不得默认为电池无限供能。

## 2. 桥接域

SG当前不足，但慢速备用在 \(T_R\) 内接管。

必须满足：
\[
|p_b|\le P^{guaranteed},
\quad
|\dot p_b|\le R^{guaranteed},
\]

\[
\int_0^{T_R}
\left(
[p_b]^+/\eta_d+\eta_c[p_b]^-
\right)dt
\le E_{\rm avail}.
\]

若无慢速接管模型，只允许报告：
\[
[0,T_{\rm bridge}]
\]
内的有限时域可生存性。

## 3. 物理不可行域

若在注册资源能力下：
- steady-state power不足；
- ramp不足；
- energy不足；
- tie限制不足；
- SG reserve不足；

则提前标记：
```text
PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY
```

不得把该类episode计作MPC算法失败。

## 4. 分类顺序

分类必须在：
- terminal calibration；
- controller design；
- final simulation

之前完成，并锁定manifest hash。
