# 修正后的物理与数学模型规范

## 1. 单位约定

内部频率状态统一使用标幺频率偏差：

\[
\omega_i=\frac{f_i-f_0}{f_0}.
\]

报告时：

\[
\Delta f_i[\mathrm{Hz}]=f_0\omega_i.
\]

功率统一使用系统基准上的p.u.；时间使用s；能量使用p.u.·h或MWh，配置中必须明确。

## 2. 两区域Plant A

### 2.1 摆动方程

对区域 \(i\in\{1,2\}\)：

\[
2H_i\dot\omega_i
=p_{m,i}+p_{b,i}-p_{L,i}-D_i\omega_i-s_i p_{12},
\]

其中 \(s_1=+1,s_2=-1\)。

### 2.2 联络线

\[
\dot p_{12}=2\pi f_0T_{12}(\omega_1-\omega_2).
\]

### 2.3 ACE

\[
ACE_1=B_1\omega_1+p_{12},
\qquad
ACE_2=B_2\omega_2-p_{12}.
\]

\(B_i\)单位为p.u.功率/p.u.频率，基准值应与 \(D_i+1/R_i\) 同量级并在参数表说明。

## 3. SG调速器、汽轮机和机械GRC

\[
T_{g,i}\dot p_{v,i}
=-p_{v,i}-\frac{1}{R_i}\omega_i+u_{g,i}+u_{aw,i},
\]

\[
\dot p_{m,i}
=\operatorname{sat}_{[-G_i^-,G_i^+]}
\left(\frac{p_{v,i}-p_{m,i}}{T_{t,i}}\right).
\]

备用限制：

\[
-P_{g,i}^{\downarrow}\le p_{m,i}\le P_{g,i}^{\uparrow}.
\]

不能通过每个积分子步硬投影 \(p_m,p_v\) 来隐藏饱和。应将饱和直接放在动力学或采用事件一致实现。PI/MPC必须有anti-windup或显式约束。

## 4. 二次调频采样与保持

上层周期：

\[
T_s\in\{2,4\}\ \mathrm{s}.
\]

本地PFR固定，不在新论文中优化。上层控制器只决定：

\[
u_k=[u_{g,1},u_{b,1},u_{g,2},u_{b,2}]^\top.
\]

命令在区间 \([kT_s,(k+1)T_s)\) 零阶保持，并经过各资源通信/执行动态。

## 5. BESS/IBR共享PFR-SFR能力模型

### 5.1 总目标功率

\[
p_{b,i}^{\star}=p_{0,i}+p_{\mathrm{PFR},i}+p_{\mathrm{SFR},i}.
\]

本地PFR可写成固定droop：

\[
p_{\mathrm{PFR},i}=-K_{f,i}\omega_i.
\]

中央SFR命令经过延迟、丢包和滤波：

\[
T_{c,i}\dot z_i=-z_i+\delta_i(t)u_{b,i}(t-\tau_i),
\]

\[
p_{\mathrm{SFR},i}=K_{u,i}z_i.
\]

### 5.2 功率、视在功率和电流约束

总交流功率必须共同满足：

\[
P_i^-\le p_{b,i}\le P_i^+,
\]

\[
p_{b,i}^2+q_{b,i}^2\le S_{i,\max}^2,
\]

或等价电流限制：

\[
\sqrt{p_{b,i}^2+q_{b,i}^2}\le V_i I_{i,\max}.
\]

若不研究无功，\(q_i\)可作为外生运行点，但必须通过剩余视在功率头寸限制有功。

### 5.3 爬坡和执行动态

\[
-R_i^-\le\dot p_{b,i}\le R_i^+,
\]

\[
\dot p_{b,i}=
\operatorname{sat}_{[-R_i^-,R_i^+]}
\left(\frac{p_{b,i}^{\mathrm{cmd}}-p_{b,i}}{T_{p,i}}\right).
\]

### 5.4 能量与SoC

令 \(E_i\) 为MWh，放电为正：

\[
\dot E_i=-\left(\frac{[P_i]^+}{\eta_{d,i}}+\eta_{c,i}[P_i]^-\right),
\]

其中时间单位为h；若仿真用s，代码必须除以3600。

离散能量：

\[
E_{k+1}=E_k-\frac{\Delta t}{3600}
\left(\frac{[P_k]^+}{\eta_d}+\eta_c[P_k]^-\right).
\]

必须在功率侧施加能量可行限制：

\[
P_k^+\le\frac{3600\eta_d(E_k-E_{\min})}{\Delta t},
\]

\[
-P_k^-\le\frac{3600(E_{\max}-E_k)}{\eta_c\Delta t}.
\]

禁止只把 \(E\) 投影回边界。

### 5.5 可持续头寸

为避免只看一步，可定义未来 \(T_{sus}\) 的保守头寸：

\[
\bar P_{E,i}^+
=\frac{3600\eta_{d,i}(E_i-E_{\min})}{T_{sus}},
\]

并与额定功率、视在功率、爬坡和可用率共同决定：

\[
\mathcal U_{b,i}(c_i)=
\{p:\underline P_i(c_i)\le p\le\bar P_i(c_i),
\ \Delta p\in[-R_i^-,R_i^+]\}.
\]

## 6. 隐藏能力向量与regime

\[
c_i(t)=
[P_i^+,P_i^-,R_i^+,R_i^-,\tau_i,
T_{c,i},T_{p,i},E_i^{avail},a_i]^\top.
\]

普通控制器只能看到：

\[
y_i=[\omega_i,ACE_i,p_{12},p_{m,i},p_{b,i},u_{g,i}^{issued},u_{b,i}^{issued}]^\top+v_i.
\]

不可见：真实regime、真实SoC（除非明确假定遥测可得）、内部延迟、实际可用率、未来变化、真实负荷。

已知训练regime应一次只改变一个机制：

1. headroom reduction；
2. ramp reduction；
3. delay/dropout；
4. energy limitation；
5. service unavailable。

复合、非对称、渐变和未知阶次仅用于OOD。

## 7. 未知负荷估计

将负荷扰动扩展为随机游走：

\[
d_{k+1}=d_k+w_{d,k}.
\]

建立EKF/UKF/MHE或未知输入观测器：

\[
\hat x_{k|k},\hat d_{k|k}
=\mathcal E(y_{0:k},u_{0:k-1}).
\]

所有部署控制器必须基于同一估计器或公平的各自估计器，不能读取真实负荷。

## 8. Plant B：原生多机RMS/DAE

优先采用ANDES Kundur/IEEE39：

- 保留母线网络代数方程；
- 保留多机转子、励磁和原生governor；
- 按控制区计算COI频率与ACE；
- 在指定母线接入黑箱IBR平均值模型；
- 能力变化只作用于IBR外部可用动态；
- 普通控制器只读取可测量量。

Plant B用于验证结论不依赖聚合模型，不要求第一篇即达到OEM EMT精度；但必须诚实标注RMS/DAE范围。

## 9. 控制相关距离

对能力状态 \(a,b\)：

\[
d_{pred}(a,b)=
\sup_{U\in\mathcal U,W\in\mathcal W}
\frac{\|Y_a(U,W)-Y_b(U,W)\|_Q}{s_y},
\]

\[
d_{act}(a,b)=
\frac{\|U_a^\star-U_b^\star\|_R}{s_u},
\]

\[
d_{cap}(a,b)=
\frac{d_H(\mathcal U_b(a),\mathcal U_b(b))}{s_c}.
\]

\[
d_{ctrl}=w_p d_{pred}+w_a d_{act}+w_c d_{cap}.
\]

权重和尺度必须在validation数据上预注册，不得在final结果后修改。

## 10. 控制关键时间

令 \(L_{wrong}(t)\) 和 \(L_{correct}(t)\) 为错误/正确能力控制器的累计损失：

\[
T_{crit}=\inf\{t\ge t_c:
L_{wrong}(t)-L_{correct}(t)\ge\Delta L_{crit}
\ \text{or safety violation occurs}\}.
\]

\(\Delta L_{crit}\)必须由频率、ACE、tie-line等物理阈值构成，不得由任意无量纲混合成本主导。
