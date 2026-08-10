# 最终审查包规范

## 文件名
```text
DIRECTION5_ACCR_MPC_SINGLE_REVIEW_PACKAGE.zip
```

## 大小
```text
<512MB
```

## 目录
```text
00_README/
01_AUDIT/
02_SCIENCE/
03_LITERATURE/
04_MODEL/
05_IDENTIFICATION/
06_PROBE_DESIGN/
07_METHOD/
08_THEORY/
09_SOURCE_ENV/
10_TESTS/
11_EXPERIMENT_DESIGN/
12_RAW_RESULTS/
13_SUMMARY_TABLES/
14_FIGURES/
15_FAILURES/
16_PAPER_DRAFT/
17_REPRODUCIBILITY/
18_GIT_MANIFEST/
19_FINAL_STATUS/
```

## 必须内容
- 历史负结果冻结；
- ≥70篇文献和创新矩阵；
- 完整数学推导；
- Plant A和原生Plant B；
- 被动集合和主动探测；
- probe library与安全门；
- ACCR-MPC；
- 所有基线；
- 理论证书；
- dev/validation/final manifests；
- 所有episode和cycle数据；
- probe候选、信息增益、拒绝原因；
- certificate轨迹；
- known/OOD/contract violation；
- normal1h；
- solver/fallback；
- failure cases；
- 论文草稿和结果源数据；
- Git/manifest/SHA256；
- 唯一终态。

## 大小控制
- Parquet+Zstd；
- cycle轨迹全部保留；
- 失败和代表性细步轨迹；
- 删除cache/env/license/重复checkpoint；
- 不删除不利数据。

## 复现
fresh extract运行：
```bash
python 17_REPRODUCIBILITY/verify_manifest.py
python 17_REPRODUCIBILITY/reproduce_minimal.py
```
