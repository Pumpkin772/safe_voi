# 方向5：VOI-ACCR-MPC 结果驱动的一次性科研执行包

## 命名

```text
中文：方向5
英文：DIRECTION5
代码标识：direction5
```

## 使用方式

将本目录放入当前真实研究仓库：

```text
research/direction5_voi_accr_mpc_result_driven/
```

然后只向Codex发送 `PROMPT_TO_CODEX.txt`。

本包不再把研究拆成大量短阶段，也不要求每个小Gate后停止。Codex应围绕一个明确的论文目标自主进行开发、诊断、实验和修复，直到：

1. 获得满足独立验证标准的论文级正面结果；或
2. 在预注册、物理合理的设计空间内完成充分搜索，形成无法被简单实现缺陷推翻的决定性负结果。

禁止为了获得正面结果而修改final数据、删除不利结果、降低标准或扩大事故。目标是获得可信结果，不是制造结果。

## Git规则

在达到“集成开发里程碑”之前：

```text
禁止 git add
禁止 git commit
禁止 git tag
禁止 push
```

Codex使用：

```text
scratch_direction5/
research_outputs_working/
progress_working.json
```

保存中间状态。

只允许三次提交：

1. 集成开发目标达成后；
2. 独立validation达成后；
3. final与审查包完成后。

若最终为决定性负结果，只在负结果证据闭合后提交一次。
