# 文件放置和使用流程

## 1. 推荐位置

在 Codex 原来的真实 Git 项目根目录中创建：

```text
research/phase_b1_bottleneck_audit/
```

项目根目录应能看到：

```text
pyproject.toml
src/d5freq/
configs/
scripts/
tests/
```

把本启动包全部文件放入 `research/phase_b1_bottleneck_audit/`。

## 2. 不要在哪里开发

不要直接在：

```text
D5_FROM_SCRATCH_SD_BMPC_REVIEW_PACKAGE(1).zip
```

或其解压后的审查目录中修改。

如果原 Git 仓库已经丢失，可将审查包中的 `source/` 复制到一个新的工作目录，再初始化/恢复 Git，但应先保存其文件哈希并建立 `phase-a-final-reviewed-v2` baseline commit。

## 3. 给 Codex 发什么

直接复制 `GOAL_TO_SEND_CODEX.txt` 的全文。

## 4. 下一轮交给外部检查

只上传：

```text
D5_PHASE_B1_BOTTLENECK_AUDIT_REVIEW_PACKAGE.zip
```

本轮不要同时做新方法。外部检查瓶颈结论后，再决定：

- CORA-MPC；
- 安全主动辨识/双重控制；
- 简化 trust-aware adaptive MPC；
- 或重新定义问题场景。
