# Codex唯一总Goal：方向5 Phase I最终科学收敛

## 0. 命名
本项目统一称为：
```text
方向5 / DIRECTION5 / direction5
```

## 1. 先读
完整阅读：
```text
research/direction5_phase_i_final_convergence/
```

其中：
```text
01_MASTER_EXECUTION_PLAN.md
07_GATES_FAILURE_AUTO_REPAIR.md
09_FINAL_REVIEW_PACKAGE_SPEC.md
```
是约束性文件。

## 2. 连续执行
严格执行：
```text
I0 → I1 → I2 → I3 → I4 → I5 → I6 → I7 → I8
```

不得在内部阶段后等待用户再次发消息。

## 3. 核心任务
1. 冻结并纠正Phase H，不再使用其H7方法结论作为投稿证据；
2. 修复factor confounding、人工normal rows、held tail和Plant B surrogate；
3. 在真实完整闭环中加入nominal warm-up和随机时刻unannounced capability change；
4. 最终隐藏能力范围收缩为power/ramp/delay；
5. energy由公共SoC计算；availability折算进deliverability，不单独伪估计；
6. 明确contract guaranteed floor与online performance envelope；
7. 负荷观测器使用actual BESS POI power；
8. 使用因果set-membership/MHE建立deliverability set；
9. 实现完整滚动DCSV-MPC、真实SoC、delay pipeline、slow reserve和三域；
10. 所有叫MPC的基线必须真实滚动优化；
11. ordinary controller禁止读取true capability、true load、hidden parameter和future event；
12. 完成不可保证边界、合同下界鲁棒约束、可持续/桥接/不可行理论；
13. development/validation/final严格隔离；
14. final锁定后禁止调参；
15. 不得删除失败、降低标准、伪造normal profile或用surrogate冒充native Plant B；
16. I6失败后必须形成决定性负结果并停止，禁止再创建新Phase逃避结论。

## 4. 唯一终态
必须输出二者之一：
```text
PAPER_READY_WITH_BOUNDED_CLAIMS
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```

## 5. 最终ZIP
生成：
```text
DIRECTION5_PHASE_I_FINAL_CONVERGENCE_SINGLE_REVIEW_PACKAGE.zip
```
要求：
```text
size <512MB
```
内容严格符合：
```text
research/direction5_phase_i_final_convergence/09_FINAL_REVIEW_PACKAGE_SPEC.md
```

完成后报告：
- ZIP路径、大小、SHA256；
- Git commit/status；
- I0–I8 Gate；
- H1–H6；
- selected observer/estimator；
- best deployable baseline；
- Plant A/B；
- known/OOD；
- normal1h；
- solver/restoration/fallback；
- theory certificate；
-最严重失败与限制；
-最终研究状态。
