# 一个总Goal下的最终关闭计划：C0–C6

## C0 冻结和独立复现

### 目标
确认最新ZIP、Git、manifest、最小复现和R5核心统计可独立重算。

### 任务
- 创建tag `direction5-final-repair-reviewed`；
- 创建branch `direction5-closure-confirmation`；
- 复算manifest、Gate、paired failures、scenario-balanced means、hierarchical bootstrap、solver denominator；
- 检查contract-only与DCSV配对是否完整；
- 检查normal1h异常轨迹来源；
- 检查Plant A/B方向计算。

### 输出
```text
progress_closure/C0.json
00_AUDIT/CURRENT_PACKAGE_REPLICATION.md
00_AUDIT/RECOMPUTED_GATES.csv
00_AUDIT/RECOMPUTED_STATISTICS.csv
00_AUDIT/REPLICATION_DIFFERENCES.csv
```

### 成功
核心结果与包内值在容差内一致。

### 失败处理
若存在影响结论的代码/统计错误，只允许修复该错误、增加回归测试，并冻结新的commit；不得调参。

---

## C1 方法与信息价值机制分析

### 目标
解释为什么真实能力有材料性，但在线方法未产生价值。

### 必须分析
- performance envelope激活占比；
- surplus command占比、幅值和持续时间；
- estimator excitation充分率；
- delay candidate宽度；
- contract-only、model-adaptive、DCSV和Oracle的动作差异；
- delivered/loss branch中binding constraints；
- fallback根因；
- mechanism×SG tension×period×Plant分层结果；
- contract violation检测延迟；
- normal1h异常根因；
- value of perfect information与value of causal online information。

### 输出
```text
01_MECHANISM/INFORMATION_VALUE_DECOMPOSITION.parquet
01_MECHANISM/SURPLUS_USAGE.csv
01_MECHANISM/ESTIMATOR_EXCITATION.csv
01_MECHANISM/FALLBACK_ROOT_CAUSES.csv
01_MECHANISM/BINDING_CONSTRAINTS.csv
01_MECHANISM/NORMAL1H_ROOT_CAUSE.md
01_MECHANISM/MECHANISM_LEVEL_RESULTS.csv
```

### 成功
每项负结果都能定位为：信息不足、保守合同、估计器宽集合、recourse保守、求解器或物理不可行。

---

## C2 一次性确认集

### 目标
在不修改方法的条件下，使用尚未消耗的final seeds作一次性确认。

### 规则
- 方法、配置、统计、成功标准和场景矩阵全部哈希锁定；
- final seeds只运行一次；
- 不根据确认结果回调算法；
- 若C0发现代码bug，必须在运行final前修复并重新锁定；
- known/OOD/contract violation分开；
- Plant A和Plant B均运行；
- 正常1h使用原注册profile并额外明确profile异常，不修改profile。

### 输出
```text
02_CONFIRMATORY/FINAL_LOCK.json
02_CONFIRMATORY/FINAL_MANIFEST.csv
02_CONFIRMATORY/FINAL_EPISODES.parquet
02_CONFIRMATORY/FINAL_CYCLES.parquet
02_CONFIRMATORY/FINAL_STATISTICS.csv
02_CONFIRMATORY/FINAL_PAIRED_FAILURES.csv
02_CONFIRMATORY/FINAL_BOOTSTRAP.csv
```

### 终态规则
- 若validation和confirmatory均不支持DCSV-CR：负结果确认；
- 若confirmatory意外通过但validation失败：报告异质性，不宣称普遍正面；
- 只有validation修正后与confirmatory均通过，才允许有限正面结论。

---

## C3 论文/技术报告路线

### 路线A：负结果确认（预期）
暂定题目：

**Limits of Causal Online Deliverability Adaptation for Black-Box IBRs in Multi-Area Secondary Frequency Control**

中文：

**黑箱IBR多区域二次调频中因果在线可交付能力自适应的价值与边界**

贡献：
1. same-instant contract collapse不可保证边界；
2. actual-POI负荷–能力分离；
3. perfect-information价值与causal-online-information价值差距；
4. 合同MPC、model-adaptive MPC和DCSV-CR系统比较；
5. 公开负结果、失败机理和可复现基准。

不得声称提出了性能更优的控制器。

### 路线B：有限正面确认
仅当validation和confirmatory均支持时，采用当前DCSV-CR的有界声明，不增加新方法。

### 输出
```text
03_PAPER/PAPER_DRAFT.md
03_PAPER/ABSTRACT.md
03_PAPER/CONTRIBUTIONS.md
03_PAPER/RESULTS_SECTION.md
03_PAPER/LIMITATIONS.md
03_PAPER/SUPPORTED_UNSUPPORTED_CLAIMS.md
03_PAPER/REVIEWER_RISK_REGISTER.md
```

---

## C4 论文级图表和表格

必须生成：
- 信息价值分解；
- perfect vs online vs contract性能；
- estimator excitation/coverage；
- surplus使用；
- failure/fallback机制；
- Plant A/B；
- known/OOD；
- normal1h异常；
- contract violation；
- validation vs confirmatory；
- theory boundaries。

格式：SVG、PDF、600dpi PNG、源数据和生成脚本。

---

## C5 代码和数据基准归档

输出：
- 完整源码；
- 环境和求解器；
- 所有实验manifest；
- validation与confirmatory原始结果；
- 所有失败；
-最小复现；
-全量复现；
-数据字典；
-许可证说明；
-Git和SHA256。

---

## C6 唯一最终状态

只允许：

```text
DIRECTION5_NEGATIVE_RESULT_CONFIRMED_AND_ARCHIVED
```

或：

```text
DIRECTION5_BOUNDED_POSITIVE_RESULT_CONFIRMED
```

不得再创建新Phase或新方法。
