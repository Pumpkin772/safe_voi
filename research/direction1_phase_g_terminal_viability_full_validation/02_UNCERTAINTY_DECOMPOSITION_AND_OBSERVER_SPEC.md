# 不确定性分解、观测器与终端局部集合规范

## 1. 禁止的旧做法

不得把以下事件混在一个axis-aligned residual box中，并假定每个周期独立重复：

- 大负荷阶跃；
- 能力跳变；
- estimator initialization transient；
- 饱和/GRC切换；
- measurement noise；
- delay interpolation；
- state observer error。

## 2. 因果观测器

对 Plant A 线性局部模型构造增广状态：

\[
\chi_k=[x_k^\top,d_k^\top]^\top,
\qquad d_{k+1}=d_k+\nu_k
\]

使用公共测量：频率、tie、SG机械功率、BESS实际功率、历史已执行命令。可采用Kalman、set-membership observer或zonotope observer，但必须：

- 完全因果；
- 不把未观测阀门状态直接等同于机械状态；
- 输出状态误差/负荷误差集合；
- 在Plant A truth上独立验证。

## 3. 全局预测集合

用于MPC stage prediction，包含：

\[
\mathcal W_{pred}
=
\mathcal W_{obs}
\oplus
\mathcal W_{load}
\oplus
\mathcal W_{model}
\oplus
\mathcal W_{delay}.
\]

其中负荷误差应通过 \(d-\hat d\) 或 \(\Delta d\) 结构进入，不允许作为任意九维state kick。

## 4. 本地终端集合

仅使用满足以下条件的development窗口：

- 距离新负荷/能力事件至少一个完整prediction horizon；
- state位于候选terminal neighborhood；
- 无执行器饱和、无GRC切换；
- observer完成warm-up；
- 无solver/fallback异常。

得到：

\[
\mathcal W_{term}\subset\mathcal W_{pred}.
\]

必须保存窗口标签和排除原因。

## 5. 经验与确定性边界

- 功率、爬坡、能量、服务delay合同可作为确定性注册边界；
- 从残差分位数得到的误差只能称为经验覆盖/高置信集合；
- 若使用conformal或有限样本覆盖，必须声明统计假设；
- 不得把97%经验覆盖写成“所有扰动鲁棒”。

## 6. Gate

- validation joint coverage≥95%；
- local terminal set不会在一步上必然突破所有terminal limits；
- no future leakage；
- coverage按Plant A/B、2/4s分开报告；
- OOD不用于集合校准。
