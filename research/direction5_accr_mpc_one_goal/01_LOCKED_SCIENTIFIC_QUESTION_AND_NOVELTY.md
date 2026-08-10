# 锁定科学问题、创新边界和假设

## 1. 最终科学问题

在多区域SFR/AGC系统中，黑箱IBR的额外可交付功率、爬坡和执行延迟会在运行中发生未通知变化。自然闭环数据可能不足以辨识这些能力。研究问题是：

> 能否在不改变区域总SFR命令的前提下，通过安全的SG–IBR分配探测主动获得控制相关能力信息，在合同能力范围内维持硬约束，并回收一部分完美能力信息对ACE、联络线责任和同步机调节成本的价值？

## 2. 信息与安全边界

### 合同保证能力
\[
\mathcal C_i^c
=
\{\underline P_i^\pm,\underline R_i^\pm,\mathcal D_i^c\}.
\]

用于硬安全。

### 当前候选能力集合
\[
\Theta_{i,k}
\]
包含执行动态、delay、power/ramp候选。它由公共I/O更新。

### 测量能量
\[
E_{i,k}=E_{i,\mathrm{rated}}SOC_{i,k}.
\]

不作为隐藏变量估计。

### 合同违约
真实能力跌破合同floor时，不提供同瞬间保证，进入独立应急域。

## 3. 创新边界

已有工作已经研究：
- 黑箱IBR多模式建模；
- 数据驱动二次控制；
- 安全持续激励；
- 双重/主动探索MPC；
- 自适应控制分配；
- 功率系统主动探测。

因此不能把上述单项作为创新。

可能成立的交叉创新是：

1. **事件触发的控制相关能力认证**：只在能力证书不足、失效或过期时探测；
2. **分配中性探测**：SG与IBR命令相反调整，区域总SFR命令保持不变；
3. **安全探测门**：考虑IBR不交付、执行延迟和SG动态的最坏频率/ACE/tie影响；
4. **有限有效期能力证书**：从主动探测数据形成power/ramp/delay控制能力下界；
5. **认证能力追索MPC**：使用认证能力提高性能，同时保留能力丢失后的SG/慢速备用追索；
6. **价值回收率**：以perfect-information value为上界评价主动认证是否真正有用。

## 4. 可证伪假设

### H1 信息价值
在power/ramp materiality-positive cells中，perfect capability相对contract MPC具有正的ACE/tie或SG-mileage价值。

### H2 探测安全
通过安全门的探测相对无探测合同MPC满足频率/ACE/tie非劣和物理硬约束。

### H3 认证有效
主动探测后能力候选集合显著收缩，false optimism≤1%，且在多数有信息价值场景中产生非零认证剩余能力。

### H4 价值回收
ACCR-MPC在materiality-positive cells中回收至少预注册比例的perfect-information value。

### H5 全局非劣
在所有known合同场景中成功率、frequency safety和硬约束不劣于contract MPC。

### H6 条件性理论
合同范围内的安全探测、集合包含和追索MPC证书与代码一致。

## 5. 停止条件

若发生任一情况，终止方向5：

1. perfect information value在纠正平台上不成立；
2. 所有安全探测序列均无信息或探测代价超过信息价值；
3. 能力认证无法满足false optimism与coverage；
4. ACCR相对contract MPC在充分validation下无价值；
5. Plant A/B方向系统性矛盾且无法解释；
6. 创新被正式文献完整覆盖。
