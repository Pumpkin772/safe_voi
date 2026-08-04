# 实验和最终裁决协议

## 1. 分割

```text
development: 0–29
validation: 30–59
final: 100–159
```

## 2. 因素独立manifest

列出：
- mechanism；
-SG tension；
-period；
-load area/sign/magnitude/time；
-capability change time；
-SoC；
-noise/jitter/dropout；
-Plant；
-domain；
-known/OOD；
-contract violation。

禁止seed取模同时决定多个因素。

## 3. 核心episode

```text
nominal warm-up >=60s
→ random unannounced capability change
→ independent load event
→ full rolling control 300–600s
```

## 4. Plant A规模

每个：
```text
mechanism × SG tension × period
```
至少10个validation paired seeds。

## 5. Plant B规模

每mechanism至少8个paired scenarios，并覆盖：
-两种运行点或SG tension；
-2/4s；
-positive/negative；
-known/OOD；
-capability change；
-部分noise/jitter。

## 6. Normal1h

-每方法≥6条；
-公开实测数据优先；
-若synthetic必须明确标注；
-完整滚动；
-anti-windup；
-频率品质Gate。

## 7. Gate

### 科学材料性
Oracle vs contract MPC在≥2机制、≥2 SG tension有价值。

### 方法
DCSV-CR vs contract MPC：
- success drop≤2pp；
-failure-aware不劣；
-2/3核心指标≥8%且hierarchical CI lower>0；
-terminal recovery不劣；
-hard violations=0；
-known in-contract backup≤1%；
-numerical failures≤0.1%；
-p99<0.5Ts；
-Plant A/B方向一致；
-normal1h无未解释大频偏。

### Contract violation
单独报告，不混入合同保证Gate。

## 8. 修复和终止

validation前允许两轮有依据修复。
仍失败：
```text
DIRECTION5_METHOD_NOT_SUPPORTED_AFTER_FINAL_CORRECTED_VALIDATION
```
停止，不运行final，不创建新阶段。

## 9. Final

只有validation Gate通过才运行。
final只运行一次，不回调算法。
