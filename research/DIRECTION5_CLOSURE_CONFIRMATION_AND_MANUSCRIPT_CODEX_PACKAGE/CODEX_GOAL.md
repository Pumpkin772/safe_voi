# Codex唯一总Goal：方向5最终确认、论文化与归档

请在当前真实Git仓库中连续执行C0→C1→C2→C3→C4→C5→C6，不要在阶段之间等待用户消息。

## 核心原则

1. 冻结当前DCSV-CR-MPC；不得设计新控制器或换算法。
2. 先独立复算当前审查包。
3. 只允许修复可复现的确定性代码/统计错误；不得调权重、改Gate或删场景。
4. 分析完美能力信息、在线能力信息和合同能力的价值差距。
5. 使用尚未消耗的final seeds作一次性确认；运行后禁止回调。
6. 用实际结果填充论文草稿，预测内容不得伪装成事实。
7. 结果不支持时形成负结果/边界论文和完整归档。
8. 不得创建新的Phase。

## 唯一终态

```text
DIRECTION5_NEGATIVE_RESULT_CONFIRMED_AND_ARCHIVED
```

或：

```text
DIRECTION5_BOUNDED_POSITIVE_RESULT_CONFIRMED
```

## 最终ZIP

```text
DIRECTION5_CLOSURE_CONFIRMATION_AND_MANUSCRIPT_SINGLE_REVIEW_PACKAGE.zip
```

小于512MB，符合 `04_FINAL_PACKAGE_SPEC.md`。

完成后报告：
- ZIP路径、大小、SHA256；
- Git commit/status；
- 当前包复算一致性；
-是否修复bug；
-validation与confirmatory结果；
-信息价值分解；
-估计器激励/覆盖；
-surplus与fallback机制；
-Plant A/B；
-normal1h；
-论文路线；
-唯一终态。
