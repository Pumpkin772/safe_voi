# Rolling Oracle、材料性与因果信息协议

## 1. 为什么必须先验证材料性

若知道当前真实能力也不能改善控制，则研究辨识没有意义。Phase E 必须先建立可信Oracle，再研究信息获取。

## 2. Oracle层级

### O0：常规部署基线

- SG-only ACE PI/LQI；
- 固定比例SG/IBR；
- 固定nominal capability。

### O1：nominal-model rolling MPC

使用公开名义模型与全局约束，未知能力不更新。

### O2：current-capability rolling NMPC（材料性Oracle）

评价侧每个SFR时刻可读取当前真实能力 `c_k` 和当前真实物理状态，但：

- 不得读取未来负荷；
- 不得读取未来能力切换；
- 不得读取未来丢包/延迟样本；
- 必须每2/4s滚动重求解；
- 只执行第一个动作；
- 必须使用与Plant相同的物理约束。

O2不是部署方法，只用于回答“当前能力知识的价值”。

### O3：clairvoyant上界（可选）

仅用于区分“当前能力知识不足”与“未来预知才有效”。不得作为普通比较对象或论文主结果。

## 3. O2优化模型

对预测时域 `N`：

\[
\min_{U,X}\sum_{j=0}^{N-1}
\left(
\|\omega_{j|k}\|_{Q_f}^2+
\|ACE_{j|k}\|_{Q_a}^2+
\|p_{tie,j|k}\|_{Q_t}^2+
\|u_{j|k}\|_{R}^2+
\|\Delta u_{j|k}\|_{S}^2
\right)
+V_f(x_{N|k}).
\]

约束：

- 动力学与ZOH；
- SG功率/GRC/阀门/anti-windup；
- BESS总PFR+SFR功率、爬坡、能量、延迟；
- 频率、ACE、联络线软/硬约束；
- 终端SG backup可行域；
- 已知当前能力在预测期间按“保持当前”或注册的保守演化集合处理，不得预知未来切换。

## 4. Oracle资格检查

每个episode必须保存：

- solver status；
- primal/dual residual；
- KKT或等价一阶条件；
- constraint violation；
- solve time；
- warm-start status；
- fallback原因；
- independent rollout objective；
- prediction vs realized error。

Gate：

- 求解成功率≥95%；
- 约束残差p99≤1e-5；
- 多初值目标差≤2%；
- horizon加倍后主要结论不反转；
- 细化dt后主要指标差≤2%。

## 5. 材料性定义

### 5.1 物理成功优先

每个episode先分类：

```text
both_success
only_oracle_success
only_baseline_success
both_fail
solver_not_evaluated
code_failure
```

物理成功至少要求：

- 全时域频率不越预注册阈值；
- ACE和联络线在终端窗口恢复；
- SG/BESS功率、GRC、能量、SoC无违反；
- solver持续可用或fallback安全。

### 5.2 连续指标

仅在双方共同成功episode上比较：

- frequency IAE/RMS/nadir/RoCoF；
- ACE IAE与终端均值；
- tie-line IAE与终端偏差；
- SG/BESS mileage、energy、reserve；
- 总成本与Pareto；
- 恢复时间；
- 计算时间。

### 5.3 H1材料Gate

至少满足：

1. 在两类能力机制、两类SG紧张度中，O2相对最佳部署基线提高成功率≥10个百分点；或
2. 在双方成功场景中，频率/ACE/tie-line至少两项平均改善≥10%，配对cluster-bootstrap 95% CI不跨0；
3. Plant A与Plant B方向一致；
4. 优势不依赖单一极端参数。

若不通过：`PROBLEM_NOT_MATERIAL`。

## 6. 控制关键窗口

### 6.1 匹配反事实

能力变化时刻 `t_c`，从同一状态和同一随机实现分叉：

- 路径A：旧能力模型控制；
- 路径B：O2 current-capability Oracle。

### 6.2 损失差

\[
\Delta J(t)=J_A(t_c,t)-J_B(t_c,t).
\]

其中包含频率、ACE、tie-line、约束和资源成本。控制关键时刻：

\[
T_{crit}=\inf\{t\ge t_c:\Delta J(t)\ge J_{mat}\}.
\]

`J_mat`使用development/validation数据和工程阈值在final前冻结。

### 6.3 其他时刻

同时报告：

- `T_freq`：首次材料频率劣化；
- `T_ACE`：首次材料ACE劣化；
- `T_tie`：首次材料联络线劣化；
- `T_constraint`：首次资源/安全违反；
- `Tcrit`对阈值的敏感性。

## 7. 因果更新时间

对估计集合 `C_hat,k`，更新时间不是“报警时刻”，而是满足以下全部条件的最早时刻：

1. 与上一集合相比发生控制相关变化；
2. 新集合重新包含当前真能力（评价侧检查）；
3. 变化足以改变可行控制域或预测动作，超过预注册 `d_ctrl` 阈值；
4. 仅使用 `0:k` 数据。

记录：

- alarm_time；
- set_expansion_time；
- set_recovery_time；
- set_contraction_time；
- control_relevant_update_time。

禁止将任一单独时间替代全部概念。

## 8. Load-vs-capability混淆

必须设计匹配场景：

- load-only；
- capability-only；
- simultaneous；
- load before/after capability；
- no excitation。

评价：

- false attribution；
- load estimator RMSE/coverage；
- capability set coverage；
- 对控制动作的影响。
