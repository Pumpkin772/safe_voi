# Phase B1 Review Package Specification

Codex 最终只输出：

```text
D5_PHASE_B1_BOTTLENECK_AUDIT_REVIEW_PACKAGE.zip
```

必须小于 512 MB。

## 必须包含

### 顶层报告

- `00_EXECUTIVE_SUMMARY.md`
- `01_BASELINE_AND_INTEGRITY.md`
- `02_PROBLEM_MATERIALITY.md`
- `03_MODEL_ADEQUACY.md`
- `04_IDENTIFIABILITY.md`
- `05_CONTROL_DESIGN_DECOMPOSITION.md`
- `06_BOTTLENECK_DECISION.md`
- `07_LIMITATIONS_AND_FAILURES.md`
- `08_REPRODUCIBILITY_COMMANDS.md`

### 源码和Git

- Phase B1 新增/修改源码；
- baseline commit、Phase B1 commit；
- status、diff、文件索引；
- 旧 Phase-A 核心结果哈希验证；
- 不包含 `.git`、许可证、密钥。

### 实验结果

- 所有必须 CSV；
- 全部逐 episode 结果；
- paired statistics；
- SG Level A/B/C；
- B0/B2/B4/B5/P_old/C0–C5；
- 所有失败、timeout、不可行和 censored 行。

### 图

至少包含 `04_EXPERIMENT_PROTOCOL.md` 中的 12 类图。

### 测试与环境

- environment YAML；
- package versions；
- solver smoke；
- pytest text/JUnit；
- coverage；
- random seeds；
- SHA256 manifest。

## 禁止包含

- Conda 环境目录；
- solver license；
- Git object database；
- 所有高频原始轨迹；
- cache和临时求解文件。

只保留代表轨迹和最差失败案例。
