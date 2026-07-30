# 软件架构、阶段契约和文件要求

## 1. 推荐目录

```text
project_root/
├─ pyproject.toml
├─ environment.yml
├─ src/direction1freq/
│  ├─ models/
│  ├─ estimation/
│  ├─ identification/
│  ├─ controllers/
│  ├─ optimization/
│  ├─ simulation/
│  └─ evaluation/
├─ configs/phase_e/
├─ scripts/phase_e/
├─ tests/phase_e/
├─ research/direction1_phase_e_science_recovery_and_capability_control/
├─ research_outputs_phase_e/
├─ results_phase_e/
├─ figures_phase_e/
├─ logs_phase_e/
└─ progress_phase_e/
```

## 2. 核心API

### Plant

```python
class FrequencyPlant(Protocol):
    def reset(self, scenario, seed) -> Observation: ...
    def step(self, command, dt) -> tuple[Observation, Diagnostics]: ...
    def public_observation(self) -> Observation: ...
```

部署控制器API不得暴露true capability。

### Capability estimator

```python
class CapabilitySetEstimator(Protocol):
    def reset(self, declared_global_set, public_initial_info): ...
    def update(self, public_measurement, issued_command) -> CapabilitySetEstimate: ...
```

返回必须包含：集合、coverage-evaluable representation、alarm、set-change event、信息指标、状态码。

### Controller

```python
class FrequencyController(Protocol):
    def reset(self, public_model, public_limits): ...
    def act(self, observation, capability_set) -> ControlDecision: ...
```

`ControlDecision`必须包含solver/fallback信息。

### Oracle

Oracle置于 `evaluation/oracles/`，普通runtime包不得导入。

## 3. 阶段进度契约

每阶段输出 `progress_phase_e/E#.json`：

```json
{
  "stage": "E2",
  "status": "PASSED|FAILED|STOPPED",
  "goal": "...",
  "inputs_sha256": {},
  "commands": [],
  "tests": {},
  "gate": {},
  "failures": [],
  "repairs": [],
  "outputs_sha256": {},
  "next_stage": "E3"
}
```

## 4. No-leakage检查

必须有静态和运行时检查：

- controller模块禁止包含 `true_regime`, `hidden_parameter`, `future_load`, `future_switch`；
- Oracle与普通controller namespace隔离；
- final运行时记录每个API字段；
- 真值只写入评价文件，不写入控制输入。

## 5. Named-MPC审计

脚本扫描所有类/文件名含 `mpc` 的实现，要求存在：

- horizon；
- optimization variables；
- dynamics constraints；
- state/input constraints；
- objective；
- solver call；
- receding execution；
- status/fallback。

不满足者必须重命名为rule/baseline，不得出现在MPC比较表。

## 6. 配置

每项实验配置必须完全序列化：

- plant/model参数；
- controller参数；
- estimator参数；
- solver；
- scenario；
- random seeds；
- metrics；
- Gate阈值；
- source commit/hash。

禁止在脚本中隐藏关键常数。

## 7. 运行入口

```text
python -m scripts.phase_e.run_e0_forensic
python -m scripts.phase_e.run_e2_model_validation
python -m scripts.phase_e.run_e3_materiality
python -m scripts.phase_e.run_e4_passive_identifiability
python -m scripts.phase_e.run_e5_active_feasibility
python -m scripts.phase_e.run_e6_selected_method
python -m scripts.phase_e.run_e8_final
python -m scripts.phase_e.build_review_package
```

并提供：

```text
reproduce_minimal.py/.ps1
reproduce_all.py/.ps1
regenerate_figures.py/.ps1
verify_manifest.py
```

## 8. 原始数据保留

- 所有episode保留控制周期轨迹；
- 所有失败、代表性和Plant B场景保留细步轨迹；
- 其他细步轨迹可由seed确定性重生；
- 全部逐episode指标必须保留；
- 使用Parquet+Zstd，数值轨迹float32，统计汇总float64。

## 9. 测试分类

```text
unit
physics
causality
no_leakage
closed_loop_stability
solver
oracle
identification
robust_constraint
reproducibility
package_audit
```

coverage目标：核心新增代码≥85%，全仓库≥75%；coverage不能代替物理测试。
