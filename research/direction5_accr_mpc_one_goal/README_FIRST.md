# 方向5：ACCR-MPC 一次性完整研究执行包

## 项目命名

```text
中文：方向5
英文标识：DIRECTION5
代码/目录标识：direction5
```

## 本包目的

本包建立在最新审查包：

```text
DIRECTION5_CLOSURE_CONFIRMATION_AND_MANUSCRIPT_SINGLE_REVIEW_PACKAGE.zip
```

的证据上。该包已经较可靠地证明：

1. 完美能力信息在部分功率/爬坡场景中对ACE和联络线责任具有有限价值；
2. 被动因果能力估计几乎没有产生可用剩余能力：
   - DCSV剩余能力仅在2/22,392个调用中激活；
3. 当前DCSV-CR-MPC没有超过合同MPC：
   - validation与confirmation均通过0/3核心指标Gate；
   - confirmation成功率下降7.48个百分点；
   - 1,171次fallback；
4. 所有正常1小时方法均未通过原频率品质Gate，需重建正常运行基准；
5. 当前负结果只针对冻结的被动估计–追索实现，不是对方向5科学问题的否定。

因此，下一步不再继续调被动DCSV-CR-MPC，也不盲目更换AI算法。唯一允许的新方法是：

> **ACCR-MPC：Active Capability Certification and Recourse Model Predictive Control**

中文：

> **主动能力认证–追索模型预测多区域二次频率控制**

其核心科学问题是：

> 当自然闭环数据不足以认证黑箱IBR的额外可交付能力时，能否利用对区域总SFR命令保持中性的安全分配探测，主动获得控制相关能力信息，并在不损害频率、ACE和联络线安全的前提下，回收部分完美能力信息价值？

本包是一个总Goal、九个内部阶段。Codex应连续执行，不在阶段之间等待用户重新发送指令。开发和validation允许有限、有依据的自动修复；final锁定后禁止调参。

最终只能输出：

```text
PAPER_READY_WITH_BOUNDED_CLAIMS
```

或：

```text
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```
