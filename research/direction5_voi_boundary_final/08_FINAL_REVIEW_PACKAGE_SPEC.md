# 最终审查包规范

## 目录

```text
00_README/
01_AUDIT/
02_SCIENCE/
03_LITERATURE/
04_MATHEMATICS/
05_BOUNDARY_ENGINE/
06_METHOD/
07_THEORY/
08_SOURCE_ENV/
09_TESTS/
10_DESIGN_SPACE/
11_DEVELOPMENT/
12_VALIDATION/
13_FINAL_OR_CONFIRMATION/
14_RAW_RESULTS/
15_SUMMARY_TABLES/
16_FIGURES/
17_FAILURES/
18_PAPER_DRAFT/
19_REPRODUCIBILITY/
20_GIT_MANIFEST/
21_FINAL_STATUS/
```

## 必须包含

- 当前启发式VOI负结果冻结；
- 正式VoI数学推导；
- no-probe theorem；
- exact/posterior boundary engine；
- design-space来源；
- 全部采样点，包括负值；
- adaptive sampling轨迹；
- period-normalized probe；
- selective controller；
- Plant A/原生Plant B；
- validation_1/validation_2/final防火墙；
- 全部episode/cycle结果；
- boundary classification；
- value recovery；
- no-probe equivalence；
- probe-window指标；
- solver日志；
-失败案例；
-论文草稿；
-完整源码、环境、manifest和SHA256；
-唯一最终状态。

## 大小控制

- Parquet+Zstd；
- 轨迹float32；
- 价值/证书float64；
- 删除cache、env、许可证和重复checkpoint；
- 保留全部边界采样和不利结果。

## 复现

fresh extract必须运行：

```bash
python 19_REPRODUCIBILITY/verify_manifest.py
python 19_REPRODUCIBILITY/reproduce_minimal.py
```

完整重跑命令必须能够重新计算：

- 小型boundary map；
- no-probe theorem check；
- selective validation摘要。
