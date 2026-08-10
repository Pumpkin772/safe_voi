# 实验、统计和预期结果协议

## 1. 新的数据防火墙

旧closure final seeds仅用于历史负结果，不得用于新方法开发。

建议新分割：

```text
development: 200–249
validation: 250–299
final: 400–459
```

## 2. 因素独立

manifest显式列出：
- Plant；
- period；
- SG tension；
- capability mechanism；
- capability change time；
- load event time/area/sign/magnitude；
- SoC；
- noise；
- jitter；
- dropout；
- probe eligibility；
- known/OOD；
- contract violation。

禁止seed取模绑定多个因素。

## 3. 核心场景

每个episode：

```text
nominal warm-up >=60 s
→ random capability change
→ load event independently before/after/simultaneous
→ full rolling 300–600 s
```

normal1h单独真实运行。

## 4. 方法

- SG-only anti-windup PI；
- fixed allocation PI；
- contract MPC；
- passive set-adaptive MPC；
- safe persistent-excitation baseline；
- periodic probe baseline；
- unsafe/no-gate probe消融；
- ACCR-MPC；
- perfect-capability Oracle。

## 5. 主要指标

### 安全
- success；
- max frequency；
- frequency safety noninferiority；
- ACE/tie terminal recovery；
- hard violations；
- fallback；
- solver。

### 信息
- candidate set size/diameter；
- delay candidate count；
- false optimism；
- certificate time；
- certificate duration；
- nonzero certified surplus；
- information gain；
- probe cost。

### 控制价值
- ACE IAE；
- tie IAE/RMS；
- SG mileage；
- BESS energy；
- value recovery ratio；
- frequency noninferiority。

## 6. 统计

- success-first；
- paired failure；
- scenario-balanced means；
- paired absolute differences；
- seed/design-cell hierarchical bootstrap；
- materiality-positive subset预注册；
- all-scenario safety与subset performance分开；
- multiple-comparison correction；
- value recovery denominator≤0时标记NA。

## 7. 现实的预期结果

根据当前包：
- passive surplus activation约0；
- perfect information主要改善ACE/tie；
- frequency不一定改善。

因此目标不是强迫频率变好，而是：

1. frequency安全不劣；
2. 能力证书显著提高；
3. 回收ACE/tie/SG-mileage的信息价值。

### 预期范围（非事实）
- eligible场景能力集合直径降低40%–80%；
- certificate success 50%–85%；
- probe增量频偏0.003–0.02 Hz；
- ACE/tie probe代价0%–5%；
- materiality-positive cells回收perfect value的40%–70%；
- ACE改善3%–8%；
- tie改善5%–10%；
- SG mileage改善3%–10%；
- overall frequency peak变化−1%至+1%；
- success drop≤1pp；
- hard violation=0。

Codex不得把这些范围当作必须通过调参实现的答案。
