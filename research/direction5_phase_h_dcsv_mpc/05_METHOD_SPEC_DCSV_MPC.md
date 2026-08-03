# DCSV-MPC 方法规范

## 1. 信息流

```text
公共测量
  ├─ disturbance observer → xhat, dhat, Dset
  └─ capability estimator → Cset
                         ↓
              domain classifier
         sustainable / bridge / infeasible
                         ↓
                    DCSV-MPC
```

## 2. Sustainable MPC

围绕：
\[
x^\star(\hat d)
\]

对：
- disturbance set；
- capability set；
- delay set；
- model mismatch

进行鲁棒预测。

所有不确定顶点共享同一控制序列。

终端：
\[
e_N\in\mathcal X_f(\hat d).
\]

## 3. Bridge MPC

状态增加：
- remaining energy；
- remaining time to slow reserve；
- required bridge power。

优化必须保证：
- power；
- ramp；
- energy；
- frequency；
- ACE；
- tie；
- slow reserve arrival。

终端为进入可持续域或满足预注册bridge target。

## 4. Infeasible supervisor

提前返回：
```text
physical_infeasibility_certificate
```

并执行预注册 emergency/SG backup。不得让求解器无限重试。

## 5. Feasibility restoration

只允许放松：
- performance envelope；
- settling target。

不得放松：
- SG/BESS power；
- ramp；
- energy；
- delay causality；
- physical capability；
- safety boundary。

## 6. Baselines

- SG-only PI；
- fixed allocation PI；
- nominal offset-free MPC；
- RLS/adaptive MPC；
- contract robust MPC；
- true-capability Oracle；
- DCSV-MPC。

所有MPC必须是真实滚动优化。
