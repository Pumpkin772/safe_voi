# 控制相关 Regime 与可辨识性规范

## 1. 为什么不能直接恢复物理标签

黑箱 IBR 的两个内部状态可能具有不同物理标签，但对未来频率预测、最优动作和可行功率集合影响接近；反之，一个物理模式在不同 SoC/头寸下可能对应多个控制行为。

因此模型库应围绕 control-relevant regime 建立。

## 2. 控制相关距离

对状态/模式 a,b，在同一初始条件与候选输入集合上定义：

`d_pred(a,b) = E_U ||Y_a(U)-Y_b(U)||_W²`

`d_act(a,b) = E_x ||u_a*(x)-u_b*(x)||_R²`

`d_cap(a,b) = Hausdorff(U_feas,a, U_feas,b)`

`d_ctrl(a,b) = α d_pred + β d_act + γ d_cap`

如果 `d_ctrl < ε_merge`，允许合并为同一 control-relevant regime。

## 3. 控制关键时间窗

物理变化发生于 t0。定义错误 regime 控制与 exact-regime 控制的频率/成本差第一次超过阈值的时间：

`T_critical = inf{t>t0: ΔJ_freq(t)≥ε_f or ΔJ_cost(t)≥ε_c or safety differs}`

诊断延迟必须与 T_critical 比较，而不是固定使用任意 5 s。

## 4. 被动可辨识性

输出：

- windowed information Gramian；
- pairwise predictive divergence；
- action-conditioned distinguishability；
- detection delay/censoring；
- source confusion；
- calibration；
- control-relevant misclassification cost。

重点区分：

1. 诊断器性能差；
2. 被动数据本身无信息；
3. 物理标签不可辨但控制等效；
4. 只有主动小扰动才能区分。

## 5. 下一方法的分支规则

- O2 有价值 + passive indistinguishable before Tcritical -> 下一方法是 safe active identification / dual control。
- O2 有价值 + passive distinguishable + O1差 -> nonlinear/online adaptive predictive model。
- O2/O1有价值 + passive distinguishable + current controller差 -> regime-adaptive MPC。
- O2无价值 -> 该场景下不继续做复杂诊断控制。
