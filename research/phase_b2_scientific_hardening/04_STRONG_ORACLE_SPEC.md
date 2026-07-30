# 强 Oracle 规范

## 1. 目的

Oracle 只用于回答“若当前真实 plant 动态已知，该黑箱资源理论上能提供多少频率控制价值”。它不是 proposed controller。

## 2. Oracle 层级

### O0 — No-IBR / conventional baseline

LQI/PI，仅使用 SG。

### O1 — Truth-regime identified model MPC

知道当前 regime 标签，但使用离线辨识模型。用于量化辨识模型失配。

### O2 — Exact-current-regime nonlinear NMPC

知道当前真实 plant 状态和当前真实参数，但不知道未来 load 或未来 regime。必须使用多动作优化。

### O3 — Clairvoyant exact NMPC（可选）

知道未来 load/regime，仅用于不可部署 ceiling，不得用于 materiality 的主要结论。

## 3. O2 优化

建议使用 CasADi/IPOPT multiple shooting。

决策：

`U = {u_g[k+i], u_b[k+i]}, i=0..N-1`

目标：

`J = Σ(q_f ||Δf||² + q_ace ||ACE||² + r_g ||u_g||² + r_b ||u_b||² + s_g ||Δu_g||² + s_b ||Δu_b||²) + terminal cost`

约束：

- exact nonlinear Plant B；
- SG reserve 与 GRC；
- IBR command/power/rate/SoC limits；
- frequency 和 tie-line 安全约束；
- 相同控制周期和测量信息边界。

建议：

- horizon：8、10、12 s，只在 validation seeds 选择一次；
- control blocking：2 s；
- integration：0.05–0.1 s；
- warm start；
- 代表场景 3 个不同初始化；
- 记录 KKT residual、constraint residual、iteration、solve time。

## 4. 必须通过的 Oracle 验证

1. 同一动作序列下 Oracle rollout 与独立 simulator 对齐。
2. O2 不能只搜索 15 个第一动作。
3. O2 不能在 horizon 内保持一个常数动作。
4. 在小型短 horizon 案例中，与 dense grid / dynamic programming 近似交叉验证。
5. 增长 horizon 不得因实现缺陷普遍恶化。
6. O2 若差于 O0，必须输出局部最优、估计误差或成本权重解释，不得自动称其为上界。
7. Oracle 结果必须同时报告频率、ACE、控制成本、约束和求解质量。
