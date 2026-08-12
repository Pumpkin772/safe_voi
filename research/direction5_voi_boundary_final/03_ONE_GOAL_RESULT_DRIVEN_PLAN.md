# 一个总Goal下的最终研究计划

## 最终论文目标

完成：

> **黑箱IBR安全主动能力探测的控制价值边界与选择性VOI-ACCR-MPC**

不是再次“试一个控制器看平均值是否超过4%”。

Codex必须持续执行，直到：

1. 得到经过独立validation的非空正值区域与选择性控制结果；或
2. 在预注册物理范围内完成价值边界计算，证明正值区域为空或不可复现，并形成边界负结果论文。

二者都属于完成项目。

## Git要求

在达到“证据里程碑”前：

```text
禁止 git add
禁止 git commit
禁止 git tag
禁止 push
```

所有中间工作保存在：

```text
scratch_direction5_boundary/
research_outputs_working/
progress_working.json
```

证据里程碑定义为：

- 正式VoI求解器通过单元和闭环开发验证；
- value boundary map可复算；
- 选择性策略在development中满足安全和净值要求；
- 或严格证明注册设计域没有正值区域。

达到后允许一次集成提交。Validation通过后允许第二次提交。Final完成后允许最终提交。

---

## 里程碑B1：建立精确价值边界引擎

### 研究目标
把当前启发式VoI替换为式(22)–(28)的注册模型内精确/保守计算。

### 任务
1. 冻结当前VOI-ACCR负结果；
2. 重构目标函数，frequency/ACE/tie使用固定归一化尺度；
3. 实现：
   - contract robust cost；
   - registered perfect-information cost；
   - safe probe library；
   - observation tubes；
   - posterior partitions；
   - actual post-probe robust recourse cost；
   - net VoI；
4. 实现no-probe upper-bound test；
5. 探测按固定物理持续时间设计，2s/4s分别离散；
6. 连续参数/OOD使用外包误差；
7. 在Plant A线性预测模型上建立boundary engine；
8. 用非线性Plant A小规模重放验证代价排序。

### 自动探索
Codex可以在锁定物理范围内：
- 自适应采样边界；
- 增加probe库；
- 改善数值算法；
- 使用并行、缓存、Benders或离线表格；
- 比较3组预注册目标偏好。

不得：
- 改变事故范围；
- 将tie weight设为0后又用tie作为主结论；
- 使用truth作为普通在线输入；
- 只保存正值cell。

### 设计域
至少包括：
- SG reserve/tension；
- 2s/4s；
- load/ACE level；
- power spread；
- ramp spread；
- delay spread；
- measurement noise；
- SoC/headroom；
- Plant A operating point。

使用Latin hypercube + boundary adaptive sampling，直到：
- 边界符号稳定；
- 未分类体积分数低于预注册阈值；
- 或计算预算达到预注册上限且有误差界。

### B1成功
- 数学定义和代码一一对应；
- no-probe theorem数值验证；
- 存在至少一个非空正值cell，或得到有证据的空正区；
- 当前heuristic与exact VoI差异有完整分析；
- period-normalized probe实现。

---

## 里程碑B2：选择性策略与独立Validation

### 研究目标
将development边界冻结为可部署选择策略。

### 策略
允许：
- 在线精确计算小probe库；
- 或development预计算的保守lookup/分段仿射边界；
- 不建议用不透明深度网络。

### 关键性质
1. 预测无价值时：
   - q=0；
   - 使用同一合同MPC对象；
   - 与合同基线数值等价。
2. 预测正价值时：
   - 选择最大净值safe probe；
   - 用真实后验集合追索；
   - 证书有覆盖；
   - probe-window代价显式计入。

### Validation设计
- development边界冻结；
- 每个精确设计cell≥10个独立seed；
- positive/no-probe区域均有样本；
- Plant A完整非线性；
- Plant B选择边界两侧运行点；
- 2s/4s分别；
- known/OOD；
- load/capability前后/同时；
- 300–600s；
- 至少6条1h正常profile；
- contract violation单独。

### Primary Gate

#### 全场景
- hard violation=0；
- success下降≤1pp；
- frequency peak绝对差≤0.02Hz；
- solver/fallback不劣；
- p99<0.5控制周期。

#### 预测正值区域
- 实际净ACE/tie/SG-mileage至少一项CI下界>0；
- value recovery≥25%，CI下界>0；
- false optimism≤1%；
- candidate reduction≥40%；
- probe-window增量频差≤0.02Hz。

#### 预测无价值区域
- false-positive probe≤5%；
- 核心指标变化≤1%；
- 动作与合同MPC近似等价。

#### Boundary
- predicted-positive precision≥70%；
- 对Plant B若边界预测为无价值，安全放弃视为正确，不强制正改善；
- 若Plant B存在正值cell，至少验证改善方向。

### 失败后的自主处理
Codex必须区分：
- VoI计算误差；
- probe安全代价低估；
- posterior分区错误；
-候选集合不覆盖；
-边界近似误差；
-数值时间；
-科学上无正值。

允许最多三轮development重构；每次必须使用新的validation split，不得直接根据旧validation调参。

若正值区域在独立validation中连续两次不可复现，形成边界负结果并进入论文。

---

## 里程碑B3：Final、论文与统一审查包

只有B2通过正面Gate才运行正面Final。

若B2得到决定性边界负结果，不运行正面Final，而使用未消耗数据进行一次边界确认。

### Final
- 配置、边界、probe库、目标和统计全部锁定；
- final seeds只运行一次；
- 不回调算法；
- 完整失败保留。

### 论文
根据结果二选一：

#### Positive
> value boundary非空，选择性策略在正值区域回收信息价值，在零值区域安全放弃。

#### Boundary-negative
> 在注册物理域内，完美信息价值不足以覆盖最小安全探测代价；给出不可获益区域和适用边界。

禁止生成“方法略差但方向仍待下一轮”的模糊结论。

---

## Codex不得频繁询问

Codex自主完成：

- 文献更新；
- 数学实现；
- 数值算法；
- adaptive sampling；
- probe库；
- development搜索；
- failure diagnosis；
- Plant A/B；
- 统计；
-论文。

仅在以下致命情况允许停止：
1. 环境或原生Plant无法修复；
2. 注册物理参数来源无法建立；
3. 数学问题无法在资源限制下求解且无近似误差界；
4. 正值区域连续两次独立validation不复现。
