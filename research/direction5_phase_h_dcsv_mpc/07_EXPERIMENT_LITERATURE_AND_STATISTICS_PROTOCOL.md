# 文献、实验与统计协议

## 1. 数据分割

```text
development: 0–19
validation: 20–39
final: 100–159
```

final前禁止读取final结果。

## 2. 因素独立

显式列出：
- Plant；
- period；
- SG tension；
- mechanism；
- load magnitude/sign/area/time；
- capability change time；
- initial SoC；
- noise；
- jitter；
- dropout；
- delay；
- sustainable/bridge/infeasible；
- split。

不得由seed取模同时决定多个因素。

## 3. 场景

### Known
- load-only；
- capability-only；
- simultaneous；
- headroom/ramp/delay/energy/availability；
- 2/4s；
- 300–600s；
- 1h正常运行；
- repeated event。

### OOD
- combined capability；
- asymmetric power；
- continuous delay；
- slow drift；
- unseen SoC；
- unseen Plant B operating point；
- delayed recovery；
- mixed load/capability.

## 4. 指标

### Science
- materiality；
- load/capability confusion；
- capability set coverage；
- update time；
- control-critical time；
- domain classification accuracy。

### Control
- success-first；
- frequency/RoCoF；
- ACE/tie；
- terminal recovery；
- resource mileage/energy；
- hard violations；
- bridge success；
- physical infeasible certificates。

### Solver
- status taxonomy；
- residual；
- time；
- restoration；
- fallback；
- consecutive fallback。

## 5. 统计
- development-only selection；
- scenario-balanced；
- paired failure；
- both-success continuous metrics；
- failure-aware sensitivity；
- seed-cluster bootstrap；
- confidence lower bound for coverage；
- known/OOD separate；
- multiple-comparison correction。

## 6. 文献
正式期刊和官方标准/报告为主；arXiv只用于最新趋势，不能单独支撑核心创新声明。
