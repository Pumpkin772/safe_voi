# 最终单一审查包规范

## 1. 文件名与大小

```text
DIRECTION1_PHASE_E_SCIENCE_RECOVERY_AND_CAPABILITY_CONTROL_SINGLE_REVIEW_PACKAGE.zip
```

必须 `<512 MB`。

## 2. 顶层目录

```text
00_README/
01_SCIENCE/
02_LITERATURE/
03_MODEL/
04_METHOD_AND_ORACLES/
05_CONFIG_ENV_SOLVERS/
06_SOURCE/
07_TESTS_VERIFICATION/
08_EXPERIMENT_DESIGN/
09_RAW_RESULTS/
10_SUMMARY_TABLES/
11_FIGURES/
12_FAILURES/
13_ANALYSIS_AND_PAPER/
14_REPRODUCIBILITY/
15_GIT_AND_MANIFEST/
16_FINAL_STATUS/
```

## 3. 必须包含

### 00_README

- `README_FIRST.md`
- `HOW_TO_REVIEW.md`
- `PACKAGE_INDEX.csv/json`

### 01_SCIENCE

- 最终科学问题；
- H1–H5；
- 信息边界；
- claim boundary；
- Gate与branch决策日志；
- Phase D结论撤回说明。

### 02_LITERATURE

- 检索协议与日志；
- ≥50篇核心文献矩阵；
- DOI/元数据核验；
- 最接近工作对比；
- BibTeX；
- 创新点—证据矩阵。

### 03_MODEL

- 完整数学模型；
- 公式推导；
- Plant A/Plant B；
- BESS能力/能量/延迟；
- SG/GRC/anti-windup；
- 单位和参数来源；
- equation-code map；
- 假设表。

### 04_METHOD_AND_ORACLES

- 所有公平基线；
- rolling current-capability Oracle；
- 被动估计器；
- 安全主动可行性；
- selected proposed；
- tube/RPI/terminal backup；
- solver与fallback。

### 05_CONFIG_ENV_SOLVERS

- `environment.yml`
- `requirements-lock.txt`
- Python/OS/CPU/GPU；
- CVXPY/CasADi/MOSEK/Gurobi/ANDES版本；
- 许可证不打包；
- 全部YAML配置。

### 06_SOURCE

- 完整可安装源码，不是diff片段；
- scripts、tests、configs；
- 无cache、无pyc。

### 07_TESTS_VERIFICATION

- 全测试日志；
- coverage；
- 闭环稳定；
- RoCoF/功率平衡；
- BESS能量；
- Plant B原生交叉验证；
- no-leakage；
- named-MPC审计；
- Oracle资格；
- theory certificates。

### 08_EXPERIMENT_DESIGN

- development/validation/final manifest；
- final lock及SHA256；
- 因素平衡报告；
- 指标schema；
- 统计计划；
- 随机种子防火墙。

### 09_RAW_RESULTS

- 全部逐episode指标；
- 全部控制周期轨迹；
- 失败/代表/Plant B细步轨迹；
- estimator set event logs；
- solver logs；
- Oracle logs；
- 探测轨迹（若分支A）。

### 10_SUMMARY_TABLES

- success-first；
- 材料性；
- passive/active identifiability；
- baseline；
- ablation；
- sensitivity；
- robustness；
- known/OOD；
- cost/Pareto；
- compute time；
- paired CI。

### 11_FIGURES

- SVG/PDF/600dpi PNG；
- source data；
- regeneration scripts；
- figure catalog。

### 12_FAILURES

- `FAILURE_LEDGER.csv`；
- 每类失败样例；
- code/solver/physical/scientific分开；
- 自动修复日志；
- 未解决限制。

### 13_ANALYSIS_AND_PAPER

- 全部结果解释；
- 支持/不支持声明；
- 论文大纲；
- 论文级方法和结果章节草稿；
- Reviewer-style limitation report。

### 14_REPRODUCIBILITY

- minimal/full replay命令；
- figure regeneration；
- manifest verification；
- runtime estimates；
- deterministic replay说明。

### 15_GIT_AND_MANIFEST

- commit、branch、status、log、diff；
- file manifest CSV/JSON；
- 每文件SHA256；
- ZIP SHA256；
- duplicate/large-file report。

### 16_FINAL_STATUS

- `FINAL_STATUS.json`；
- `ALL_GATES.csv`；
- selected branch；
- H1–H5状态；
- best baseline；
- known/OOD结果；
- final claim boundary；
- 最严重限制；
- 下一步边界。

## 4. 原始数据保留与大小控制

- Parquet + Zstd；
- 控制周期轨迹float32；
- 统计指标float64；
- 全细步轨迹保留所有失败、代表性、Plant B和证书场景；
- 其余细步轨迹可由seed/配置确定性重生；
- 删除 `.git`对象、conda环境、solver许可证、checkpoint、cache、pyc、重复图片；
- 不得删除支持结论的逐episode数据和失败证据。

## 5. 审计门

生成ZIP前运行：

```text
verify_manifest
verify_no_cache
verify_no_license
verify_no_true_state_leakage
verify_named_mpc
verify_final_lock
verify_failure_retention
verify_zip_size
```
