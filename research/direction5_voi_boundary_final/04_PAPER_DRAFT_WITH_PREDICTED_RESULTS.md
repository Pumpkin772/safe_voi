# 论文初稿：黑箱IBR能力信息的控制价值边界

> 所有带 `[PREDICTED]` 的内容是预注册方向性预测，不是当前事实。Codex必须用实际结果替换；不得通过调参强行匹配。

## 暂定题目

### 中文
**多区域二次频率控制中黑箱IBR能力信息的价值边界与选择性安全探测**

### 英文
**Value-of-Information Boundaries and Selective Safe Probing of Black-Box IBR Capability in Multi-Area Secondary Frequency Control**

## 摘要草稿

黑箱逆变器型资源的可交付功率、爬坡和执行延迟可能在运行中发生变化。已有安全探测和自适应控制方法通常假设额外信息始终值得获取，但在二次频率调节中，探测本身会改变同步机与IBR之间的动态责任，且完美能力信息的闭环价值可能远小于探测代价。本文研究“何时探测值得”这一问题。首先，在统一的多区域频率、ACE、联络线、资源功率、爬坡、延迟和能量约束下，定义合同鲁棒控制代价、注册控制器族的完美信息代价、探测观测管、可能后验集合和探测后追索代价。由此建立状态–不确定性相关的净价值函数，并证明：若安全探测后的完美信息下界仍不优于合同基线，则任何因果后验策略都不能获得正净收益。其次，提出选择性VOI-ACCR-MPC，仅在净价值为正的区域执行按物理时长归一化的SG–IBR分配探测，在其余区域严格退化为合同MPC。最后，通过非线性两区域模型和原生ANDES多机模型刻画价值边界，并验证正值区域的净收益以及零值区域的安全放弃。

`[PREDICTED]` 当前证据表明正值区域可能较窄：2s控制周期、较大功率/爬坡不确定性、较高ACE/联络线敏感度和较低测量噪声更可能出现正值；4s、delay-only、小完美信息差和高噪声大多属于无探测区域。预期选择性策略的全局平均性能接近合同MPC，而在正值区域对ACE或联络线获得约0.5%–3%的净改善并回收25%–60%的注册完美信息价值。若正值区域在独立validation中为空，本文将报告安全主动能力探测的不可获益边界。

## 1. 引言

### 1.1 工程背景
- IBR模型与实际能力不一致；
- 控制中心可能只有外部测量；
- 能力信息可能有价值，也可能不值得主动获取；
- 多区域系统不仅关心频率，还关心ACE和联络线责任。

### 1.2 文献缺口
- 安全数据驱动二次控制已有持续激励；
- 主动探索MPC已有一般双重控制；
- 功率系统探测已有信号设计；
- 黑箱IBR多模式建模已有；
- 缺少针对多区域频率责任的“探测价值边界”和选择性放弃理论。

### 1.3 贡献
1. 注册控制器族内的完美信息价值和安全探测净值定义；
2. 无探测区域定理；
3. 正值区域与边界；
4. 选择性VOI-ACCR-MPC；
5. period-normalized probe和完整闭环代价；
6. Plant A/Plant B边界验证。

## 2. 模型
采用统一离散增广模型、实际能量状态、delay pipeline和合同能力。

## 3. 价值边界理论
使用式(4)–(31)。

## 4. 选择性控制
使用式(33)–(35)。

## 5. 数值算法
- 有限候选与观测管；
- probe后验分区；
- adaptive boundary sampling；
- offline map/online exact small-library；
- conservative interpolation。

## 6. 实验

### 6.1 基线
- contract MPC；
- current heuristic VOI；
- fixed safe probe；
- selective exact VOI；
- perfect-information comparator；
- passive adaptive MPC。

### 6.2 设计域
- SG reserve；
- period；
- load/ACE；
- power/ramp/delay spread；
- noise；
- SoC；
- Plant。

### 6.3 结果
- VPI map；
- safe probe upper-bound map；
- exact net VoI map；
- positive/no-probe region；
- boundary uncertainty；
- closed-loop validation；
- failure cases；
- computation time。

## 7. 预期结果

| 结果 | 方向性预测 |
|---|---|
| 正值区域占比 | 较小，约5%–25%的物理设计域 |
| 2s vs 4s | 2s更可能正值；4s多为无探测 |
| power/ramp | 比delay-only更有价值 |
| positive-region ACE/tie净改善 | 0.5%–3%，但CI应为正 |
| perfect-info value recovery | 25%–60% |
| no-probe false positive | ≤5% |
| no-probe性能差异 | ≤1% |
| probe-window增量频差 | ≤0.02Hz |
| hard violations | 0 |
| global average | 接近合同MPC，不追求大幅改善 |
| Plant B | 可能主要验证安全放弃；若存在正区则验证方向 |

## 8. 失败路径

如果：
- exact boundary计算显示全部安全probe净值≤0；或
- development正区在两个独立validation中均不复现；

则论文题目改为：

> **安全主动能力探测在多区域频率控制中的不可获益边界**

仍需给出理论边界、完整图谱和真实负结果，随后终止方向5。
