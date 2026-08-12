# Codex唯一总Goal：方向5价值信息边界与选择性VOI-ACCR-MPC

## 命名

```text
方向5 / DIRECTION5 / direction5
```

## 论文目标

完成：

> 黑箱IBR能力信息的控制价值边界，以及只在正价值区域探测、在零价值区域严格退化为合同MPC的选择性VOI-ACCR-MPC。

## 必须阅读

```text
research/direction5_voi_boundary_final/
```

下全部文件。

## 执行方式

不要频繁询问用户。围绕三个宽里程碑连续科研：

1. 精确价值边界引擎；
2. 选择性策略和独立validation；
3. final/边界确认和论文。

## 决定性修复

必须：

1. 冻结当前启发式VOI-ACCR负结果；
2. 不再使用当前heuristic gross/cost公式作为正式VoI；
3. 不再用固定负荷幅值定义worthwhile；
4. 将Oracle称为注册控制器族完美信息比较，不作全局ceiling；
5. 使用frequency/ACE/tie均非零且物理归一化的固定目标；
6. 实现式(22)–(28)的perfect-information upper bound、posterior partition和actual net VoI；
7. 探测按物理时长归一化，2s/4s分别离散；
8. 探测成本使用完整闭环反事实，不只使用q的L1；
9. false optimistic certificate≤1%；
10. no-probe区域严格退化为同一合同MPC；
11. Plant B不强制正改善；若边界判断为无价值，安全放弃视为正确；
12. 每个validation cell有独立重复seed；
13. probe-window频率指标只在匹配窗口计算；
14. normal1h至少6条profile；
15. 普通控制器禁止读取true capability、true load和future event；
16. final后禁止调参；
17. 不删除失败、不扩大事故制造正区、不修改统计规则。

## 自主探索

在development内可以：

- 增加safe probe库；
- 改进边界求解算法；
- 自适应采样；
- 优化缓存和并行；
- 使用保守lookup；
- 在三组预注册目标偏好下做敏感性；
- 最多两次返回development并使用新validation split。

不得无限尝试配置直到碰巧显著。

## Git

证据里程碑之前：

```text
禁止git add/commit/tag/push
```

只用scratch和progress文件。

## 成功和终止

### Positive
- 非空正值区域在独立validation复现；
- 正区实际净收益CI下界>0；
- value recovery≥25%且CI下界>0；
- 全场景安全非劣；
- 零值区安全放弃。

### Boundary-negative
- 经过完整设计域和两次独立validation，正值区域为空或不可复现；
- 形成无探测/不可获益边界论文。

两者都算项目完成。禁止继续创建新Phase。

## 最终ZIP

```text
DIRECTION5_VOI_BOUNDARY_SINGLE_REVIEW_PACKAGE.zip
```

小于512MB，符合 `08_FINAL_REVIEW_PACKAGE_SPEC.md`。

最终状态只允许：

```text
PAPER_READY_POSITIVE_VALUE_REGION
```

或：

```text
PAPER_READY_NO_PROBE_BOUNDARY
```

或在无法形成论文证据时：

```text
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```
