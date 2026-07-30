# CODEX GOAL — Phase B2 Scientific Hardening

在当前 `d5_hidden_mode_frequency_from_scratch` 仓库中，建立独立分支 `phase-b2-scientific-hardening`，严格按照本目录所有规范完成 Phase B2。

## 本轮唯一目标

修正 Phase B1 的统计与判决错误，建立具有物理含义的两区域补充/二次频率控制模型、物理化黑箱 BESS/IBR Plant B、可信的多动作 exact nonlinear NMPC Oracle，以及 control-relevant regime 的可辨识性审计，从而判断该科学问题是否真实、具有控制价值、主要瓶颈是什么。

## 必须完成

1. 冻结 Phase B1 基线，旧结果和 hash 不得覆盖。
2. 修正 bottleneck decision：无 active trigger 时必须输出 INCONCLUSIVE。
3. 修正效果量：禁止使用逐 episode 相对比率平均作为主要估计量。
4. failure 采用 success-first，不能从主要材料性分析中静默排除。
5. 总资源价值同时包含 SG 与 IBR，不得只用 SG mileage。
6. 保留 Plant A 作为 regression；新增两区域 Plant B。
7. 固定本地一次调频，上层只控制 supplementary/secondary commands。
8. SG 建模真实 reserve 与 mechanical GRC。
9. Plant B 包含 command delay、power state、headroom、SoC/energy、efficiency、power/ramp limit、service availability 和 held-out OOD。
10. 实现 O0/O1/O2，O3 可选；O2 必须使用多动作 nonlinear NMPC，不得使用 15 个单动作网格代替。
11. 定义 control-relevant regime distance 和 control-critical window。
12. 完成 load-only、regime-only、before/coincident/after、gradual、recovery、OOD 审计。
13. 使用预注册 validation/final seeds；final 不得调参。
14. 所有失败、超时、不可行和缺失必须保留。
15. 本轮结束后只给出科学判决，未经外部评审不得继续实现下一 proposed controller。

## 禁止

- 普通 controller 读取 true regime、SoC 或内部参数；
- 将 evaluation-only Oracle 伪装成可部署方法；
- 在无 trigger 时强制选择最大分数；
- 用 final test 调参；
- 通过削弱基线制造优势；
- 删除失败 episode；
- 仅凭 SG mileage 宣称成本收益；
- 将单区域 0.5 s 集中控制直接称为标准 AGC；
- 在 O2 仍是单动作常值 shooting 时称为 exact optimal Oracle。

## 最终输出

生成：

`D5_PHASE_B2_SCIENTIFIC_HARDENING_REVIEW_PACKAGE.zip`

小于 512 MB，内容严格符合 `07_REVIEW_PACKAGE_SPEC.md`。完成后报告：

- ZIP 大小和 SHA256；
- Git commit/status；
- tests；
- corrected Phase B1 decision；
- Plant B validation；
- O2 Oracle quality；
- problem materiality；
- passive identifiability；
- final active triggers；
- 最终唯一结论；
- 最严重失败和局限。
