# 模型与估计器重建规范

## Plant A
必须使用非线性物理step，保存：
- frequency；
- tie；
- valve；
- mechanical；
- BESS actual power；
- SoC/energy；
- PFR/SFR commands；
- slow reserve；
- saturation/GRC flags。

## Plant B
原生ANDES闭环，不允许用“reduced model + Gaussian noise”替代final。

## Load observer
使用actual BESS POI power作为已知输入：

\[
d_i
=
p_{m,i}+p_{b,i}^{actual}-D_i\omega_i-s_ip_{tie}
-2H_i\dot\omega_i.
\]

允许Kalman/UIO/MHE，但必须：
-因果；
-有噪声模型；
-不读取true load；
-报告2s/4s condition和误差。

## Deliverability estimator
使用滑动窗口：
\[
p_{k+1}=ap_k+bu_{k-d}+e_k
\]
并联合power/ramp约束。

输出：
- feasible model/parameter set；
- delay candidate set；
- observed performance envelope；
- contract violation state。

禁止：
-用历史最大出力直接称为未来保证下界；
-用已消耗能量称为剩余能量；
-availability永远返回[0,1]却声称已估计；
-在无激励时虚假收缩。

## Full-event protocol
每个能力实验：
```text
nominal pre-event >= 60 s
capability change time randomized
load event independently timed
full closed-loop 300–600 s
```

normal profile必须真实仿真。
