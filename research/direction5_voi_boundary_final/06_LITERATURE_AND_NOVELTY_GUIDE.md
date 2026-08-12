# 文献与创新性对比指南

Codex必须重新核验并补充正式来源。以下是必须比较的最近邻：

1. **Safe Data-Driven Secondary Control of Distributed Energy Resources**  
   IEEE Transactions on Power Systems, 2021, DOI: 10.1109/TPWRS.2021.3084440  
   已有：闭环安全数据驱动二次控制、持续激励。  
   区别：本文不主张持续激励，而研究状态相关的探测价值边界和主动放弃。

2. **Active Exploration in Adaptive Model Predictive Control**  
   IEEE CDC, 2020, DOI: 10.1109/CDC42340.2020.9304303  
   已有：集合成员不确定系统的主动探索和最坏代价。  
   区别：本文专门利用SG–IBR分配结构，评价多区域ACE/tie责任，并建立可操作的正/零价值区域。

3. **Probing Signal Design for Power System Identification**  
   IEEE Transactions on Power Systems, 2010, DOI: 10.1109/TPWRS.2009.2033801  
   已有：低幅探测和模式识别。  
   区别：本文优化的不是模型精度本身，而是闭环控制净价值。

4. **Learning to Model the Dynamics of Black-Box IBRs With Multiple Unknown Control Modes**  
   IEEE Transactions on Smart Grid, DOI: 10.1109/TSG.2025.3647551  
   已有：黑箱多模式建模。  
   区别：本文不恢复内部模式标签，而判断信息是否值得获取和使用。

5. 自适应控制分配、容错LFC、set-membership MPC、dual MPC、DeePC频率控制等。

## 不能声称
- 首次主动探测；
- 首次dual MPC；
- 首次黑箱IBR辨识；
- 首次安全二次控制；
- 首次多区域MPC。

## 可声称的潜在贡献
- 多区域频率责任下的控制价值边界；
- 无探测必要区域；
- 选择性放弃策略；
- period-normalized probe；
- exact posterior recourse value；
- 跨Plant边界验证。
