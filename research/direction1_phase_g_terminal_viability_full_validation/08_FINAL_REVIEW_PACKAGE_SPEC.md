# 最终审查包规范

文件名：

```text
DIRECTION1_PHASE_G_TERMINAL_VIABILITY_FULL_VALIDATION_SINGLE_REVIEW_PACKAGE.zip
```

大小：`<512 MB`。

必须包含：

```text
00_README/
01_SCIENCE/
02_LITERATURE/
03_MODEL/
04_METHOD/
05_THEORY/
06_SOURCE/
07_CONFIG_ENV_SOLVERS/
08_TESTS_VERIFICATION/
09_EXPERIMENT_DESIGN/
10_RAW_RESULTS/
11_SUMMARY_TABLES/
12_FIGURES/
13_FAILURES/
14_PAPER_ANALYSIS/
15_REPRODUCIBILITY/
16_GIT_MANIFEST/
17_FINAL_STATUS/
```

关键新增材料：

- Phase F G5重分类；
- 全局/本地不确定性分解；
- observer/load误差；
- sustainable/bridge/infeasible manifest；
- static feasibility和bridge energy；
- terminal RPI/RCI；
- bridge certificates；
- 修订CDSR公式—代码映射；
- 实际BESS功率和能量预测审计；
- closed-loop G5/G6结果；
- solve build/solver time；
- Plant A/B；
- known/OOD；
-所有失败；
-审查包感知的minimal replay；
-无cvxpy的certificate verification入口；
- manifest/SHA256/Git clean。

大小控制：所有episode保留控制周期轨迹；失败、代表性和Plant B保留细步轨迹；其余细步轨迹可由seed/config重生；使用Parquet+Zstd。
