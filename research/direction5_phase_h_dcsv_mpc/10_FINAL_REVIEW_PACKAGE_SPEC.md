# 最终统一审查包规范

## 文件名

```text
DIRECTION5_PHASE_H_DCSV_MPC_SINGLE_REVIEW_PACKAGE.zip
```

## 大小

```text
<512MB
```

## 目录

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

## 必须内容

- 科学问题和H1–H6；
- 文献与创新矩阵；
- Plant A/B完整公式；
- disturbance observer；
- capability estimator；
- sustainable/bridge/infeasible；
- load-dependent equilibria；
- global/local uncertainty sets；
- DCSV-MPC；
-全部真实MPC基线；
- terminal/bridge/infeasibility证书；
-全部源码、配置、环境、求解器；
-全部测试；
-final manifest；
-全部episode指标；
-控制周期轨迹；
-失败和代表性细步轨迹；
-solver/restoration/fallback日志；
-known/OOD、消融、敏感性、鲁棒性；
-论文级SVG/PDF/600dpi PNG及源数据；
-支持/不支持声明；
-Git、manifest、SHA256；
-final status。

## 大小控制

保留：
-所有episode控制周期轨迹；
-全部失败细步轨迹；
-每机制≥3个代表轨迹；
-Plant B关键轨迹；
-所有证书和源数据。

删除：
- cache；
- `__pycache__`；
- `.pytest_cache`；
-conda env；
-license；
-重复checkpoint；
-重复图片；
-不支撑结论且可由seed重生的全细步数据。

使用：
- Parquet+Zstd；
-float32轨迹；
-float64统计和证书。

## 复现

在全新临时目录运行：

```bash
python 15_REPRODUCIBILITY/verify_manifest.py
python 15_REPRODUCIBILITY/reproduce_minimal.py
```

二者必须通过。完整重跑命令另列。
