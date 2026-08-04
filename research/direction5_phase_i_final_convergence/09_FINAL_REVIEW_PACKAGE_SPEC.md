# 最终统一审查包规范

## 文件名
```text
DIRECTION5_PHASE_I_FINAL_CONVERGENCE_SINGLE_REVIEW_PACKAGE.zip
```

## 最大大小
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
- Phase H更正；
-科学问题、假设和不可保证边界；
-≥60篇文献与创新矩阵；
-完整模型、参数、单位、来源；
-Plant A和原生Plant B；
-load observer与deliverability estimator；
-contract floor语义；
-DCSV-MPC和真实基线；
-理论与可重算证书；
-完整dev/val/final manifests；
-全部episode指标；
-全部失败；
-控制周期轨迹；
-代表性和失败细步轨迹；
-known/OOD；
-normal1h；
-solver/fallback；
-论文级图表和源数据；
-supported/unsupported claims；
-完整源码、环境、Git、manifest和SHA256。

## 大小控制
- Parquet+Zstd；
-轨迹float32；
-统计/证书float64；
-删除cache/env/license/重复checkpoint；
-保留所有失败、全部控制周期轨迹和支持结论的原始数据。

## 复现
fresh extract中必须运行：
```bash
python 15_REPRODUCIBILITY/verify_manifest.py
python 15_REPRODUCIBILITY/reproduce_minimal.py
```

若依赖pyarrow等，minimal script必须先检查依赖并给出明确环境命令，不得以模糊subprocess失败结束。
