# 最终实验和统计协议

## 数据分割
```text
development: 0–29
validation: 30–59
final: 100–159
```

## 因素独立
manifest必须显式列出所有因素，禁止seed取模混杂。

## 实验规模下界
### Plant A validation
每个：
```text
mechanism × SG tension × period
```
至少10个paired seeds。

### Plant B validation
每个mechanism至少8个paired scenarios。

### Normal
每种方法至少6条真实1h net-load profiles。

## 指标
- success-first；
-frequency/RoCoF/IAE/RMS/terminal；
-ACE/tie/terminal/settling；
-SoC/energy/mileage/reserve；
-estimator coverage/false optimism；
-solver/restoration/fallback；
-computation；
-contract violation。

## 统计
- development-only选择；
-validation固定；
-final单次；
-seed/scenario cluster bootstrap；
-paired failure table；
-failure-aware sensitivity；
-known/OOD分开；
-multiple comparison correction。

## 成功Gate
- success drop≤2pp；
- 2/3核心指标改善≥8%，CI lower>0；
-terminal recovery不劣；
-hard violation=0；
-unsolved≤0.1%；
-fallback≤1%；
-p99<0.5Ts；
-Plant A/B方向一致；
-normal1h为真实仿真；
-final不回调。
