# 被动与安全主动能力辨识规范

## 1. 被动能力集合估计

### 1.1 低阶外部动态

对每个IBR，建立控制器可见的外部模型族，例如：

\[
x^b_{k+1}=A_b(\theta)x^b_k+B_b(\theta)u^d_k+G_bv_k,
\quad p_{b,k}=C_bx^b_k+e_k,
\]

其中 `u^d`包含候选延迟。非线性饱和、爬坡和能量通过能力集合进入。

### 1.2 Set-membership更新

\[
\Theta_{k+1}=\Theta_k\cap
\{\theta:\|y_{k+1}-\hat y_{k+1|k}(\theta)\|\le\epsilon_k\}.
\]

对突变允许change detector触发集合扩展：

\[
\Theta_{k+1}=\Theta_{global}
\]

或切换到多模型集合，但必须记录扩展时间和原因。

### 1.3 功率/爬坡/延迟/能量集合

- 已实现的输出只能证明能力下界；
- 未触及边界不能证明上限降低；
- 延迟候选更新必须由实际集合变化记录；
- 能量集合由已知初始区间、POI功率和效率区间传播；
- availability只能通过影响输出能力的证据更新，不能依赖标签。

### 1.4 至少三种合理被动基线

1. 多步 set-membership；
2. GLR/CUSUM + reset；
3. IMM/Bayesian interval model。

阈值选择必须使用Pareto/预注册评分，不允许“全部失败时选最后候选”。

## 2. 信息充分性指标

对最近窗口的回归量：

\[
G_k=\sum_{j=k-L+1}^{k}\phi_j\phi_j^T.
\]

报告：

- `lambda_min(G_k)`；
- condition number；
- 预测模型间KL/似然间隔；
- capability set diameter；
- 可控动作集合差异。

当信息不足时，估计器应输出“不确定”，而不是高置信错误标签。

## 3. 安全主动辨识

### 3.1 控制分解

\[
u_k=u_k^{reg}+u_k^{probe}.
\]

探测可采用：

- BESS增量与SG补偿；
- 两个异质资源间零和重分配；
- 在AGC自然命令上选择更有信息的可行分配。

由于资源动态不同，静态零和不代表动态完全抵消，必须进入预测模型和安全管束。

### 3.2 信息目标

可选一个并预注册：

\[
J_{info}=-\log\det(G_{k+N}+\epsilon I),
\]

或

\[
J_{info}=\operatorname{diam}(\Theta_{k+N}),
\]

或预测集合体积。final前不得根据结果更换指标。

### 3.3 双重MPC目标

\[
\min_U J_{reg}(U)+\lambda_{info}J_{info}(U)+\lambda_p\|U^{probe}\|^2.
\]

所有候选探测轨迹必须具有backup：

\[
\exists U^{backup}: X^{backup}_{j|k}\in\mathcal X,
U^{backup}_{j|k}\in\mathcal U,
\forall c\in\mathcal C_k,w\in\mathcal W.
\]

### 3.4 探测预算

预注册：

- 最大探测功率；
- 探测能量；
- SG补偿里程；
- 可接受额外频率/ACE波动；
- 禁止探测的低安全裕度区域。

## 4. 分支选择

### 分支P

自然闭环被动Gate通过，使用被动能力集合自适应tube MPC。

### 分支A

被动失败但安全主动Gate通过，使用SACID-TMPC。

### 分支R

被动和主动均不通过，但H1材料性成立，使用不依赖辨识的全能力集合鲁棒MPC。

只允许一个分支进入final。

## 5. 禁止事项

- 使用未来窗口判断变化来源；
- 使用centered smoothing；
- 以真实能力标签训练部署分类器后不说明监督信息；
- 通过触发饱和制造不安全探测；
- 用探测测试数据调阈值；
- 在被动失败后未经Gate临时加入RL、CBF或神经网络。
