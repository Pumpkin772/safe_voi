# 最终审查包规范

## 文件名

```text
DIRECTION5_VOI_ACCR_MPC_SINGLE_REVIEW_PACKAGE.zip
```

## 大小

```text
<512MB
```

## 必须目录

```text
00_README/
01_SCIENCE/
02_LITERATURE/
03_MATHEMATICS/
04_METHOD/
05_PLATFORM/
06_SOURCE_ENV/
07_TESTS/
08_DEVELOPMENT_SEARCH/
09_VALIDATION/
10_FINAL/
11_RAW_RESULTS/
12_SUMMARY_TABLES/
13_FIGURES/
14_FAILURES/
15_PAPER_DRAFT/
16_REPRODUCIBILITY/
17_GIT_MANIFEST/
18_FINAL_STATUS/
```

## 必须文件

### 科学和数学
- 科学问题；
- 探测值得区域定义；
- VoI公式；
- 探测安全条件；
- 候选集合包含；
- 证书条件；
- change reset；
- 价值回收率；
- 声明边界。

### 自动搜索
- 完整设计空间；
- 每次试验配置；
- 失败原因；
- M1选择规则；
- 未选择方案；
- 不得只保留最好结果。

### 结果
- 全部development；
- 每轮独立validation；
- final；
- Plant A/B；
- known/OOD；
- normal1h；
- contract violation；
- probe-worthwhile和not-worthwhile；
- Oracle gap；
- probe cost；
- candidate set；
- value recovery；
- solver/fallback；
- 全部失败。

### 源码与复现
- 完整可安装源码；
- 环境；
- 入口；
- tests；
- fresh-extract reproduce_minimal；
- reproduce_all；
- Git状态；
- manifest；
- SHA256。

## 大小控制

使用：

- Parquet + Zstd；
- 轨迹float32；
- 统计float64。

删除：

- cache；
- 环境目录；
- 许可证；
- 重复checkpoint；
- 重复图片。

保留：

- 所有控制周期轨迹；
- 所有失败细步轨迹；
- 每个设计类别的代表轨迹；
- 全部搜索结果和不利结果。
