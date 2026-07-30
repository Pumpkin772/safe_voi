# 最终统一审查压缩包规范

## 1. 文件名与大小

```text
DIRECTION5_PHASE_C_FULL_REBUILD_AND_METHOD_COMPLETION_SINGLE_REVIEW_PACKAGE.zip
```

必须小于512MB。

## 2. 必须目录

```text
00_README/
01_SCIENCE/
02_LITERATURE/
03_MODEL_AND_THEORY/
04_SOURCE/
05_CONFIG_AND_ENV/
06_TESTS_AND_VERIFICATION/
07_EXPERIMENT_DESIGN/
08_RAW_RESULTS/
09_SUMMARY_TABLES/
10_FIGURES/
11_FAILURES/
12_REPRODUCIBILITY/
13_GIT_AND_MANIFEST/
14_FINAL_STATUS/
```

## 3. 必须文件

### 00_README

- `README_FIRST.md`
- `HOW_TO_REVIEW.md`
- `PACKAGE_INDEX.csv`

### 01_SCIENCE

- `SCIENTIFIC_QUESTION.md`
- `HYPOTHESES_AND_FALSIFICATION.md`
- `SUPPORTED_AND_UNSUPPORTED_CLAIMS.md`
- `SCIENCE_GATE_DECISIONS.json`

### 02_LITERATURE

- `LITERATURE_REVIEW.md`
- `LITERATURE_MATRIX.csv`
- `NOVELTY_COMPARISON_TABLE.md`
- `SOURCE_BIBLIOGRAPHY.bib`
- `SEARCH_LOG.md`

### 03_MODEL_AND_THEORY

- `FULL_MATHEMATICAL_MODEL.md`
- `FORMULA_CODE_MAP.csv`
- `PARAMETER_SOURCES.csv`
- `ASSUMPTIONS_AND_LIMITATIONS.md`
- `THEOREMS_AND_PROOFS.md`
- `NUMERICAL_CERTIFICATE_INDEX.csv`

### 04_SOURCE

- 完整、可安装的 `src/`、`scripts/`、`tests/`；
- 不能只提供patch；
- 删除缓存和无关旧代码副本。

### 05_CONFIG_AND_ENV

- 全部resolved YAML；
- `environment.yml`、`requirements-lock.txt`；
- Python、OS、CPU/GPU、求解器版本；
- 不包含许可证和密钥。

### 06_TESTS_AND_VERIFICATION

- pytest XML/TXT；
- coverage；
- unit audit；
- RoCoF analytical check；
- energy conservation；
- dt convergence；
- no-leakage；
- Plant A/B cross-validation；
- solver validation。

### 07_EXPERIMENT_DESIGN

- `EXPERIMENT_MATRIX.csv`
- `SEED_SPLIT.json`
- `FINAL_PROTOCOL_LOCK.json`
- baselines/ablations说明。

### 08_RAW_RESULTS

- 所有逐episode指标；
- 所有失败和求解日志；
- 每个episode的control-grid原始轨迹；
- 所有失败episode的细步轨迹；
- 每个场景至少3个代表细步轨迹；
- 图表对应数据；
- 使用Parquet/Zstd。

### 09_SUMMARY_TABLES

- success-first；
- scene-balanced；
- paired bootstrap；
- known/OOD；
- materiality；
- identifiability；
- method comparison；
- Pareto；
- compute time。

### 10_FIGURES

- PNG/PDF/SVG论文图；
- 每张图有源数据和生成脚本；
- 不要只放图片。

### 11_FAILURES

- `FAILURE_LEDGER.csv`
- `WORST_CASES.md`
- `SOLVER_FAILURES.csv`
- `NEGATIVE_RESULTS.md`
- 所有未解决异常。

### 12_REPRODUCIBILITY

- `RUN_ALL.md`
- `reproduce_minimal.*`
- `reproduce_all.*`
- `regenerate_figures.*`
- 从空环境安装和运行记录。

### 13_GIT_AND_MANIFEST

- commit、branch、status、diff；
- 全文件SHA256；
- 包SHA256；
- 文件大小清单；
- 数据裁剪说明。

### 14_FINAL_STATUS

- `FINAL_RESEARCH_STATUS.md`
- `FINAL_DECISION.json`
- `PAPER_OUTLINE.md`
- `RESULTS_INTERPRETATION.md`
- `NEXT_UNRESOLVED_RISKS.md`

## 4. 大小控制

必须删除：

- `.git/`
- Conda环境
- `__pycache__`
- `.pytest_cache`
- solver临时文件
- 重复结果
- 大模型checkpoint
- 无用中间数组

不得删除：

- 逐episode指标；
- 失败日志；
- 支撑结论的原始轨迹；
- 配置和seed；
- 图表源数据；
- 源码和测试。

若仍超512MB：

1. Parquet+Zstd；
2. float64轨迹转float32，但指标保留float64；
3. 全细步轨迹只保留失败/代表/验证集，其余保留control-grid轨迹和可重生信息；
4. 在 `DATA_RETENTION_POLICY.md` 明确说明。

## 5. 最终状态枚举

```text
PUBLICATION_READY_WITH_STATED_SCOPE
PROMISING_BUT_NATIVE_VALIDATION_INCOMPLETE
METHOD_NOT_SUPPORTED_BY_EVIDENCE
PROBLEM_NOT_MATERIAL
STRUCTURALLY_UNIDENTIFIABLE_BUT_ROBUST_CONTROL_SUPPORTED
NEGATIVE_RESULT_COMPLETE
FATAL_IMPLEMENTATION_BLOCKER
```
