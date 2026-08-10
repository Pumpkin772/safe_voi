# Codex唯一总Goal：方向5 ACCR-MPC

## 0. 命名
```text
方向5 / DIRECTION5 / direction5
```

## 1. 阅读
完整阅读：

```text
research/direction5_accr_mpc_one_goal/
```

下全部文件。

## 2. 连续执行
严格按：

```text
A0 → A1 → A2 → A3 → A4 → A5 → A6 → A7 → A8
```

连续完成，不得在阶段间等待用户再次发消息。

## 3. 唯一方法
```text
ACCR-MPC
Active Capability Certification and Recourse MPC
```

禁止临时改为RL、普通随机探测、另一个MPC或新Phase。

## 4. 核心要求

1. 冻结并保留历史DCSV-CR负结果；
2. 先修复normal1h基准平台；
3. 重验perfect capability materiality；
4. 实现完整候选模型集合和被动基线；
5. 实现分配中性探测：
   ```text
   u_g = u_g0 - q
   u_b = u_b0 + q
   ```
   但不得称为实际功率中性；
6. 探测必须对所有候选和不交付分支通过frequency/ACE/tie/physical安全门；
7. 建立事件触发、探测库、信息指标、probe cost和有限有效期能力证书；
8. 实现合同分量、认证分量、探测分量和能力丢失追索；
9. ordinary controller禁止读取true capability、true load和future event；
10. development/validation/final使用全新seed防火墙；
11. 允许在development/validation内按预注册范围最多三轮自动修复：
    - probe library/trigger；
    - estimator window/noise；
    - MPC weight/horizon；
12. 不得为了预期结果删除数据、扩大事故或降低标准；
13. final锁定后禁止调参；
14. A6失败后终止，不创建新Phase；
15. 使用 `07_PAPER_DRAFT_WITH_PREDICTED_RESULTS.md` 作为论文模板；
    所有预测必须被真实结果替换，预测不是事实。

## 5. 唯一终态

```text
PAPER_READY_WITH_BOUNDED_CLAIMS
```

或：

```text
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```

## 6. 最终ZIP

```text
DIRECTION5_ACCR_MPC_SINGLE_REVIEW_PACKAGE.zip
```

小于512MB，严格符合：

```text
research/direction5_accr_mpc_one_goal/09_FINAL_REVIEW_PACKAGE_SPEC.md
```

完成后报告：
- ZIP路径/大小/SHA256；
- Git commit/status；
- A0–A8；
- H1–H6；
- selected probe policy；
- passive vs active identification；
- certificate coverage；
- probe safety/cost；
- value recovery；
- best baseline；
- Plant A/B；
- known/OOD；
- normal1h；
- solver/fallback；
- theory；
-最严重失败；
-最终状态。
