# 最终实验与统计协议

## 1. 数据防火墙

历史M1/M2数据仅用于审计和先验预测，不用于最终正区选择。

建议新分割：

```text
development: 7000–7199
validation_1: 7300–7399
validation_2: 7400–7499
final: 7600–7699
```

## 2. 目标函数

主目标使用归一化frequency/ACE/tie和资源成本。至少预注册三组偏好：

1. balanced；
2. ACE/tie responsibility；
3. resource-economy。

正值区域必须报告对偏好的敏感性，不能只选择最有利权重。

## 3. 设计空间

使用文献和设备参数确定范围：

- SG reserve/tension；
- control period 2/4s；
- load/ACE level；
- power uncertainty width；
- ramp uncertainty width；
- delay interval width；
- noise；
- SoC/headroom；
- event timing；
- Plant operating point。

使用：
- Latin hypercube初始采样；
- boundary adaptive sampling；
- 正/负区域两侧加密；
- 所有采样保留。

## 4. 重复性

每个锁定validation cell至少：

```text
10 independent seeds
```

Plant B每个代表边界cell至少：

```text
6 paired scenarios
```

正常1小时：

```text
≥6 profiles / method
```

## 5. 探测

探测按物理时长定义：

```text
4s, 8s, 12s
```

2s和4s周期分别离散。报告：

- command L1/L2；
- actual power deviation；
- local window frequency/ACE/tie；
- energy；
- candidate partition；
- closed-loop total cost。

## 6. 统计

### Primary
- paired absolute difference；
- scenario-balanced aggregate；
- seed/design-cell hierarchical bootstrap；
- positive/no-probe区域分开；
- exact value vs realized value calibration。

### Classification
- positive-region precision；
- recall；
- no-probe false-positive；
- boundary calibration curve。

### Safety
- success-first；
- hard violations；
- solver/fallback；
- frequency noninferiority。

### Value recovery
仅对：

\[
J^R-J^{PI}>J_{\min}^{material}
\]

的场景评价。

## 7. Validation失败处理

第一次validation失败后：
- 不允许直接调现有validation；
- 回到development；
- 根据失效原因修改数学近似或probe库；
- 使用新的validation_2。

第二次独立validation仍失败：
- 形成边界负结果；
- 不再继续算法搜索。

## 8. Final
只有正面validation通过才运行正面final。边界负结果使用独立确认集验证无正区。
