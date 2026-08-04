# 方向5最终科学范围

## 1. 核心对象

黑箱IBR的“内部模式”不是目标。研究对象是控制中心可使用的外部可交付集合：

\[
\mathcal C_k
=
\{P_k^+,P_k^-,R_k^+,R_k^-,\mathcal D_k\}.
\]

能量由公共SoC和设备参数直接计算：

\[
E_k=E_{\rm rated}SOC_k.
\]

availability不再作为单独不可观变量，而通过可交付power/ramp集合体现。

## 2. 两类能力信息

### 合同保证能力
\[
\mathcal C_{\rm contract}
\]

用于硬约束和安全声明。

### 在线可用能力
\[
\mathcal C_{\rm online}
\]

用于性能改善。若其可信度不足，控制器必须退回合同能力，而不是把估计值当作安全保证。

## 3. 合同违约

若：
\[
\mathcal C_{\rm true}\not\supseteq\mathcal C_{\rm contract},
\]
定义为contract violation。

在检测完成前，不得声称依赖该资源的命令一定可执行。方法只能依赖SG/其他备用在检测时间内吸收风险。

## 4. 可持续/桥接/不可行

- sustainable：长期不依赖电池净放电；
- bridge：在慢速备用到达前需要有限能量；
- infeasible：注册能力下无法满足功率、爬坡或能量。

该分类必须在控制器评价前锁定。

## 5. 最终贡献边界

可能贡献：

1. 实际出力已知输入下的负荷–执行能力分离；
2. 合同下界与在线性能能力的双层语义；
3. 多区域ACE责任下的DCSV-MPC；
4. abrupt contract violation的不可保证边界；
5. sustainable/bridge/infeasible条件性理论。

不得声称各组件单独首创。
