# 软件架构与最终输出

## 新源码建议

```text
src/direction5freq/voi_boundary/
├─ robust_baseline_value.py
├─ perfect_information_value.py
├─ probe_observation_tubes.py
├─ posterior_partition.py
├─ exact_probe_value.py
├─ no_probe_bound.py
├─ boundary_sampler.py
├─ selective_controller.py
└─ value_calibration.py
```

## 代码要求

- 禁止通过`inspect.getsource`和`exec`动态修改MPC源码；
- 目标权重、模型和约束显式参数化；
- exact/approximate模式分别实现；
- 每个价值计算保存求解状态和误差界；
- 所有数据、配置、seed可追溯；
- 普通控制器不读取truth/future；
- pyproject统一改为direction5项目名；
- Git clean；
- 完整reproduce_all能够重生boundary map和validation摘要。

## 工作目录

```text
scratch_direction5_voi_boundary/
research_outputs_boundary/
results_boundary/
figures_boundary/
logs_boundary/
progress_boundary.json
```

## Git

证据里程碑之前禁止提交。

允许：
1. boundary engine和development证据闭合后；
2. validation通过后；
3. final/负结果论文完成后。

## 最终审查包

```text
DIRECTION5_VOI_BOUNDARY_SINGLE_REVIEW_PACKAGE.zip
```

必须小于512MB。
