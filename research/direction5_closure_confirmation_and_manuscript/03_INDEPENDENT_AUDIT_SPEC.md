# 独立审计规范

## 必须复算
- ZIP/manifest/Git；
- paired failure table；
- both-success和failure-aware统计；
- scenario-balanced means；
- hierarchical bootstrap；
- solver denominator；
- normal1h；
- Plant direction；
- materiality cells；
- estimator coverage。

## 代码语义审计
- 所有MPC是真滚动；
- action commit；
- fallback分母；
- contract-only comparator；
- truth/future leakage；
- final seed未使用；
- contract violation分离；
-物理不可行分离。

## 允许修复
仅允许影响结论的确定性代码错误；修复必须：
- 有最小失败测试；
- 有前后结果差异；
- 不改变权重、场景、Gate和方法结构。
