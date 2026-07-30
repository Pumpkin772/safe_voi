# 下一轮统一审查压缩包规范

## 1. 文件名

```text
DIRECTION1_PHASE_D_CRCS_TUBE_MPC_SINGLE_REVIEW_PACKAGE.zip
```

必须小于512MB。

## 2. 固定目录

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

## 3. 必须包含

### 00_README

- `README_FIRST.md`
- `HOW_TO_REVIEW.md`
- `PACKAGE_INDEX.csv/json`

### 01_SCIENCE

- 锁定科学问题；
- H1–H4及结果；
- Gate决策；
- 支持/不支持声明；
- 决策日志。

### 02_LITERATURE

- ≥50篇文献矩阵；
- 文献综述；
- 创新对照；
- 检索日志；
- BibTeX。

### 03_MODEL_AND_THEORY

- 完整数学模型；
- 全部假设；
- 参数来源；
- 单位表；
- 公式—代码映射；
- 定理和证明；
- RPI/终端集/约束收紧证书；
- Plant A/B验证说明。

### 04_SOURCE

- 可安装完整源码；
- 脚本；
- 测试；
- 不得只给patch。

### 05_CONFIG_AND_ENV

- `environment.yml`、`pyproject.toml`、锁定依赖；
- 求解器说明；
- 全部YAML；
- 不包含许可证。

### 06_TESTS_AND_VERIFICATION

- 全部pytest XML/log/coverage；
- 单位、RoCoF、功率平衡、能量、延迟和dt证书；
- Plant B ANDES交叉验证；
- leakage、factor independence、seed firewall；
- Oracle和管束数值证书。

### 07_EXPERIMENT_DESIGN

- 预注册实验矩阵；
- 控制器清单；
- 指标字典；
- 统计方案；
- 计算预算；
- final锁定哈希。

### 08_RAW_RESULTS

- 全部episode指标；
- 每个episode控制周期轨迹；
- 所有失败和代表场景细步轨迹；
- 能力集合时序；
- 估计器/求解器状态；
- 消融、敏感性和OOD原始结果。

### 09_SUMMARY_TABLES

- success-first四格；
- 场景平衡汇总；
- 配对差值与CI；
- 已知/OOD；
- 成本/Pareto；
- 计算时间；
- 能力集合覆盖。

### 10_FIGURES

必须包含非空且论文级：

- 系统与方法框图；
- Plant A/B交叉验证；
- Oracle材料性；
- 能力变化、集合更新、责任转移、频率、ACE、tie、SoC同轴图；
- 已知/OOD比较；
- 消融；
- Pareto；
- 失败案例；
- 源数据和生成脚本。

### 11_FAILURES

- 所有失败episode；
- 代码/求解器/物理/科学分类；
- 修复日志；
- 未解决风险；
- 负结果。

### 12_REPRODUCIBILITY

- Windows/PowerShell和跨平台命令；
- 最小复现；
- 全量复现；
- 仅重画图；
- 预计时间和硬件。

### 13_GIT_AND_MANIFEST

- commit、branch、status、diff；
- 全文件清单；
- 每文件SHA256；
- ZIP SHA256。

### 14_FINAL_STATUS

- 最终研究状态；
- 每个Gate；
- 结果解释；
- 支持/不支持创新；
- 论文提纲；
- 下一步仅限投稿完善，不再探索新方法。

## 4. 大小控制

- 结果用Parquet+Zstd；
- 时序float32，统计float64；
- 删除`.git`对象、缓存、conda环境、模型checkpoint、重复图片和许可证；
- 所有episode保留控制周期数据；
- 细步数据只保留失败、代表和验证场景，其余由seed确定性重生；
- 压缩前运行重复文件和大文件报告；
- 不得为减小体积删除支持结论的失败数据。
