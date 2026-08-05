# 最新审查包专家裁决

## 一、可信部分

- 方向5的工程问题真实：黑箱IBR可交付能力可能偏离调度模型。
- Plant A、原生ANDES Plant B、actual-POI负荷观测和合同能力语义具有保留价值。
- 当前包已实现真实滚动MPC、失败保存、合同违约分离、final seed firewall和有限理论证书。
- 当前统计已修正旧阶段的逐episode相对比值错误，并将contract-only rolling MPC作为主要公平基线。

## 二、当前决定性结果

相对contract-only rolling MPC，在双方成功场景中：

```text
frequency peak：约 +0.23% 改善，置信下界<0
ACE IAE：约 +3.21% 改善，置信下界<0
tie RMS：约 -9.07%，即明显恶化
```

同时：

```text
proposed success rate下降约2.73个百分点
terminal recovery下降约3.64个百分点
known contract fallback约6.86%
Plant A方向为负，Plant B仅轻微正向
全部方法均未通过注册normal1h频率质量Gate
```

model-adaptive MPC和contract-only MPC总体优于DCSV-CR-MPC。当前DCSV-CR方法不构成正面性能贡献。

## 三、科学问题与方法的区分

- 当前能力知识对power/ramp下降在4/6小规模材料性cell中有价值；delay单独价值弱。
- 这只能说明真实能力信息可能有价值，不能说明当前被动在线估计能可靠实现该价值。
- 当前set-membership envelope非常保守，在线surplus使用弱；loss branch进一步压缩性能收益。
- 因此应终止DCSV-CR正面方法路线，而不是继续更换算法。

## 四、最终建议

当前方向5不适合继续追逐正面性能结果。下一轮只进行：

- 冻结方法的独立确认；
-  untouched final seeds确认；
- 失败机理、信息价值和合同安全边界分析；
- 负结果/边界论文草稿和代码基准归档。

若确认集与validation一致，方向5正式结束。若发现决定性代码错误，只允许修复该错误并重跑同一冻结方法一次；不得设计新算法。
