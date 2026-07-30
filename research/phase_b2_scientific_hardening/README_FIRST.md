# README_FIRST — Phase B2 科学模型加固与证伪

本包用于继续审查并加固“黑箱 IBR 隐含状态/能力变化下的频率控制”方向。

**本阶段不允许直接继续调旧 SD-BMPC，也不允许先实现新的复杂控制器。**
第一目标是修正 Phase B1 的统计与判决错误，建立具有物理含义的验证对象和可信的非线性 Oracle，并判断该科学问题在合理电力系统场景中是否真实、可辨识、具有控制价值。

建议阅读顺序：

1. `00_EXPERT_REVIEW_AND_DECISION.md`
2. `01_PHASE_B2_PROJECT_PLAN.md`
3. `02_ANALYSIS_CORRECTION_SPEC.md`
4. `03_PHYSICAL_MODEL_AND_SERVICE_SCOPE_SPEC.md`
5. `04_STRONG_ORACLE_SPEC.md`
6. `05_CONTROL_RELEVANT_REGIME_SPEC.md`
7. `06_EXPERIMENT_AND_DECISION_PROTOCOL.md`
8. `07_REVIEW_PACKAGE_SPEC.md`
9. `CODEX_GOAL.md`

参考实现：

- `reference/statistics_reference.py`
- `reference/phase_b2_config_template.yaml`
- `reference/required_output_tables.md`
