# 当前 Phase B2 压缩包专家审查

## 1. 审查对象

- 文件：`D5_PHASE_B2_SCIENTIFIC_HARDENING_REVIEW_PACKAGE.zip`
- 审查文件 SHA256：`5280a39e97a99f0bd831d0d5d2f72c7faae6b04b45e5e8fcf5b644325c9b1ebe`
- 文件数量：164
- 包内逐 episode 结果：2150 行，每种方法 430 行
- 包内方法：
  - O0 conventional ACE PI：430 完成，430 科学成功；
  - O1 truth-regime identified MPC：430 完成，230 成功；
  - O2 exact-current-regime NMPC：60 真正运行，41 成功；其余 370 未评估；
  - RLS-MPC 与旧 SD-BMPC：各 430 行均是未移植占位记录，不是实际运行结果。

## 2. 总体裁决

```text
HIGH_LEVEL_SCIENTIFIC_QUESTION: VALID_AND_VALUABLE
CURRENT_PHYSICAL_MODEL: MAJOR_REBUILD_REQUIRED
CURRENT_METHOD_EVIDENCE: INSUFFICIENT
CURRENT_PROBLEM_NOT_MATERIAL_DECISION: WITHDRAW
DIRECTION_DECISION: CONTINUE_WITH_MAJOR_REBUILD
```

当前高层问题真实、明确、可证伪：黑箱 IBR 的外部可用动态或能力发生未通知变化后，错误模型是否会影响多区域频率/ACE控制；是否能够及时检测并重分配责任。该问题有工程背景，也能通过 Oracle 价值、检测时间与控制关键时间之间的关系被证伪。

但是，当前包的物理模型、Oracle、公平性、统计和仿真范围不足以支持 `PROBLEM_NOT_MATERIAL`，也不足以支持任何 proposed method 的有效性结论。

## 3. 致命问题

### F1：频率状态与惯量、阻尼单位混用

当前代码把频率状态当作 Hz，但配置使用：

- `M1=8, M2=10 pu·s/Hz`
- `D1=1.0, D2=1.2 pu/Hz`
- `R=2.5 Hz/pu`

若频率状态是 Hz，则标准摆动方程中的系数应为 `2H/f0`。在 `H=4–10 s, f0=50 Hz` 时，合理量级约为 `0.16–0.40 pu·s/Hz`，而不是 8–10。与此同时，ACE 频率偏置约 0.425 pu/Hz 又暗示阻尼应远小于 1.0 pu/Hz。当前配置混合了“频率标幺值”和“Hz”两套单位，使系统惯量/阻尼放大约数十倍。

后果：

- 初始 RoCoF 被严重压低；
- 0.06 pu 事故只产生很小频率变化；
- 2 s 二次控制在本应由惯量/PFR主导的阶段内获得异常大的作用；
- 材料性、Oracle价值和可辨识性结论全部失去定量可信度。

这是当前模型最核心的物理错误。

### F2：当前 O2 不是完整闭环 NMPC 性能上界

当前 O2：

- 只在事件后一次求解五段控制动作；
- 执行期间不滚动重求解；
- 使用非光滑投影/截断模型；
- IPOPT KKT阈值较宽；
- 19/60 运行未通过质量门；
- 仅覆盖少量场景；
- 获得当前真实负荷和内部真值信息，而普通控制器没有相同信息。

因此 O2 既不是可部署控制器，也不是可信的理论性能上界。用它判定研究问题“不具材料性”不成立。

### F3：没有实际评估 ordinary proposed controller

Phase B2 最终实验没有运行一个普通、无真值泄露的自诊断/自适应控制器。RLS-MPC和旧SD-BMPC只是占位失败记录。当前包只比较常规控制和若干 evaluation-only Oracle，不能支撑“诊断/适应方法是否有效”的创新结论。

### F4：BESS SoC边界存在潜在自由能量

当前实现通过状态投影把 SoC 截断在边界，但实际功率可能仍在惯性/一阶环节中继续放电。这会出现：

```text
p_b > 0,  E = E_min
```

即能量不再下降但仍输出功率。必须用步内能量可行功率、事件定位或互补约束保证功率—能量守恒。

### F5：PFR与SFR没有共享全部物理约束

当前中央调频功率先受 headroom 限制，之后再叠加本地 droop，最后仅按额定功率截断。这样本地PFR可能绕过：

- 视在功率/电流限制；
- 上下调头寸；
- 可持续能量；
- 部分可用容量。

正确模型必须对 `p_PFR + p_SFR + p_base` 的总交流侧功率统一施加能力约束。

### F6：12秒最终实验不属于充分的二次频率调节验证

当前 episode 仅12 s，成功标准主要是 `max_abs_frequency <= 0.20 Hz`，未要求：

- ACE恢复；
- 联络线计划交换恢复；
- 频率稳态恢复；
- SoC/能量可持续；
- 180–600 s内的资源接管。

这更像快速补充响应测试，而不是完整二次频率调节验证。

## 4. 重大问题

### M1：Oracle与普通控制器信息集不公平

O1/O2获得真实状态、真实当前负荷和真实 regime；O0依赖带噪测量与ACE。必须明确区分：

- evaluation-only upper bound；
- deployable controller；
- 统一信息集下的公平方法比较。

### M2：隐藏regime叠加多个物理原因

例如“energy limited”同时改变初始 SoC、availability 和 headroom；“headroom limited”又同时改变多项参数。这会使模式容易被人为区分，却难以判断究竟哪种能力变化导致控制效果。已知训练模式应一次只改变一个机制；复合变化留作 OOD。

### M3：availability状态缺少清晰物理解释

连续一阶 availability 变量需要解释为可用电池簇比例、逆变器模块可用率或聚合资源在线率，并给出参数来源；否则应删除，改用明确的功率能力状态。

### M4：成本函数量纲不一致

当前将 `∫|p|dt`、功率里程、频率指标直接线性相加，缺少 $/MWh、$/MW-mileage、失负荷或越限惩罚的单位来源。成本不能作为判断“问题是否有价值”的硬门。应把安全/频率/ACE价值与经济成本分开，并提供成本参数敏感性和Pareto前沿。

### M5：失败与未评估混为一谈

O1无模型、O2未注册、RLS/SD-BMPC未移植均被写成 scientific failure。必须区分：

```text
success
physical_or_control_failure
solver_failure
not_evaluated
not_applicable
```

### M6：统计门控过于脆弱

材料性要求某组全部10对都成功，一次局部求解失败便否定整组，实际混合了方法价值和求解器可靠性。应先比较成功概率，再在共同成功样本上比较连续指标，并给出失败惩罚敏感性。

### M7：可辨识性审计是有利上界而非真实在线诊断

当前检测器使用相同真实负荷和相同初始状态的名义反事实模型，普通控制器无法获得这些信息。因此 88.9% 延迟/删失是有价值的负面线索，但不能直接作为真实检测器性能，也不能据此选择主动辨识方法。

### M8：审查包不是完全自包含代码快照

包内 `source/` 主要包含新增/修改文件，部分导入的旧仓库模块缺失。下一轮必须包含完整、可直接安装运行的源码快照，或包含明确的基线归档+完整补丁，并通过全新环境一键复现测试。

## 5. 可保留内容

- 两区域频率、联络线与ACE的软件结构；
- 本地PFR固定、上层SFR单独研究的范围划分；
- hidden capability / hidden regime 的基本思想；
- ordinary controller 与 Oracle 的无真值泄露边界；
- 全量失败记录和哈希清单；
- O1/O2 框架、统计工具、场景管理和测试结构；
- “物理标签不等于控制相关regime”的方向；
- success-first、scenario-balanced 的统计意识。

## 6. 本轮严禁沿用的结论

- 不得声称研究问题不具材料性；
- 不得声称被动诊断必然无效；
- 不得声称O2代表全局或可信的最优性能上界；
- 不得声称现有模式准确率能够代表控制有效性；
- 不得将12秒结果解释为完整二次频率调节结果。
