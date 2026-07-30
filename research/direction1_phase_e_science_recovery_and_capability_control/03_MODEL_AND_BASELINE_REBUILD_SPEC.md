# 物理模型、名义闭环和基线重建规范

## 1. 多区域频率模型

内部频率状态统一为：

\[
\omega_i=(f_i-f_0)/f_0.
\]

区域摆动方程：

\[
2H_i\dot\omega_i=p_{m,i}+p_{b,i}-p_{L,i}-D_i\omega_i-\sum_j p_{ij}.
\]

联络线：

\[
\dot p_{ij}=2\pi f_0 T_{ij}(\omega_i-\omega_j).
\]

ACE：

\[
ACE_i=B_i\omega_i+\sum_j p_{ij},
\qquad B_i=D_i+R_i^{-1}
\]

或使用系统运营商定义的频率偏置，必须在参数表中说明。

## 2. 同步机/调速器/汽轮机

\[
T_{g,i}\dot p_{v,i}=-p_{v,i}-\omega_i/R_i+u_{g,i}+u_{aw,i},
\]

\[
\dot p_{m,i}=
\operatorname{sat}_{[-G_i^-,G_i^+]}
\left((p_{v,i}-p_{m,i})/T_{t,i}\right).
\]

约束：

\[
\underline p_{m,i}\le p_{m,i}\le\bar p_{m,i}.
\]

Anti-windup必须显式实现，不允许积分后直接裁剪机械功率来掩盖不稳定。

## 3. 固定本地PFR和上层SFR

本地PFR固定，不作为论文创新：

\[
p_{b,i}^{PFR}=-K_{b,i}\omega_i.
\]

上层SFR命令：

\[
u_i=[u_{g,i},u_{b,i}]^T,
\]

主更新周期4 s，2 s为敏感性。命令通过统一延迟通道，不得在不同脚本中临时实现。

## 4. BESS/IBR共享能力模型

总目标：

\[
r_{b,i}=p_{b,i}^{0}+p_{b,i}^{PFR}+u_{b,i}^{SFR}.
\]

延迟后目标：

\[
r_{b,i}^{d}(t)=\mathcal D_{\tau_i(t)}[r_{b,i}(t)].
\]

功率、视在功率、headroom与availability：

\[
\underline P_i(k)\le p_{b,i}(k)\le\bar P_i(k),
\]

\[
p_{b,i}^2+q_{b,i}^2\le S_i^2,
\]

\[
\bar P_i(k)\le a_i(k)P_i^{rated}h_i^+(k),
\quad
-\underline P_i(k)\le a_i(k)P_i^{rated}h_i^-(k).
\]

爬坡：

\[
-\bar R_i^-(k)\le\dot p_{b,i}\le\bar R_i^+(k).
\]

执行器：

\[
T_{b,i}\dot p_{b,i}=
\operatorname{sat}_{[-\bar R_i^-,\bar R_i^+]}
\left(\operatorname{sat}_{[\underline P_i,\bar P_i]}(r_{b,i}^{d})-p_{b,i}\right).
\]

能量：

\[
\dot E_i=-\frac{[P_i]^+}{\eta_{d,i}}-\eta_{c,i}[P_i]^-,
\]

并在功率侧预先限制一步可用能量，不允许事后SoC投影产生自由能量。

## 5. 隐藏能力事件

开发/验证使用单机制事件：

1. headroom-only；
2. ramp-only；
3. delay-only；
4. energy-only；
5. availability/service-only。

OOD final可使用：

- 非对称上下限；
- 缓慢漂移+突然变化；
- 两机制复合；
- 三阶执行器；
- 通信抖动与丢包。

物理标签仅evaluation侧保存，部署控制器不可见。

## 6. Plant A

透明两区域聚合模型，用于：

- 数学推导；
- 单元测试；
- 大规模实验；
- 能力集合和tube证书。

必须输出完整矩阵、符号、单位、参数来源和离散化方法。

## 7. Plant B

原生多机RMS/DAE，优先ANDES Kundur；若使用IEEE39，必须说明模型参数完整性。

要求：

- 保留原生网络、发电机、励磁和调速器；
- BESS在具体母线作为真实有功注入进入网络代数功率平衡；
- 获取COI频率、区域频率、联络线和机组功率；
- 外部控制接口与ANDES原生事件/Alter在同一输入下交叉验证；
- 不允许仅运行未修改ANDES案例就称为Plant B验证。

## 8. 名义闭环设计

名义PI/LQI必须先基于离散增广模型设计：

\[
x_{k+1}=A_dx_k+B_du_k+E_dw_k,
\]

包含ZOH、2/4s采样和已知名义延迟。

设计后检查：

- 线性闭环谱半径；
- 非线性饱和/GRC闭环；
- anti-windup；
- 小扰动和背景负荷。

禁止直接沿用Phase D的 `Kp=1.4, Ki=0.18, 35/65` 方案。

## 9. 公平控制器信息集

部署基线与proposed共享：

- 同一观测；
- 同一状态/负荷估计器；
- 同一输入、功率、能量和延迟约束；
- 同一控制周期；
- 同一求解容差与fallback统计。

Oracle可知道当前真能力，但不得知道未来。

## 10. 必须增加的测试

- `test_nominal_closed_loop_small_signal_decay`
- `test_background_load_controller_does_not_destabilize`
- `test_delay_applied_in_all_entrypoints`
- `test_bess_energy_no_projection_or_free_energy`
- `test_pfr_sfr_share_same_power_and_energy_set`
- `test_plant_b_bess_power_enters_network_balance`
- `test_plant_b_same_input_external_vs_native_event`
- `test_2s_4s_discrete_closed_loop_stability`
- `test_no_hidden_truth_in_deployable_api`
