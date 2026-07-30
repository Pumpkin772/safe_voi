# 纠正后的物理模型、单位和验证规范

## 1. 统一单位

内部频率状态统一为：

\[
\omega_i=\frac{f_i-f_0}{f_0}\quad [\mathrm{pu}],
\]

报告量为：

\[
\Delta f_i=f_0\omega_i\quad [\mathrm{Hz}].
\]

所有惯量 \(H_i\) 使用秒，阻尼 \(D_i\) 使用 pu功率/pu频率，功率使用系统基准标幺，能量使用 MWh。禁止在同一方程中混用 Hz 状态和 pu 参数。

## 2. Plant A：透明两区域聚合模型

### 2.1 区域频率和联络线

\[
\dot\delta_i=2\pi f_0\omega_i,
\]

\[
2H_i\dot\omega_i=p_{m,i}+p_{b,i}-p_{L,i}-D_i\omega_i-s_i p_{12},
\]

\[
p_{12}=T_{12}(\delta_1-\delta_2),\qquad
\dot p_{12}=2\pi f_0T_{12}(\omega_1-\omega_2),
\]

其中 \(s_1=1,s_2=-1\)。

### 2.2 ACE

\[
ACE_1=B_1\omega_1+p_{12},\qquad
ACE_2=B_2\omega_2-p_{12},
\]

\[
B_i=D_i+1/R_i.
\]

所有控制器使用同一ACE定义。

### 2.3 同步机调速器、汽轮机和GRC

\[
T_{g,i}\dot p_{v,i}=-p_{v,i}-\frac{1}{R_i}\omega_i+u_{g,i}+u_{aw,i},
\]

\[
\dot p_{m,i}=\operatorname{sat}_{[-G_i^-,G_i^+]}
\left(\frac{p_{v,i}-p_{m,i}}{T_{t,i}}\right),
\]

\[
-P_{g,i}^-\le p_{m,i}\le P_{g,i}^+.
\]

禁止在每个积分步末用硬投影掩盖不连续；应采用事件一致饱和和显式anti-windup。

### 2.4 固定本地PFR和上层SFR

\[
p_{b,i}^{\mathrm{PFR}}=-K_{b,i}^{\mathrm{PFR}}\omega_i,
\]

\[
u_{b,i}^{\mathrm{tot}}=p_{b,i}^{\mathrm{PFR}}+u_{b,i}^{\mathrm{SFR}}.
\]

PFR参数在所有方法间固定；CRCS-TMPC只优化上层SG/IBR SFR责任。

### 2.5 BESS总功率和能量

通信/执行延迟采用离散命令队列：

\[
\bar u_{b,k}=u_{b,k-d_k}^{\mathrm{tot}},\qquad d_k\in\mathcal D_k.
\]

执行器动态：

\[
T_{b,k}\dot p_{b,k}=-p_{b,k}+\Pi_{\mathcal U(E_k,c_k)}(\bar u_{b,k}).
\]

统一可行集合：

\[
\mathcal U(E_k,c_k)=\left\{p:
-P_k^-\le p\le P_k^+,
-R_k^-\le \dot p\le R_k^+,
p^2+q^2\le (V I_{\max})^2,
E_{k+1}\in[E_{\min},E_{\max}]
\right\}.
\]

能量更新：

\[
E_{k+1}=E_k-\frac{\Delta t}{3600}
\left(\frac{[P_{b,k}]^+}{\eta_d}+\eta_c[P_{b,k}]^-\right).
\]

功率侧必须在步内限制可用能量，禁止事后SoC投影产生自由能量。

## 3. 黑箱外部动态模型

控制器不使用内部Plant参数。对外I/O模型使用延迟ARX/状态空间集合：

\[
p_{b,k+1}=\phi_k^\top\theta_k+e_k,
\quad \theta_k\in\Theta_k,
\quad d_k\in\mathcal D_k,
\]

\[
\phi_k=[p_{b,k:k-n_y+1},u_{b,k-d:k-d-n_u+1},\omega_{k:k-n_f+1},1].
\]

模型阶数通过development数据和验证多步误差选定，final数据不得参与。

## 4. Plant B：必须是真实原生多机网络验证

首选实现：

- ANDES Kundur 或 IEEE 39-bus；
- 保留原生网络代数方程、同步机模型和调速器；
- 在指定母线接入平均值BESS/IBR有功注入模型；
- 通过 ANDES 外部控制或用户模型接口接收2/4s SFR；
- 计算COI频率、区域ACE和关键联络线功率。

不允许再次使用与ANDES无动力学耦合的自定义“六母线Plant B”。

### 4.1 有功平衡审计

每个积分步必须满足：

\[
\sum_g (p_{m,g}-p_{e,g})+\sum_b p_{b}-\sum_l p_L-p_{loss}=2\sum_g H_g\dot\omega_g,
\]

在数值容差内闭合。BESS有功必须明确进入网络/机器电气功率平衡。

### 4.2 交叉验证要求

在同一无BESS和固定BESS控制的扰动下，对比：

- COI初始RoCoF；
- nadir/peak；
- 10/30/60s频率；
- 主导机电模态频率和阻尼；
- 区域联络线功率；
- SG机械功率总和。

若自建接口与原生ANDES误差超过：nadir 10%、IAE 10%、主导模态频率 10%、阻尼 20%，不得通过Plant B Gate。

## 5. 数值验证门限

- 初始RoCoF解析值相对误差 ≤1%；
- 功率平衡残差 P99 ≤1e-7 pu；
- BESS能量残差 P99 ≤1e-8 MWh；
- dt=0.01与0.005s关键指标差 ≤1%；
- dt=0.02与0.01s关键指标差 ≤2%；
- 延迟脉冲响应到达误差 ≤一个仿真步；
- 300s无外扰闭环无漂移；
- Plant B所有基础场景不出现数值增长型振荡。

## 6. 参数来源

每一个参数必须在 `PARAMETER_SOURCES.csv` 中记录：

- 名称；
- 数值/范围；
- 单位；
- 适用Plant；
- 来源类型（标准系统、文献、设备规格、假设）；
- DOI/文献或文件路径；
- 合理性；
- 敏感性范围。

不得只记录5个参数。
