# CODEX GOAL — Direction 5 Phase B1 Scientific Bottleneck Audit

你正在继续一个已经完成 Phase 0–7 的黑箱 IBR 隐动态频率控制项目。

当前第二版审查包的工程实现已通过，但完整 SD-BMPC 尚未形成可投稿的科学优势：P 的总体 frequency IAE 约 1.1956 Hz·s，差于 B2 RLS-MPC 的约 1.0227 Hz·s，也差于 B0 LQI-only 的约 1.0435 Hz·s；模式识别和 OOD 结果较弱，且若干删减版本优于完整方法。

## 本轮唯一目标

完成一次严格、可审计的科学瓶颈分解，判断主导问题究竟是：

```text
PROBLEM_NOT_MATERIAL
MODEL_MISMATCH_DOMINANT
IDENTIFIABILITY_DOMINANT
CONTROL_DESIGN_DOMINANT
COMBINED:<primary>+<secondary>
```

本轮不得直接实现 CORA-MPC、双重控制或其他新 proposed method。完成瓶颈审计后必须停止，并生成审查包交给外部评审。

## 先完整阅读

```text
research/phase_b1_bottleneck_audit/
```

下的全部文件，然后严格执行 `01_PHASE_B1_PROJECT_PLAN.md`。

## 基线

目标 review ZIP SHA256：

```text
2e1c3bfc380c57172a5d96663a6ab90cf95b79511f60cefce73ce4c38e2f04a9
```

其 frozen Phase-6 commit：

```text
20f652f5f8b180a2518798d0ed85aa3f48212908
```

审查包记录的 Git status 非干净，因此先核对 diff，提交 Phase-A final baseline，并创建：

```text
tag: phase-a-final-reviewed-v2
branch: phase-b1-bottleneck-audit
```

旧结果不得覆盖。

## 必须完成

1. 新增 evaluation-only `B5 simulator-exact nonlinear oracle`；
2. 在 SG capability A/B/C 下完成 IBR value audit；
3. 完成 exact plant vs ARX 模型误差审计；
4. 完成被动闭环可辨识性审计；
5. 完成 load disturbance 与 mode change 来源混淆审计；
6. 完成 sticky prior、worst-mode cost、tightening、binary fallback 的单因素控制设计分解；
7. 输出 `BOTTLENECK_DECISION.md`；
8. 保留全部失败和负结果。

## 严格限制

- proposed/baseline runtime controller 禁止读取 true mode 或 truth parameters；
- B4/B5 只允许在 evaluation-only 路径；
- 禁止用旧 final 或新 final seeds 调参；
- 禁止通过临时削弱 B0/B2 制造 IBR 优势；
- SG Level A/B/C 必须预注册，不得根据结果改变；
- B5 不成功时必须报告失败，不得静默替换为 LQI；
- 不得只以测试通过宣布科学成功。

## 最终输出

生成：

```text
D5_PHASE_B1_BOTTLENECK_AUDIT_REVIEW_PACKAGE.zip
```

必须小于 512 MB，内容严格符合 `05_REVIEW_PACKAGE_SPEC.md`。

完成后报告：

- ZIP大小；
- SHA256；
- baseline和Phase B1 commit；
- 最终瓶颈结论；
- exact Oracle 是否证明 IBR 有实质价值；
- 最严重失败和未解决问题。
