# Phase G理论与证书规范

## 最低必须完成

1. 静态可持续性命题；
2. 可持续域终端集合的不变性证书；
3. 桥接域的功率—爬坡—能量有限时域证书；
4. CDSR预测时域内注册集合约束满足命题；
5. action transaction、restoration和backup与理论边界说明。

## 递归可行性

只有在：

- 当前cell属于可持续域；
- terminal set非空；
-所有delay/model顶点共同不变；
- shift-and-append候选可行；
-实际代码使用同一集合、同一backup；

时才能声称：

```text
conditional recursive feasibility on the certified sustainable domain
```

桥接域不得声称无限时域递归安全，除非显式建模并证明慢速接管。

## 证书输出

```text
05_THEORY/STATIC_FEASIBILITY_CERTIFICATE.csv
05_THEORY/SUSTAINABLE_RPI_SET.npz
05_THEORY/SUSTAINABLE_RPI_CERTIFICATE.json
05_THEORY/BRIDGE_CERTIFICATES.parquet
05_THEORY/THEOREMS_AND_PROOFS.md
05_THEORY/NUMERICAL_CERTIFICATE_REPRODUCTION.py
05_THEORY/UNSUPPORTED_THEORY_CLAIMS.md
```

证书脚本必须在无cvxpy的最小依赖环境中至少完成已有集合的独立验证；集合生成可依赖优化器。
