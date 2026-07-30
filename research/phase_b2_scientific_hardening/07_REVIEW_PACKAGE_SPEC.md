# 下一轮审查压缩包规范

最终文件名：

`D5_PHASE_B2_SCIENTIFIC_HARDENING_REVIEW_PACKAGE.zip`

硬性要求：小于 512 MB；推荐小于 150 MB。

## 必须包含

### 顶层报告

- `00_EXECUTIVE_SUMMARY.md`
- `01_CORRECTED_PHASE_B1_AUDIT.md`
- `02_SERVICE_SCOPE_AND_MODEL_REPORT.md`
- `03_PLANT_B_PHYSICAL_VALIDATION.md`
- `04_STRONG_ORACLE_VALIDATION.md`
- `05_MATERIALITY_REPORT.md`
- `06_CONTROL_RELEVANT_IDENTIFIABILITY.md`
- `07_FINAL_DECISION_AND_NEXT_METHOD.md`
- `08_LIMITATIONS_AND_FAILURES.md`
- `09_REPRODUCIBILITY_COMMANDS.md`

### 源码与配置

- 本阶段全部新增/修改源码；
- Git commit、status、diff；
- resolved configs；
- environment；
- solver versions；
- tests 和 coverage。

### 结果表

必须符合 `reference/required_output_tables.md`。

至少包括：

- 每个 episode 指标；
- failure pairing table；
- corrected materiality；
- cost sensitivity；
- O0/O1/O2/O3 oracle gap；
- prediction error；
- solver/KKT；
- control-relevant regime distance；
- Tcritical；
- detection delay；
- source confusion；
- final decision JSON。

### 轨迹

只保留预注册代表性高频轨迹，使用 Parquet/ZSTD：

- load-only；
- mode-only；
- before/coincident/after；
- energy/headroom limit；
- communication degraded；
- OOD；
- 最差失败；
- O2 与 O0 差异最大的案例。

每类 1–2 个 seed，避免把所有高频轨迹打包。

### 图

- corrected B1 decision；
- Plant B block diagram；
- open-loop regime responses；
- O0/O1/O2 performance；
- cost-frequency Pareto；
- detection vs Tcritical；
- source confusion；
- Oracle solver quality；
- failures。

## 完整性

- `FILE_INDEX.csv`
- `SHA256_MANIFEST.json`
- ZIP 外部 `.sha256`
- 声明总 episode、失败、缺失、超时、不可行数量。
- 不含 Conda 环境目录、solver license、缓存、模型训练临时文件。
