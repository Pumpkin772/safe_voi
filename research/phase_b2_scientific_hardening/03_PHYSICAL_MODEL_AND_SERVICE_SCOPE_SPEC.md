# Plant B：两区域频率系统与物理化黑箱 IBR

## 1. 服务定位

本阶段研究“补充/二次频率调节”，本地一次调频固定，不由上层方法优化。

上层控制周期建议为 2 s。若保留 0.5 s，只能称“wide-area supplementary frequency control”，不能直接称标准 AGC。

## 2. 两区域系统

对区域 i=1,2：

`M_i * dω_i/dt = -D_i ω_i + p_m_i + p_b_i - d_i - p_tie_i`

`T_t_i * dp_m_i/dt = -p_m_i + p_v_i`

`T_g_i * dp_v_i/dt = -p_v_i - (1/R_i)ω_i + u_g_i`

`dp_12/dt = 2π T_12 (Δf_1 - Δf_2)`

`p_tie_1 = p_12`, `p_tie_2 = -p_12`

`ACE_1 = B_1 Δf_1 + p_12`

`ACE_2 = B_2 Δf_2 - p_12`

固定本地下垂保留在 governor/IBR 本地环；上层只输出 `u_g_i` 与 `u_b_i`。

## 3. SG GRC 与备用

必须把 GRC 施加到机械功率或阀门输出，而不是只限制控制命令：

`dp_m_i/dt = clip((-p_m_i+p_v_i)/T_t_i, -GRC_i^-, GRC_i^+)`

或采用等价分段模型。

SG capability level 使用真实可解释单位：

- adequate：备用足以独立承担最大事故，GRC 较快；
- scarce：稳态备用不足以独立承担最大事故，IBR 有实质价值；
- critical：常规资源明显不足，但系统在 IBR 可用时仍应可行。

所有 pu/s 同时报告 pu/min 与基准 MW/min。

## 4. 物理化 BESS/IBR Plant B

状态建议：

`x_b = [z_cmd, p_b, soc, a]`

其中 `a∈[0,1]` 是可用度/头寸状态，仅 simulator 内部可见。

### 命令通道

`T_c,m dz_cmd/dt = -z_cmd + e_m K_u,m u_b(t-τ_m)`

### 可用功率头寸

`H_d(soc,P0,Q0,V) = min(P_r-P0, sqrt(max((V I_max)^2-Q0^2,0))-P0, 3600 E_N η_d (soc-s_min)/(S_B T_sus))`

`H_c(soc,P0,Q0,V) = min(P_r+P0, sqrt(max((V I_max)^2-Q0^2,0))+P0, 3600 E_N (s_max-soc)/(S_B T_sus η_c))`

最终上下调能力乘以 `a`。

### 实际有功输出

`p_ref = P0 + p_local(Δf) + sat(z_cmd, -a H_c, a H_d)`

`dp_b/dt = clip((p_ref-p_b)/T_p,m, -r_m^-, r_m^+)`

`p_local(Δf)` 是固定本地响应，不属于上层决策。可以设置为零或已知固定下垂，但所有方法必须一致。

### SoC

`dsoc/dt = -S_B/(3600 E_N) * ([p_b-P0]^+/η_d + η_c[p_b-P0]^-)`

## 5. 具有物理含义的 hidden regimes

1. `nominal_available`：正常头寸、正常延迟；
2. `headroom_or_current_limited`：P0/Q0/电流限制导致 H_d/H_c 收缩；
3. `energy_limited`：SoC 接近上下界，持续能力下降；
4. `communication_degraded`：时延增加、丢包或命令保持；
5. `service_disabled`：集中命令被禁用，但固定本地保护/下垂仍可存在；
6. `recovery`：能力逐步恢复；
7. `structural_ood`：滞回、非对称速率或未训练的组合变化。

切换不能重置 p_b、SoC 或历史命令。

## 6. 测量接口

默认控制器可见：

- 区域频率；
- tie-line power；
- ACE；
- IBR POI 有功输出；
- 已下发命令；
- SG/区域总有功遥测。

默认不可见：

- true regime；
- SoC；
- 内部限幅原因；
- 真实时延；
- 内部状态。

另设可用遥测对照实验，逐项开放 SoC/headroom/status bit，量化通信标准化信息的价值。
