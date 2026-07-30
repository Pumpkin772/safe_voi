# 理论推导与证明规范

## 1. 理论对象必须与实现一致

必须从实际部署预测模型、能力集合、估计误差和fallback逻辑出发。禁止为理想线性模型证明定理，而代码使用未建模硬投影、非因果信息或不同控制器。

## 2. 假设清单

至少明确：

1. 可测状态/估计状态及误差界；
2. 未知负荷集合；
3. 能力集合初始包含性；
4. 能力变化速率/跳变模型；
5. 延迟上界；
6. SG备份能力；
7. 局部线性化/模型误差界；
8. 控制与状态约束紧性；
9. 终端控制器和终端集合存在性；
10. 被动或主动辨识的激励条件。

每个假设必须在 `ASSUMPTION_EVIDENCE.csv` 中映射到参数来源、代码检查或实验。

## 3. 集合一致性

被动/主动估计器应证明或至少数值认证：

\[
c_k^{true}\in\mathcal C_k
\]

在注册误差界下保持，或给出概率覆盖保证。

若突变导致集合不再覆盖，应定义：

- 检测；
- 全局扩展；
- 覆盖恢复；
- 扩展期间采用的安全控制。

## 4. 误差管与RPI

对闭环误差：

\[
e_{k+1}=A_K(\theta)e_k+w_k,
\]

构造集合 `E` 满足：

\[
A_K(\theta)\mathcal E\oplus\mathcal W\subseteq\mathcal E,
\quad\forall\theta\in\Theta.
\]

可以使用：

- polytopic RPI；
- zonotope；
- ellipsoid；
- finite-horizon reachable tubes。

必须提供数值证书和独立顶点抽样验证。

## 5. 递归可行性

典型证明结构：

1. 时刻k优化可行；
2. 执行首个输入；
3. 实际状态留在预测tube；
4. 移位剩余序列；
5. 末端追加SG backup控制；
6. 新序列在k+1可行。

能力集合扩展时，若旧tube不再有效，必须使用预注册backup/fallback，不得直接声称无条件递归可行。

## 6. 鲁棒约束满足

证明：

\[
x_k\in\mathcal X,
\quad u_k\in\mathcal U(c_k),
\]

包括：

- 频率/ACE/tie-line；
- SG功率/GRC；
- BESS总PFR+SFR功率；
- 爬坡；
- 能量；
- 延迟扩展状态。

## 7. 分支A的安全学习条件

不要求精确双重控制最优性。应证明：

- 所有探测候选满足robust tube约束；或
- 学习轨迹违反触发条件前可切换到backup；
- backup从当前可达集合内可行；
- 信息目标不进入安全证明的必要条件。

## 8. 稳定性声明边界

可证明：

- 终端区域内渐近稳定；
- ISS/robust practical stability；
- 有限时域安全和最终有界性。

不可在未证明时声称：

- 全局渐近稳定；
- 任意能力跳变下无条件稳定；
- 任意未建模IBR下保证安全。

## 9. 数值证书输出

```text
07_THEORY/RPI_SET.json或.npz
07_THEORY/TERMINAL_SET.json或.npz
07_THEORY/VERTEX_VERIFICATION.csv
07_THEORY/CONSTRAINT_TIGHTENING.csv
07_THEORY/CERTIFICATE_REPLAY.py
07_THEORY/THEORY_CODE_TRACEABILITY.csv
```

证书脚本必须能在不运行全量仿真的情况下独立检查集合包含和约束收紧。
