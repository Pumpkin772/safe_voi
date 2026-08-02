# CDSR-MPC修订与实时求解规范

## 1. 不确定预测

对所有delay/capability/model顶点共享控制序列：

\[
z_{i+1|k}^{(q)}=A_qz_{i|k}^{(q)}+B_qv_{i|k}+E_q\hat d_k.
\]

## 2. 全部硬约束

必须对全部顶点/误差margin约束：

- SG valve；
- SG mechanical power；
- SG GRC；
- BESS actual power；
- BESS actual ramp；
- BESS total PFR+SFR；
- BESS energy；
- tie flow physical limit；
- delay pipeline consistency。

性能约束可以有高代价slack；资源物理约束无slack。

## 3. 实际BESS功率和能量

MPC中能量不得用request近似：

\[
E_{i+1}=E_i-rac{T_sS_B}{3600}
\left(\frac{[p_{b,i}^{actual}]^+}{\eta_d}+\eta_c[p_{b,i}^{actual}]^-\right).
\]

若为保持QP使用正负分裂变量，必须与delay actuator state一致。

## 4. 终端模式

- `SUSTAINABLE`：全部顶点进入负荷依赖终端集合；
- `BRIDGE_ONLY`：满足bridge horizon、能量和接管条件；
- `PHYSICALLY_INFEASIBLE`：调用预注册紧急backup并计为物理失败，不伪装成普通可行episode。

## 5. 可行性恢复

恢复QP只允许放松：

- frequency envelope；
- ACE envelope；
- tie performance envelope。

不允许放松：

- power；
- ramp；
- energy；
- GRC；
- delay history；
- terminal/bridge物理条件。

## 6. 求解加速

必须记录：

```text
canonicalization/build time
solver time
warm-start status
iteration count
factorization reuse
number of vertices
number of variables/constraints
```

优先顺序：

1. DPP参数化；
2. 稀疏矩阵预构建；
3. 直接OSQP接口；
4. condensed/sparse formulation对比；
5. warm start；
6. 删除数学冗余顶点，但必须证明不改变外包。

实时Gate：

\[
p99(t_{solve})<0.5T_s.
\]
