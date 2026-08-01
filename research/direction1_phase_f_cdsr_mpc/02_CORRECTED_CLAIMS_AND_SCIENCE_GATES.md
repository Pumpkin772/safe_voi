# 纠正后的科学声明与 Gate

## 科学问题

在固定本地PFR和多区域SFR系统中，黑箱IBR的外部可用能力和执行延迟可能在未通知情况下变化。研究目标不是恢复OEM内部模式，而是：

1. 判断当前能力知识是否具有材料性控制价值；
2. 判断自然闭环或安全主动信号能否及时获得该知识；
3. 当及时辨识不可靠时，基于保证能力包络进行诊断无关的鲁棒责任分配。

## 假设状态

### H1：当前能力知识具有控制价值
Phase E 仅为初步支持。本轮必须以 development-only baseline selection、success-first 和 failure-aware 统计重新审计。

### H2：自然闭环数据足以支持及时能力集合更新
不得写“falsified”。正确表述：

```text
NOT_SUPPORTED_BY_THE_THREE_TESTED_PASSIVE_ESTIMATORS
UNDER_THE_REGISTERED_NATURAL_EXCITATION
```

### H3：安全主动激励可在不损害调频时提供及时信息
不得写“falsified”。正确表述：

```text
THE_REGISTERED_ALTERNATING_PROBE_WAS_NOT_SAFE_OR_COST_EFFECTIVE
```

### H4：CDSR-MPC能在保证能力包络下提高多区域频率控制
本轮核心可证伪假设。

### H5：注册模型和能力包络内可给出有限时域鲁棒约束证书，并在非空SG backup集下建立递归/切换安全边界
仅在F5证书通过后才能支持。

## Science stop rules

立即停止当前方法并输出负结果包，若发生任一情况：

1. 修正统计后H1在至少两个机制、两个SG tension上不成立；
2. 保证能力包络必然使BESS控制始终为零，且相对SG-only无可测价值；
3. Plant B中方向与Plant A系统性相反且无法由模型差异解释；
4. 非空SG robust backup set不存在；
5. 两轮合理修复后F6仍不能优于最佳可部署基线；
6. 任何改进依赖读取真能力、真负荷、未来事件或final调参。

## Claim boundary

最终可以声称的最高层级取决于证据：

- 无理论：经验鲁棒MPC；
- 有有限时域证书：registered-set finite-horizon robust constraint satisfaction；
- 有不变集和递归证明：recursive feasibility within certified initial set；
- 不得声称对任意OEM模式、任意延迟、任意能量状态安全。
