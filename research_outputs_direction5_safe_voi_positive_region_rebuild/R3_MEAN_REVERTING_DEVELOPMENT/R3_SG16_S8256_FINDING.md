# R3 SG-conserving-16 mechanism result: development seed 8256

Only the registered SG/BESS movement-allocation condition changed from the
initial R3 comparison.  The load, capability transition, estimator, 0.003 then
0.006 pu control-aligned actions, two-window limit, and 240 s information
validity remained unchanged.

## High-capability branch

| method | grid-service cost (s) | SG mileage (pu) | BESS throughput (pu s) | frequency peak (Hz) |
| --- | ---: | ---: | ---: | ---: |
| contract | 70.217300257 | 2.365099399 | 27.701515906 | 0.223116201 |
| exploit-only | 69.774304763 | 2.391577266 | 27.543697919 | 0.223116201 |
| dual | 69.742340668 | 2.394777031 | 28.093465989 | 0.223116201 |

The dual controller removed every 0.045 pu candidate at 338.2 s and retained
all four 0.068 pu ramp/delay candidates.  Pure information value
`exploit-only - dual` was `+0.031964095 s` in grid-service cost.  Total
`contract - dual` grid-service value was `+0.474959590 s`.  Posterior use also
increased BESS throughput by `0.549768069 pu s` relative to exploit-only, so
the result is a grid-service/resource-price boundary rather than Pareto
dominance.

## Low-capability branch

The dual controller did not form a high-power certificate.  It retained the
four 0.045 pu candidates after two windows and stopped for futility.

```text
contract - dual grid-service value: +0.170233127 s
dual - contract frequency peak:       0.000000000 Hz
ACE relative change:                 -0.1098%
tie relative change:                 -0.8456%
```

Both branches were physically successful.  Every trajectory attempted 181
rolling optimizations with zero solver failures and zero fallback calls.  This
is a positive development mechanism point, not independent evidence.

Before any replication result is calculated, high-capability development
seeds `8100`, `8101`, and `8102` are fixed as the first replication set.  Each
uses contract, exploit-only, and dual on the same paired path.  The
configuration is not changed between those seeds.
