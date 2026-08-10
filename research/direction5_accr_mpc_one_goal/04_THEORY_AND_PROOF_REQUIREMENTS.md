# 理论和证明要求

## 1. 必须给出的严格结果

### P1 分配中性恒等式
命令层总SFR不变。

### P2 集合包含性
在模型和误差假设下真候选不被错误删除。

### P3 有限时域安全探测
对所有候选和loss branch满足注册约束。

### P4 可区分性充分条件
输出集合分离大于噪声直径时能够排除候选能力类。

### P5 认证下界条件
能力静止和误差界条件下，认证power/ramp/delay集合有效。

### P6 能力突降边界
无预警能力下降不能同瞬间保证；必须依赖追索。

### P7 合同终端/追索
至少完成Plant A合同终端集和loss branch一步或多步追索证书。

## 2. 可选高级结果

- 信息价值与集合直径上界；
- probe library最优性界；
- event-trigger避免Zeno；
- certificate expiry的概率/确定性界；
- bridge有限能量证书。

## 3. 声明收缩

若不能证明递归可行，不得写global recursive safety。

可接受声明：

```text
registered-set finite-horizon safe active capability certification
with a separately certified contract fallback
```

## 4. 证书复现

保存：

```text
THEOREMS_AND_PROOFS.md
ASSUMPTIONS.md
CERTIFICATE_DATA.npz
CERTIFICATE_STATUS.json
REPRODUCE_CERTIFICATES.py
```

代码必须实际使用同一合同、终端集和probe safety set。
