# 模型和估计器重建

## 1. 负荷观测器

实际BESS POI power作为已知输入。

至少比较：
- augmented Kalman；
- unknown-input observer；
- constrained MHE。

development选择，validation固定。

## 2. Set-membership deliverability model

对每个区域：

\[
p_{k+1}=a p_k+b u_{k-d}+e_k,
\quad |e_k|\le\epsilon.
\]

delay candidate：
\[
d\in\mathcal D_k.
\]

在滑动窗口中求：
\[
\Theta_k(d)
=
\{(a,b):\text{全部历史约束满足}\}.
\]

由可行模型集合推导：
- one-step delivered-power interval；
- ramp interval；
- delay set；
- excitation status；
- feasible-set emptiness；
- model residual coverage。

不得把历史最大值直接称为未来能力保证。

## 3. 合同与在线集合

### Contract
硬安全。

### Online
性能分配和surplus branch。

### Contract violation
若测量与任何满足contract的模型都不相容，进入contract violation detector。

## 4. Energy

由测量SoC直接更新，不由黑箱估计器推断。

## 5. Continuous delay

-有限顶点；
-稠密grid验证；
-插值误差加入model-error set。

## 6. 输出与测试

必须输出：
- parameter/model feasible sets；
- coverage；
-false optimism；
-delay coverage；
-no-excitation；
-abrupt drop；
-slow drift；
-load/capability confusion；
-contract violation delay；
-no truth/future leakage。
