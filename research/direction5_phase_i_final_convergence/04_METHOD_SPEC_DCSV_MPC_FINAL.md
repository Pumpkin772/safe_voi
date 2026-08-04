# 最终DCSV-MPC规范

## 1. 输入
- causal state/load estimate；
- actual previous action；
- measured BESS power；
- measured energy/SoC；
- contract capability；
- online deliverability set；
- delay set；
- slow reserve state。

## 2. 安全与性能分离

硬约束只使用：
\[
\mathcal C_{\rm contract}.
\]

在线额外能力仅进入：
-参考分配；
-性能soft envelope；
-可撤销的surplus use。

## 3. 能量状态

\[
E_{k+1}
=
E_k-\frac{T_sS_B}{3600}
(P_k^+/\eta_d-\eta_cP_k^-).
\]

同时约束上、下界。充电不能被计为正的“已使用能量”。

## 4. 延迟
- finite candidate set或verified outer polytope；
-所有顶点共享控制序列；
-稠密delay grid验证；
-完整actual-action pipeline。

## 5. 全时域滚动
禁止：
-只运行8个更新后held tail；
-插入人工零normal rows；
-使用truth决定普通控制动作。

## 6. Bridge
- time-to-handoff逐周期递减；
- slow reserve有动态；
- bridge energy与实际执行功率一致；
- handoff后进入sustainable控制。

## 7. Restoration
只允许放松frequency/ACE performance envelope。
不得放松设备power/ramp/energy和delay causality。

## 8. Diagnostics
每周期输出：
- solver status/residual；
- scenario/vertex count；
- hard margin；
- energy margin；
- fallback/restoration；
- actual/model action history；
- domain；
- contract violation；
- solve time。
