# Implementation and API Specification

## 1. 目录

在真实项目根目录新增：

```text
research/phase_b1_bottleneck_audit/
artifacts_phase_b1/
results_phase_b1/
figures_phase_b1/
logs_phase_b1/
progress_phase_b1/
```

不得覆盖原 `artifacts/`、`results/`、`figures/`。

## 2. 建议新增源码

```text
src/d5freq/evaluation/
├─ exact_nonlinear_oracle.py
├─ oracle_gap_audit.py
├─ identifiability_audit.py
├─ problem_materiality.py
└─ control_design_counterfactuals.py

scripts/
├─ phase_b1_00_freeze_baseline.py
├─ phase_b1_01_validate_exact_oracle.py
├─ phase_b1_02_run_materiality_audit.py
├─ phase_b1_03_run_model_audit.py
├─ phase_b1_04_run_identifiability_audit.py
├─ phase_b1_05_run_control_design_audit.py
├─ phase_b1_06_make_decision.py
└─ phase_b1_07_build_review_package.py
```

## 3. Truth access 边界

B5 可以访问：

```text
true_mode
true_ibr_parameters
true_delay
true_saturation
true_rate_limits
true_deadband
```

但只能通过：

```text
src/d5freq/evaluation/
```

运行时 proposed/baseline controllers 的 API 仍只能接受 `Measurement`。

必须增加静态扫描和运行时 sentinel 测试，证明 `src/d5freq/controllers/`、`src/d5freq/estimation/` 不读取上述 truth 字段。

## 4. Exact Oracle 接口

建议：

```python
class ExactNonlinearOracleController:
    def reset(self, evaluation_context: ExactOracleContext) -> None: ...
    def act(self, measurement: Measurement) -> ControlAction: ...
```

`ExactOracleContext` 只能由 evaluation runner 创建，不得通过普通 controller factory 暴露。

B5 可采用：

- CasADi/IPOPT direct multiple shooting；
- SciPy nonlinear direct shooting；
- 高精度 simulator-in-the-loop scenario MPC。

无论采用何种方式，都必须：

- 保存求解状态；
- 验证首个动作约束；
- 对简化线性情形与 B4 做交叉检查；
- 报告求解失败，不得静默使用 B0 替代而仍标记为 B5。

## 5. Counterfactual controller API

C0–C5 必须共享同一 MPC weights、horizon、solver 和 bounds，只改变被审计因素，避免多个因素同时变化。

## 6. 配置

新增：

```text
configs/phase_b1_audit.yaml
configs/phase_b1_sg_levels.yaml
configs/phase_b1_oracle.yaml
```

所有审计阈值在运行前写入 `protocol_lock_phase_b1.json`。

## 7. 测试

至少新增：

- exact Oracle truth isolation；
- exact plant one-step consistency；
- SG Level配置冻结；
- paired seed consistency；
- no final-test feedback；
- all failure retention；
- model-error unit tests；
- Gramian and likelihood separation tests；
- counterfactual single-factor-change tests；
- review package completeness。
