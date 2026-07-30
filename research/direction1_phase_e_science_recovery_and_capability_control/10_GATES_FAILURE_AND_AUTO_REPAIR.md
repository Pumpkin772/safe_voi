# Gate、失败判据和自动修复规则

## 1. 总诊断顺序

任何失败必须按顺序处理：

```text
CODE
→ NUMERICS/SOLVER
→ PARAMETERS_WITHIN_REGISTERED_PHYSICS
→ MODEL
→ METHOD
→ SCIENTIFIC_HYPOTHESIS
```

不得跳到无依据调参或更换算法。

## 2. Gate表

| Gate | 通过条件 | 不通过结论 | 后续 |
|---|---|---|---|
| G0 Baseline | 证据完整、独立问题可复现 | FATAL_BASELINE_INCOMPLETE | 停止打包 |
| G1 Novelty | 科学交叉未被完整覆盖 | NOVELTY_NOT_SUPPORTED | 收缩一次；仍失败停止 |
| G2 Physics | 名义闭环稳定、Plant A/B物理与数值通过 | FATAL_PHYSICAL_OR_CLOSED_LOOP_MODEL_FAILURE | 最多两轮修复；失败停止 |
| G3 Materiality | 合格Oracle显示能力知识有实质价值 | PROBLEM_NOT_MATERIAL | 停止辨识路线 |
| G4 Passive | coverage/timing/收缩达到Gate | PASSIVE_IDENTIFIABLE | 选择分支P |
| G5 Active | 安全探测增加信息且不破坏安全 | ACTIVE_IDENTIFICATION_FEASIBLE | 选择分支A |
| G5b Active fail | 主动不安全/无信息 | ACTIVE_IDENTIFICATION_NOT_SAFE | 选择分支R |
| G6 Method | proposed相对最佳基线通过验证门 | METHOD_NOT_SUPPORTED_BY_EVIDENCE | 不换方法，负结果 |
| G7 Theory | 证书与代码一致 | EMPIRICAL_ONLY_THEORY_NOT_CERTIFIED | 收缩理论声明 |
| G8 Final | 冻结矩阵上结论成立 | FINAL_EVIDENCE_NOT_SUPPORTED | 保留负结果 |
| G9 Package | 完整、可复现、<512MB | PACKAGE_INCOMPLETE | 仅补材料 |

## 3. 自动修复额度

### 代码/测试

不限于合理修复次数，但每次必须增加回归测试和记录diff。

### 数值/求解器

最多两轮：

1. 单位、缩放、离散化、warm start、容差；
2. 等价求解器/凸化/网格细化。

不得降低物理约束或删除难例。

### 参数

只能在文献、设备或预注册范围内调整；development/validation最多两轮。final开始后禁止。

### 模型

允许修正错误接口、守恒和缺失物理；不得为了让方法获胜而减弱基线或改变科学问题。

### 方法

E6最多两轮development/validation修复。失败后不能切换到另一个分支或加入额外算法。

## 4. Fatal stop条件

- 源码/数据不可恢复；
- 科学问题被现有工作完整覆盖；
- 稳定物理平台无法建立；
- 合格Oracle证明问题无材料性；
- 选定方法在验证集持续不优于最佳基线；
- final证据不支持声明。

停止时仍必须执行E9，生成完整负结果包。

## 5. 禁止掩盖失败

- 不得删除失败episode；
- 不得将solver failure记为not evaluated；
- 不得将not evaluated记为科学失败；
- 不得调宽频率/ACE阈值；
- 不得改变final seeds或manifest；
- 不得只展示最佳seed；
- 不得用平均值掩盖失败率；
- 不得把代数规则命名为MPC；
- 不得在全部触发条件为false时强制输出dominant结论。

## 6. Branch选择必须唯一

```text
if G4_PASS:
    branch = P
elif G3_PASS and G5_PASS:
    branch = A
elif G3_PASS and not G5_PASS:
    branch = R
else:
    STOP
```

Branch写入 `06_METHOD/SELECTED_BRANCH.json` 并哈希锁定。选择后不得改变。
