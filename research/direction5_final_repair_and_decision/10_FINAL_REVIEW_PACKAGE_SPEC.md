# 最终审查包规范

## 文件名

```text
DIRECTION5_FINAL_REPAIR_AND_DECISION_SINGLE_REVIEW_PACKAGE.zip
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

-Phase I更正；
-科学问题、假设、材料性；
-≥60篇文献和创新矩阵；
-完整Plant A/原生Plant B；
-负荷观测器和set-membership estimator；
-contract/online双层能力；
-DCSV-CR-MPC；
-所有真实滚动基线；
-理论与可重算证书；
-dev/validation/final manifests；
-全部episode和control-cycle结果；
-所有失败和solver日志；
-known/OOD/contract violation；
-normal1h；
-消融/敏感性/鲁棒性；
-论文级图表；
-supported/unsupported claims；
-Git/manifest/SHA256；
-唯一最终状态。

## 大小控制

- Parquet+Zstd；
-轨迹float32；
-统计/证书float64；
-删除cache/env/license/重复checkpoint；
-保留所有失败、全部控制周期轨迹和支持结论的原始数据。

## Fresh extract

必须在新目录运行：

```bash
python 15_REPRODUCIBILITY/verify_manifest.py
python 15_REPRODUCIBILITY/reproduce_minimal.py
```

依赖缺失时必须给出明确环境安装命令，不得只返回模糊subprocess错误。
