# 最终方法分支规范

## 1. 共通控制模型

离散增广系统：

\[
x_{k+1}=A(\theta_k)x_k+B_g u_{g,k}+B_b(\theta_k,d_k)u_{b,k}+Ew_k,
\]

其中：

- `theta_k` 属于在线能力/动态集合；
- `d_k`为延迟候选；
- `w_k`包含未知负荷估计误差和模型残差。

控制器使用：

\[
\Theta_k,\quad\mathcal C_k,\quad\mathcal W_k,
\]

而不是单一真实标签。

状态约束至少包含：

\[
|\Delta f_i|\le \bar f,
\quad |ACE_i|\le\bar a,
\quad |p_{tie,ij}|\le\bar p_{tie},
\]

以及SG/BESS功率、GRC、爬坡、能量和SoC约束。

## 2. Tube结构

名义轨迹：

\[
z_{j+1|k}=A_0z_{j|k}+B_0v_{j|k}.
\]

实际控制：

\[
u_{j|k}=v_{j|k}+K(x_{j|k}-z_{j|k}).
\]

误差管：

\[
e_{j+1|k}\in(A(\theta)+B(\theta)K)e_{j|k}\oplus\mathcal W_k,
\quad \forall \theta\in\Theta_k.
\]

收紧约束：

\[
z_{j|k}\in\mathcal X\ominus\mathcal E_{j|k},
\quad
v_{j|k}\in\mathcal U(\mathcal C_k)\ominus K\mathcal E_{j|k}.
\]

## 3. 终端SG备份

构造不依赖IBR当前可用性的备份集：

\[
\mathcal X_f^{SG}=
\{x:\kappa_{SG}(x)\text{在最坏IBR能力下满足约束并保持不变性}\}.
\]

终端约束：

\[
z_{N|k}\in\mathcal X_f^{SG}\ominus\mathcal E_{N|k}.
\]

若在线优化失败，执行最近一次可行序列移位并切换至 `kappa_SG`。

## 4. 分支P：Passive Capability-Set Adaptive Tube MPC

优化：

\[
\min_{V,Z}\sum_{j=0}^{N-1}
\ell(z_{j|k},v_{j|k})+V_f(z_{N|k})
\]

在当前被动能力集合和误差管上求解。

核心创新不应写成一般adaptive MPC，而是：

- 对未通知IBR调频能力变化建立控制相关集合；
- 在多区域ACE责任下实时收缩/扩展能力集合；
- 用集合变化驱动调频责任重分配。

## 5. 分支A：SACID-TMPC

全称：

**Safe Active Capability Identification Dual Tube MPC**。

优化变量同时包含调频动作和探测分量：

\[
\min_{V^{reg},V^{probe},Z}
J_{reg}+\lambda_{info}J_{info}+\lambda_pJ_{probe}.
\]

信息模型必须预测未来测量对集合的可能收缩，但不允许使用未来真值。

可采用有限候选探测序列/场景树，以保证可计算性；应明确这是近似双重控制，不声称精确Bayes最优。

每个候选学习轨迹必须与一条安全backup轨迹绑定：

\[
\forall \theta\in\Theta_k,w\in\mathcal W_k,
\quad X^{learn}\text{或}X^{backup}\text{至少一条可行}.
\]

在线只在安全裕度和求解器状态满足时执行探测，否则退回纯调频/鲁棒分配。

## 6. 分支R：Capability-Set Robust Tube MPC

不尝试判断当前能力标签；使用当前可证全局集合或运营商声明集合：

\[
\theta\in\Theta_{global},\quad c\in\mathcal C_{global}.
\]

对集合内全部能力保证安全。该分支的价值是给出“信息不足时不做错误识别”的可信基线或最终方法。

若过度保守导致IBR完全不用，应如实报告，不得通过缩小未知集合制造性能。

## 7. 真正MPC的代码要求

任何名为MPC的类必须包含：

- 明确prediction horizon；
- 决策变量序列；
- 动态等式约束；
- 状态/输入/终端约束；
- 目标函数；
- receding-horizon执行；
- solver status和fallback。

禁止用固定比例、标量gain更新或SG-only规则命名为MPC。

## 8. 基线实现要求

### Nominal MPC

固定名义能力和名义动态，但求解真实有限时域优化。

### RLS Adaptive MPC

在线估计低阶动态参数：

\[
\hat\theta_k=\hat\theta_{k-1}+
K_k(y_k-\phi_k^T\hat\theta_{k-1}),
\]

并有协方差、遗忘因子、投影和预测MPC。

### Robust capability MPC

在全局能力集合上进行真实robust/tube MPC，而不是简单不给IBR命令。

## 9. 在线复杂度

主控制周期4s；要求：

- median <0.1×周期；
- p99 <0.5×周期；
- 超时必须进入记录明确的安全fallback；
- Plant B可使用降阶预测模型，但必须在原生plant闭环评估。

## 10. 方法声明

只有在E7证书通过时允许使用：

- recursively feasible；
- robust constraint satisfaction；
- safety-guaranteed。

否则只能称为：

- constraint-aware；
- empirically safe in tested cases；
- robustified predictive control。
