# 对 Phase D 完整审查包的专家审查与裁决

## 1. 审查对象

- 原始包：`DIRECTION1_PHASE_D_CRCS_TUBE_MPC_SINGLE_REVIEW_PACKAGE.zip`
- 独立 SHA256：`ed471534e162d5748cb8d735d9ca1f017ac6ad2c7ab9c125c6351e6ef658ebc6`
- ZIP 完整性：通过 `unzip -t`
- 包内清单：声明 240 个受管文件；独立重算后 240/240 哈希一致
- Phase D 最终状态：`PASSIVE_CAPABILITY_SET_NOT_SUPPORTED`
- 实际完成范围：D0–D3；D4–D6 因 H2 Gate 被跳过

## 2. 总体裁决

高层科学问题仍然成立，但 Phase D 的致命 H2 裁决无效。当前包只能证明：

> 注册的单步固定模型 + 单边 CUSUM + 下界证据更新方案，在注册的实验和不稳定闭环控制器下未通过预设 Gate。

它不能证明：

- 被动能力集合估计普遍不可行；
- 当前黑箱 IBR 能力变化没有控制价值；
- 需要终止方向1；
- 主动辨识、集合鲁棒控制或双重控制一定必要；
- CRCS-TMPC 的科学假设已经被否定。

本轮应将原状态改为：

`PHASE_D_GATE_INVALIDATED_BY_CLOSED_LOOP_AND_EVALUATION_DEFECTS`

## 3. 做得较好的内容

1. 两区域 Plant A 使用标幺频率状态，摆动方程、联络线和 ACE 的量纲框架基本正确。
2. BESS 已将本地 PFR 与上层 SFR 合并后施加功率、爬坡、延迟和能量约束，较早期版本明显改善。
3. 估计器部署 API 不直接读取真值模式或隐藏参数。
4. 开发、验证种子分开，失败样本和未评估阶段均被保留。
5. 包结构、Git、哈希、测试和负结果边界说明较完整。
6. 文献包已覆盖黑箱 IBR、多模式建模、频率控制与鲁棒/自适应 MPC 的主要邻近领域。

## 4. 致命问题

### 4.1 D3 名义闭环并不稳定

D3 使用的 2 s 采样 PI 分配为：

```python
integral = clip(integral + 2*ACE, -0.12, 0.12)
request = clip(-1.4*ACE - 0.18*integral, -0.10, 0.10)
command = [0.35*request_1, 0.65*request_1,
           0.35*request_2, 0.65*request_2]
```

独立复算得到：

- 零负荷、仅区域1初始频率扰动 `omega_1=1e-6 pu`：200 s 内最大频差约 0.578 Hz，末端仍约 0.378 Hz；
- 仅 0.0015 pu 小幅正弦背景负荷：
  - 无 SFR：最大频差约 0.0044 Hz；
  - 注册 35/65 PI：最大频差约 0.571 Hz，RMS 约 0.227 Hz；
  - BESS-only PI：最大频差约 1.00 Hz。

因此，所谓“自然闭环 I/O”主要由自激/饱和极限环产生，而不是代表性 AGC 运行数据。任何可辨识性、报警时刻和控制损失时刻均被该闭环缺陷污染。

### 4.2 延迟能力已经更新，但评价器把它记成“未更新”

`CausalCapabilitySetEstimator` 可通过一致性筛选更新 `delay_candidates_s`，但 `d3_capability_gate.py` 的 `update_time` 只在 `estimate.alarm == True` 时记录。

独立复算验证种子100的 `delay_after_load`：

- 真延迟在 45.0 s 从 0.2 s 变为 1.0 s；
- 候选集合约 45.6 s 已收缩为 `{1.0}`；
- 没有触发 CUSUM alarm；
- 代码仍将 `update_time=inf`，因此把该 episode 判为 `update_before_control_loss=False`。

包内“delay 更新及时率=0”的核心证据由评价器错误造成，H2 Gate 必须作废。

### 4.3 `control_loss_time` 不是实际控制损失

当前定义为：

```python
deficit_area += max(|issued_total|-|actual_power|-0.004, 0)*dt
control_loss_time = first time deficit_area >= 0.015
```

它没有使用频率、ACE、联络线、约束违反、成本或与正确能力控制器的反事实差异。独立复算中，某些 headroom 场景在外部负荷事件发生前即被判定“控制损失”，原因只是自激控制命令与执行器输出之间出现面积差。

因此当前 `T_crit` 不是控制关键时间，`P(T_update<T_loss)` 不能支撑科学判断。

### 4.4 失败候选选择逻辑不是“最佳被动估计器”

开发阶段三个候选分别表现为：

- 候选0：联合覆盖约0.993，但 false alarm 约10.4%；
- 候选1：联合覆盖约0.990，false alarm=0，但时序 Gate 未通过；
- 候选2：联合覆盖约0.737，false alarm=0，时序更差。

当全部候选失败时，代码直接选择最后一个候选2，而不是预注册 Pareto 规则、最小违规规则或保守最优候选。最终验证因此使用了明显更差的联合覆盖参数。不能据此否定整个被动估计器类别。

### 4.5 H2 先于 H1 的 Gate 顺序不合理

Phase D 在没有先验证“知道当前真实能力是否能显著改善控制”的情况下，因 H2 失败而终止。正确顺序应为：

1. 先建立可信 rolling current-capability Oracle；
2. 验证能力知识是否具有材料性；
3. 再判断被动数据是否能及时提供该知识；
4. 若被动不足，再判断安全主动辨识或集合鲁棒方法是否必要。

否则可能在一个没有控制价值的问题上研究辨识，也可能错过一个“能力知识很有价值但自然闭环信息不足”的重要科学问题。

## 5. 重大问题

1. H2 只测试 headroom、ramp、delay；energy 与 availability 没有真实变化，`energy_coverage=1` 基本是平凡结果。
2. 能力估计器只使用总命令和 POI 有功，未利用其文档允许的频率、ACE、联络线和未知负荷估计信息。
3. 单一固定时间常数模型和三个阈值候选不足以代表被动能力集合估计的合理技术上界。
4. 变化时间固定45 s、控制周期仅2 s、Plant A 单模型、120 s 时域，不能代表2/4 s AGC、长时正常波动和跨模型泛化。
5. upper capability 在未触及边界时本来不可由被动 I/O 收缩；应明确区分结构不可辨识、有限样本不足和估计器设计失败。
6. Plant B 只完成接口/事件一致性验证，未参与 H2 或材料性分析。
7. 单元测试只检查 API 因果性、简单 CUSUM 和量纲，不检查闭环稳定性、真实 update-time 语义或控制关键时间定义。

## 6. 可保留内容

- Plant A 的状态和物理组件；
- BESS 共享 PFR/SFR 能力约束框架；
- Augmented load estimator 代码雏形；
- capability-set 数据结构；
- no-leakage API 约束；
- 文献与复现包治理框架；
- 结构不可辨识负控制场景；
- 所有失败证据和历史实验。

## 7. 专家建议

方向1应继续，但必须进入“科学恢复”而不是直接继续调估计器。后续先重建稳定闭环和可信材料性 Oracle，再按证据自动选择：

- 被动 set-adaptive tube MPC；
- 安全主动能力辨识的 dual tube MPC；
- 无辨识的 capability-set robust MPC。

最终只允许一个分支进入 final test。
