# Phase B2 统计与判决修正规范

## 1. 主要估计量

对方法 M 和参考 R 的配对 episode，定义差值：

`d_i = y_i^M - y_i^R`

主要绝对效果：

`Δ = mean_scenario( mean_seed(d_i | scenario) )`

主要相对效果：

`Δ_rel = Δ / max(|mean_scenario(mean_seed(y_i^R))|, ε)`

禁止将 `mean((M-R)/R)` 作为主要结论。

## 2. 场景平衡

每个 scenario 先在 seed 内求均值，再对 scenario 等权平均。SG level 分开报告，不把 A/B/C 混成一个主要结论。

## 3. 失败处理

采用 lexicographic success-first：

1. catastrophic/scientific failure rate；
2. frequency safety violation rate；
3. 在共同成功子集上的连续性能；
4. 所有 episode 的 censored/penalized sensitivity。

不得因为 `scientific_success=false` 就从主表删除。必须输出：

- attempted pairs；
- both-success pairs；
- M-only failure；
- R-only failure；
- both failure。

## 4. 材料性

材料性需要满足下列至少一种：

### Frequency-value gate

- failure/safety 不恶化；
- IAE 或最差频差改善达到阈值；
- 总控制成本不恶化超过容差。

### Cost-value gate

- failure/safety 不恶化；
- 频率 IAE 非劣；
- 总控制成本改善达到阈值。

总成本：

`J_cost = c_sg E_sg + c_ibr E_ibr + c_dsg Mileage_sg + c_dibr Mileage_ibr`

对 `c_ibr/c_sg = 0.25, 0.5, 1.0, 2.0` 做敏感性分析。没有明确价格时，不允许仅凭 SG mileage 宣称成本收益。

## 5. Bottleneck 判决

伪代码：

```python
if not problem_material:
    decision = "PROBLEM_NOT_MATERIAL"
else:
    active = [name for name, triggered in triggers.items() if triggered]
    if len(active) == 0:
        decision = "INCONCLUSIVE_REQUIRES_MORE_EVIDENCE"
    elif len(active) == 1:
        decision = active[0]
    else:
        ranked = sort_only_active_by_normalized_score(active)
        decision = "COMBINED:" + ranked[0] + "+" + ranked[1]
```

COMBINED 不得包含未触发的 bottleneck。

## 6. 必须生成的回归测试

1. 三个 trigger 全 false -> INCONCLUSIVE。
2. 仅 model trigger true -> MODEL_MISMATCH。
3. 两个 trigger true -> COMBINED，只包含两个 active。
4. 小参考值 episode 不得主导 ratio-of-means。
5. reference-only failures 必须出现在失败比较表。
6. 资源成本必须同时包含 SG 和 IBR。
