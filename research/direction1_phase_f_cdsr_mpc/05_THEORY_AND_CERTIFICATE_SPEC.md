# 理论与证书要求

## 1. 最低可接受理论层级

至少完成：

> 对注册的线性Plant A、有限延迟顶点、保证能力包络和校准误差集合，CDSR-MPC在可行解存在时对整个预测时域满足资源硬约束和注册性能约束（含明确slack边界）。

若要声称递归可行，还必须额外证明：

1. \(\mathcal X_f^{SG}\) 非空；
2. SG backup在该集合中满足全部硬约束；
3. 对所有注册扰动，下一状态仍在集合中；
4. shift-and-append候选在下一时刻可行；
5. 实际代码的delay pipeline、actual-action commit与证明一致。

## 2. Robust backup set

对离散SG-only闭环：

\[
x_{k+1}=A_{cl}x_k+Ew_k
\]

计算 \(\mathcal X_f^{SG}\)，可采用：

- polyhedral predecessor iteration；
- zonotope；
- verified interval box；
- LMI ellipsoid。

但必须：

- 保存集合数据；
- 保存算法和容差；
- 保存每个顶点的不变性残差；
- 在独立脚本中重算。

## 3. 延迟多模型证书

对全部 \(\tau_q\)：

- 验证预测矩阵；
- 验证稠密delay grid被外包；
- 验证共同控制序列；
- 验证终端集合；
- 若只覆盖有限delay grid，声明必须限定于该grid/外包。

## 4. 求解与fallback声明

不得把“求解器返回optimal”当成数学证明。

必须区分：

- formulation feasibility；
- numerical solution quality；
- physical action availability；
- backup invariance；
- empirical Plant B performance。

## 5. 允许的收缩

如果递归可行无法证明，可将理论声明收缩为：

```text
registered-set finite-horizon robust constraint satisfaction
with a separately validated SG backup supervisor
```

但论文标题和贡献不能再写“certified recursive safety”。
