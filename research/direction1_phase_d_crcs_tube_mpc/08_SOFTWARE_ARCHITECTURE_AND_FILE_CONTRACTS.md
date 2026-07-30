# 软件架构、接口和文件契约

## 1. 新分支与目录

```text
branch: direction1-phase-d-crcs-tube-mpc
outputs:
  research_outputs_phase_d/
  results_phase_d/
  figures_phase_d/
  logs_phase_d/
  progress_phase_d/
```

旧Phase C结果只读保留。

## 2. 推荐源码结构

```text
src/direction1freq/
├─ models/
│  ├─ plant_a_two_area.py
│  ├─ plant_b_andes_adapter.py
│  ├─ sg_dynamics.py
│  ├─ bess_capability.py
│  └─ delayed_external_ibr.py
├─ estimation/
│  ├─ augmented_load_estimator.py
│  ├─ set_membership_identifier.py
│  ├─ capability_set_estimator.py
│  └─ causal_change_detector.py
├─ controllers/
│  ├─ sg_only_pi.py
│  ├─ fixed_allocation_pi.py
│  ├─ nominal_mpc.py
│  ├─ rls_adaptive_mpc.py
│  ├─ worst_case_tube_mpc.py
│  ├─ crcs_tube_mpc.py
│  └─ oracle_nmpc.py
├─ optimization/
│  ├─ tube_sets.py
│  ├─ terminal_set.py
│  ├─ delay_augmentation.py
│  └─ solver_interface.py
├─ experiments/
├─ evaluation/
└─ utils/
```

## 3. Controller接口

```python
class DeployableController(Protocol):
    def reset(self, public_initialization: PublicInitialization) -> None: ...
    def update(
        self,
        measurement: PublicMeasurement,
        timestamp_s: float,
    ) -> ControlAction: ...
```

`PublicMeasurement`不得包含true load、true capability、true SoC、hidden state和future信息。

## 4. Plant接口

```python
class FrequencyPlant(Protocol):
    def reset(self, scenario: ScenarioTruth) -> PlantState: ...
    def public_measurement(self, state: PlantState) -> PublicMeasurement: ...
    def step(self, state, command, exogenous_truth, dt_s) -> PlantStep: ...
```

truth对象与public measurement在类型上分离，增加运行时泄露测试。

## 5. 配置

所有实验只从YAML加载：

- 单位与系统基准；
- Plant参数；
- 能力变化；
- 噪声与通信；
- 估计器；
- 控制器；
- 求解器；
- 数据split；
- 随机种子；
- 成功阈值。

final配置生成SHA256后锁定。

## 6. 公式—代码映射

`FORMULA_CODE_MAP.csv` 每个公式至少记录：

- equation_id；
- document_section；
- source_file；
- function/class；
- unit test；
- numerical certificate；
- status。

## 7. 必须新增测试

- unit dimensional audit；
- Plant A initial RoCoF；
- Plant B power balance；
- BESS no-free-energy；
- shared PFR/SFR current/ramp/energy；
- causal detector no-prechange alarm；
- no-future-data test；
- delay queue impulse test；
- true RLS parameter update；
- each named MPC has horizon and optimization object；
- RPI/terminal set nonempty；
- recursive feasibility regression；
- final factor independence；
- final seed firewall；
- package completeness。

## 8. 进度状态

每阶段写入：

```text
progress_phase_d/D0.json ... D9.json
```

字段：目标、输入哈希、执行命令、测试、Gate、失败、修复、输出哈希、下一阶段。
