# 方向5论文草稿与预期结果

> 所有 `[PREDICTED]` 内容是基于当前模型和validation结果的方向性预测，不是事实，也不是Codex必须调参达到的目标。确认实验必须原样替换这些内容。

## 暂定标题

**Limits of Causal Online Deliverability Adaptation for Black-Box IBRs in Multi-Area Secondary Frequency Control**

## 摘要草稿

黑箱逆变器型资源的可交付功率、爬坡和延迟可能偏离调度模型。本文研究仅利用公共测量分离净负荷和设备执行失配，并比较合同安全MPC、公共I/O自适应MPC、完美能力Oracle以及合同–在线双层DCSV-CR-MPC。理论上，若设备能力在命令发出前无预警跌破所有已知正下界，任何因果控制器都无法保证同瞬间命令可执行。实验在两区域非线性模型和原生ANDES模型中评估能力信息的材料性、在线可辨识性和控制价值。

`[PREDICTED]` 当前结果表明，完美功率/爬坡能力知识在部分低备用场景具有材料性，但因果在线能力集合在自然闭环数据中较宽，DCSV-CR-MPC相对合同MPC没有稳定的性能增益，并引入更高fallback。预计独立确认集将复现这一结论。本文因此强调合同能力、在线性能能力和合同违约的边界，而不声称提出更优控制器。

## 预期确认结果

| 项目 | 当前validation事实 | 确认集预期 |
|---|---:|---:|
| DCSV vs contract frequency | +0.23%，CI跨0 | 约-3%至+5% |
| DCSV vs contract ACE | +3.21%，CI跨0 | 约-5%至+8% |
| DCSV vs contract tie | -9.07%，CI全负 | 继续不利或接近0 |
| success差 | -2.73个百分点 | 约-5至0个百分点 |
| known fallback | 6.86% | 约3%–10% |
| Plant A方向 | 负 | 预计仍负或接近0 |
| Plant B方向 | 轻微正 | 预计小幅、统计不显著 |
| power/ramp perfect info | 有材料性 | 预计保留 |
| delay perfect info | 弱 | 预计仍弱 |
| normal1h | 全部方法失败 | 预计暴露profile/闭环边界，不作为正面结果 |

## 论文结构

1. 引言与工程背景；
2. 科学问题与信息边界；
3. 合同能力、在线能力与不可能性定理；
4. Plant A/Plant B和比较方法；
5. 完美信息价值与在线信息价值；
6. validation与confirmatory结果；
7. 失败机理与工程含义；
8. 结论与停止边界。

## 可证伪结论

若确认集显示DCSV-CR在成功率不降低的同时，相对contract MPC在至少两个核心指标上达到预注册改善且Plant A/B一致，则可以形成有限正面论文。

否则，应形成负结果/边界论文或技术报告，并正式终止方向5。
