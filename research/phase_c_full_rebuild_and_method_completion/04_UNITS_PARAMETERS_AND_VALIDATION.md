# 单位、参数来源与验证硬规则

## 1. 推荐内部单位

| 量 | 符号 | 内部单位 |
|---|---|---|
| 频率偏差 | omega | p.u. frequency |
| 报告频差 | Delta f | Hz |
| 功率 | p | p.u. on Sbase |
| 惯量 | H | s |
| 阻尼 | D | p.u. power / p.u. frequency |
| droop | R | p.u. frequency / p.u. power |
| tie coefficient | T12 | p.u./rad |
| 时间 | t | s |
| 能量 | E | MWh or p.u.·h, explicitly fixed |

## 2. 起始参数范围（仅供开发，不得直接作为最终来源）

- `f0=50 Hz`
- `H_i=3–8 s`
- `D_i=0.5–2.0 pu/pu-frequency`
- `R_i=0.04–0.06 pu-frequency/pu-power`
- `Tg=0.1–0.5 s`
- `Tt=0.3–8 s`，按机组类型区分
- 上层SFR周期 `2/4 s`
- BESS执行 `0.05–0.5 s`
- BESS通信延迟 `0–2 s`
- 功率、能量、爬坡按实际MW/MWh转换成p.u.

最终参数必须填写 `PARAMETER_SOURCES.csv`：

```text
parameter,value,unit,source_type,source,justification,sensitivity_range
```

## 3. 必须通过的解析验证

### 初始RoCoF

扰动发生、快速控制尚未动作时：

\[
\left.\frac{d\Delta f_i}{dt}\right|_{0^+}
=\frac{f_0}{2H_i}\left(-\Delta p_{L,i}-s_i\Delta p_{12}\right).
\]

数值积分第一时刻与解析误差<1%。

### 稳态droop

在无积分SFR时，阶跃扰动后的稳态频差应与等效droop/阻尼解析解一致。

### tie-line

区域1频率高于区域2时，\(p_{12}\)应按定义从1流向2；ACE符号必须与此一致。

## 4. 数值步长

至少测试：

```text
0.005, 0.01, 0.02, 0.05 s
```

推荐步长必须使：

- nadir、RoCoF、频率IAE、ACE IAE、最大BESS功率误差<1%；
- 约束激活场景误差<2%；
- 不允许 `dt` 大于最小动态时间常数的一半而无收敛证明。

## 5. BESS守恒验证

每个episode检查：

\[
\epsilon_E=
E(T)-E(0)+\int_0^T
\left(\frac{[P]^+}{\eta_d}+\eta_c[P]^-\right)dt.
\]

要求：

```text
abs(epsilon_E) <= max(1e-6 p.u.h, 1e-5 * throughput)
```

SoC边界场景必须证明没有自由能量。

## 6. 约束验证

每个积分步检查：

- SG机械GRC；
- SG reserve；
- BESS总PFR+SFR功率；
- 视在功率/电流；
- ramp；
- energy/SoC；
- delay/dropout；
- service enablement。

任何投影必须记录投影量；若频繁投影，视为模型/控制器错误，不能当作正常运行。

## 7. 参数来源层级

优先顺序：

1. 标准系统原始数据与官方文档；
2. IEEE/Elsevier正式论文；
3. NERC/ENTSO-E/系统运营商指南；
4. 厂商/项目公开技术资料；
5. 合理假设，仅能用于敏感性，不得伪装成真实参数。

## 8. 原生模型验证

Plant B至少输出：

- 原始网络/机组模型清单；
- 修改点；
- 稳态潮流；
- 无控制事件；
- PI基准事件；
- IBR能力变化事件；
- 与Plant A的COI频率/ACE趋势对照。
