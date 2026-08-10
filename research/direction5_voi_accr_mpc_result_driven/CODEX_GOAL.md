# Codex唯一总Goal：方向5 VOI-ACCR-MPC

## 命名

```text
方向5 / DIRECTION5 / direction5
```

## 唯一目标

完成一篇能够投稿的、关于“主动能力认证何时值得”的方法论文。

唯一方法：

```text
VOI-ACCR-MPC
Value-of-Information-Gated Active Capability Certification and Recourse MPC
```

## 必须先读

```text
research/direction5_voi_accr_mpc_result_driven/
```

下全部文件。

## 执行方式

不要把任务拆成许多等待用户确认的阶段。围绕三个科研里程碑自主执行：

1. 集成正收益原型；
2. 独立validation；
3. final与论文。

在M1之前禁止任何Git提交、tag和push。只使用scratch和progress文件。

## 核心修复

1. 复现并冻结当前ACCR失败；
2. 删除固定±0.05 BESS探测基准；
3. 探测必须围绕当前合同MPC最优分配；
4. 删除“没有证书就探测”的逻辑；
5. 建立decision relevance和VoI门；
6. 只在预计净收益为正时探测；
7. 探测不值得时严格退化为合同MPC；
8. 防止重复探测，加入cooldown、被动续期和change reset；
9. 完整闭环评价探测，不用单次局部安全代替集成效果；
10. 证书有效期内使用认证能力；新变化时撤销并退回合同MPC；
11. 普通控制器禁止读取true capability、true load和future event；
12. 所有MPC必须真实滚动；
13. Plant A与原生Plant B均需验证；
14. normal1h必须真实仿真。

## 自主探索

在development中可以自动搜索：

- probe序列；
- 幅值；
- VoI阈值；
- decision-relevance阈值；
- cooldown；
- certificate validity；
- estimator window；
- MPC horizon；
- MPC weights。

不得搜索或修改：

- 物理事故范围；
- validation/final场景；
- 成功标准；
- final seeds；
- 统计规则。

不要在一个配置失败后停止。持续诊断和探索，直到：

### 正面目标
满足 `03_RESULT_DRIVEN_RESEARCH_PLAN.md` 中M1和M2的论文Gate；

或：

### 决定性负目标
在完整预注册设计空间内证明没有非空安全正VoI区域，或独立validation反复否定正收益。

## Git规则

- M1之前：禁止提交；
- M1通过：允许第一次提交；
- M2通过：允许第二次提交；
- Final完成：允许最终提交和tag；
- 若负结果：证据闭合后只提交一次。

## 科研诚信

用户希望获得合理正面结果，但不得：

- 删除失败；
- 降低标准；
- 修改final；
- 使用validation直接调参；
- 扩大事故制造Oracle gap；
- 只报告最好配置；
- 强行把预测结果写成事实。

## 最终输出

```text
DIRECTION5_VOI_ACCR_MPC_SINGLE_REVIEW_PACKAGE.zip
```

小于512MB，符合 `05_OUTPUT_PACKAGE_SPEC.md`。

最终状态只允许：

```text
PAPER_READY_WITH_BOUNDED_CLAIMS
```

或：

```text
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```
