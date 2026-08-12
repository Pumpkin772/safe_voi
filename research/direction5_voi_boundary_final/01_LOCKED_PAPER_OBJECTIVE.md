# 锁定论文目标与科学问题

## 1. 论文科学问题

> 对给定的多区域频率状态、合同能力、IBR候选能力集合、控制周期、测量误差和同步机备用，安全主动探测的净控制价值是否为正？正值区域的边界在哪里？能否构造一个只在正值区域探测、其余状态严格退化为合同MPC的选择性控制器？

## 2. 核心输出不是全局平均增益

论文必须输出：

1. **Perfect-information value map**；
2. **Safe-probe net-value map**；
3. **No-probe region**；
4. **Positive-probe region**；
5. **Boundary sensitivity**：
   - SG reserve；
   - control period；
   - load/ACE level；
   - power/ramp/delay uncertainty spread；
   - measurement noise；
   - SoC/headroom；
6. 选择性策略的闭环验证。

## 3. 方法名称

继续沿用：

> **Selective VOI-ACCR-MPC**

不再创建新的方法缩写。

## 4. 论文级正面结果

正面论文不要求全场景平均提高4%。

必须满足：

### 全场景
- physical success相对合同MPC下降≤1个百分点；
- hard violations=0；
- frequency peak绝对非劣margin≤0.02Hz；
- no-probe区域探测率≤5%；
- no-probe区域核心指标绝对变化≤1%；
- p99 solve time<0.5控制周期。

### 正值区域
- 实际闭环净收益对ACE、tie或SG mileage至少一项：
  \[
  \mathrm{CI}_{95\%,lower}>0;
  \]
- 完美信息价值回收率：
  \[
  \rho\ge0.25,
  \quad
  \mathrm{CI}_{lower}>0;
  \]
- probe-window增量频差≤0.02Hz；
- false optimistic certificate≤1%；
- 候选集合直径平均降低≥40%。

### 边界
- development得出的边界在validation中：
  - no-probe false-positive≤5%；
  - positive-region precision≥70%；
  - boundary classification有置信区间；
- Plant B至少正确复现“正区域或安全放弃”中的一种，不再要求每个Plant都强制正改善。

## 5. 决定性负结果

若在有文献/设备依据的参数范围内：

\[
\max_{q\in\mathcal Q_{\rm safe}}V_q\le0
\]

占全部设计域，或正值区域不能在独立validation中复现，则论文改为：

> **安全主动能力辨识的价值边界与不可获益区域**

并停止继续开发控制器。
