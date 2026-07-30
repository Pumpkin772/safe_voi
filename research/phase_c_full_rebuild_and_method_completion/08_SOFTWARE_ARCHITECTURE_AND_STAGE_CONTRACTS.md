# 软件架构、文件契约和阶段自动执行

## 1. 推荐目录

```text
project_root/
├─ pyproject.toml
├─ environment.yml
├─ src/d5freq/
│  ├─ models/
│  ├─ estimation/
│  ├─ identification/
│  ├─ controllers/
│  ├─ optimization/
│  ├─ experiments/
│  ├─ evaluation/
│  └─ utils/
├─ configs/phase_c/
├─ scripts/phase_c/
├─ tests/phase_c/
├─ research/phase_c_full_rebuild_and_method_completion/
├─ research_outputs/
├─ results_phase_c/
├─ figures_phase_c/
├─ logs_phase_c/
└─ progress/
```

## 2. 一键入口

必须建立：

```text
python scripts/phase_c/run_master_pipeline.py --config configs/phase_c/master.yaml
```

支持：

```text
--resume
--start-stage C4
--stop-after-stage C6
--dry-run
```

默认自动从C0运行到C9，不等待用户确认。

## 3. 阶段契约

每阶段产生：

```text
progress/Cx_status.json
progress/Cx_gate_decision.json
logs_phase_c/Cx/
```

字段至少：

```json
{
  "stage": "C4",
  "status": "PASSED",
  "inputs_sha256": {},
  "outputs": [],
  "tests": {},
  "success_criteria": {},
  "failure_diagnosis": [],
  "repairs": [],
  "next_stage": "C5"
}
```

## 4. 配置冻结

- `development.yaml`可改；
- `validation.yaml`经C3后锁定；
- `final.yaml`经C5分支决定后锁定；
- 锁定文件生成SHA256；
- final运行后任何配置变化都必须导致管线拒绝继续并记录违规。

## 5. 代码质量

- 类型提示；
- docstring标注公式编号；
- 无绝对Windows路径；
- 任何随机过程显式seed；
- 所有求解器状态记录；
- 对核心公式单元测试；
- 全新环境 `pip install -e .` 可运行。

## 6. 数据格式

- 逐episode指标：Parquet；
- control-grid轨迹：Parquet/Zstd；
- 全细步轨迹：失败episode、代表episode、Oracle校核episode；
- 其余全细步轨迹可由seed/config重生，但必须保存积分累积量和极值审计；
- 图表数据单独CSV/Parquet，不能只提供PNG。

## 7. 自动修复日志

Codex每次自动修复必须写入：

```text
progress/REPAIR_LEDGER.md
```

包括：失败类型、证据、修改文件、为何不改变科学标准、重跑结果。

## 8. 致命停止

仅以下情况允许提前停止：

- 源码基线无法恢复；
- corrected Plant A/Plant B无法建立或验证；
- 材料性在两个模型上均失败；
- 结构不可辨识且集合鲁棒控制也没有控制价值；
- 核心求解器在合理重构后仍无法提供可信结果。

即使提前停止，也必须运行C9的负结果归档模式并生成最终ZIP。
