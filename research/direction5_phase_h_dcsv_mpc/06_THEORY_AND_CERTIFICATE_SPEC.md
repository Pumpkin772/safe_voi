# 理论和证书要求

## 1. Sustainable theorem

在注册：
- disturbance/load-rate set；
- capability set；
- delay set；
- terminal set；
-初始可行域

内，证明以下之一：

### Level A
有限时域鲁棒约束满足。

### Level B
条件性递归可行：
- terminal set invariant；
- shift candidate可行；
- actual-action commit与delay pipeline一致；
- backup/controller约束一致。

不能证明 Level B 时，必须收缩声明为 Level A。

## 2. Bridge theorem

证明：
- 在 \(T_R\) 前资源硬约束和频率/ACE边界满足；
- energy budget足够；
- slow reserve到达后进入sustainable domain。

无slow reserve模型时，只能给有限 \(T_{\rm bridge}\) 证书。

## 3. Infeasibility theorem/certificate

为每个物理不可行cell保存：
- power shortfall；
- ramp shortfall；
- energy shortfall；
- binding constraints。

## 4. Reproduction

所有集合和证书必须：
-保存为NPZ/JSON/Parquet；
-有独立重算脚本；
-有容差；
-有hash；
-代码使用同一对象。
