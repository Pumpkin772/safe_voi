# 最终统一审查包规范

## 文件名

```text
DIRECTION1_PHASE_F_CDSR_MPC_SINGLE_REVIEW_PACKAGE.zip
```

## 最大大小

```text
< 512 MB
```

## 必须目录

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

## 必须文件

### 00_README
- review顺序；
- package index；
-最小复现命令；
-完整复现命令。

### 01_SCIENCE
-科学问题；
-H1–H5；
-纠正后的Phase E状态；
-claim-evidence matrix；
-supported/unsupported claims。

### 02_LITERATURE
-聚焦新增文献；
-检索日志；
-创新对比；
-至少引用可靠正式来源；
-不得只用arXiv支撑核心创新。

### 03_MODEL
-完整Plant A/B公式；
-delay augmented model；
-capability envelope；
-误差集合；
-参数、单位、来源；
-equation-code map。

### 04_METHOD
-CDSR formulation；
-pseudocode；
-action transaction；
-feasibility restoration；
-baseline formulation；
-information boundary。

### 05_THEORY
- assumptions；
- backup set；
- certificate；
- proofs；
- reproduction script；
-不支持的理论声明。

### 06_SOURCE
-完整可安装源码；
-scripts；
-tests；
-pyproject。

### 07_CONFIG_ENV_SOLVERS
- environment.yml；
- requirements lock；
- solver versions；
- licenses excluded；
-all final configs。

### 08_TESTS_VERIFICATION
- unit/integration；
-action commit；
-delay vertices；
-energy；
-terminal set；
-dt convergence；
-Plant B；
-no leakage；
-coverage。

### 09_EXPERIMENT_DESIGN
-development/validation/final manifests；
-factor independence audit；
-final lock hash。

### 10_RAW_RESULTS
-所有episode指标；
-控制周期轨迹；
-失败和代表性细步轨迹；
-solver/restoration/fallback日志；
-Parquet+Zstd。

### 11_SUMMARY_TABLES
- success-first；
-paired failure；
-known/OOD；
-ablation；
-sensitivity；
-computation；
-Plant A/B；
-certificates。

### 12_FIGURES
- SVG/PDF；
-600dpi PNG；
-源数据；
-生成脚本。

### 13_FAILURES
-所有失败；
-异常；
-修复；
-未解决限制；
-不得删除最差结果。

### 14_PAPER_ANALYSIS
-贡献；
-结果叙事；
-审稿风险；
-论文结构；
-支持/不支持声明。

### 15_REPRODUCIBILITY
- review-package-aware reproduce_minimal；
- reproduce_all；
-runtime；
- deterministic checks。

### 16_GIT_MANIFEST
- commit；
-status；
-diff；
-file manifest；
-SHA256；
-large/duplicate report。

### 17_FINAL_STATUS
- gates；
-hypotheses；
-best baseline；
-known/OOD；
-final status；
-next-step boundary。

## 大小控制

保留：
-所有episode的控制周期轨迹；
-全部失败的细步轨迹；
-每类至少3个代表性细步轨迹；
-Plant B关键细步轨迹；
-图源数据。

删除：
- conda env；
- cache；
- solver license；
-重复checkpoint；
-重复图片；
-可确定性重生且不支撑结论的全部细步轨迹。

压缩：
- Parquet Zstd；
-float32用于轨迹，float64用于汇总和证书；
-文本日志gzip或zip内部压缩。
