# Gate和停止规则

## A0 审计一致性
核心统计可重算。否则终止为不可审计。

## A1 机制解释
至少解释90%的fallback和性能差异来源。

## A2 确认集锁定
方法、配置、统计和seeds哈希锁定后一次运行。

## A3 结果裁决

### 有限正面
只有同时满足：
- validation修正后和confirmatory均支持；
- success不降>2pp；
-至少2/3指标改善≥8%，CI下界>0；
- Plant A/B方向一致；
-hard violation=0；
才允许有限正面。

### 负结果确认
否则：
```text
DIRECTION5_NEGATIVE_RESULT_CONFIRMED_AND_ARCHIVED
```

## 禁止
- 新控制器；
- 新Phase；
- final后调参；
-删失败；
-放宽标准；
-用预测代替结果。
