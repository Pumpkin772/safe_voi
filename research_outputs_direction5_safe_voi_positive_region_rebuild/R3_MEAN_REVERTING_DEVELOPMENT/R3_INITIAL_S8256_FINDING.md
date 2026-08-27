# R3 initial paired nonlinear result: seed 8256, high capability

The load distribution and controller configuration were fixed at commit
`c4b4b12` before these trajectories were calculated.  All three runs used the
same 720 s full nonlinear Plant-A load, capability, and measurement paths.

| method | grid-service cost (s) | SG mileage (pu) | BESS throughput (pu s) | frequency peak (Hz) |
| --- | ---: | ---: | ---: | ---: |
| contract | 78.004901824 | 2.268321640 | 25.873510734 | 0.224886211 |
| exploit-only | 77.829016642 | 2.302731436 | 25.434826048 | 0.224886211 |
| dual | 77.829043991 | 2.302728147 | 25.434456873 | 0.224886211 |

All trajectories were physically successful.  Each controller attempted 181
optimizations with zero solver failures and zero fallback calls.  The dual
controller correctly removed all 0.045 pu power candidates at 354.2 s and kept
all four high-power ramp/delay candidates; no model inconsistency occurred.

Paired value coordinates, with positive meaning lower cost for the second
method, were:

```text
contract - dual:
  grid-service +0.175857833 s
  SG mileage   -0.034406507 pu
  BESS energy  +0.439053862 pu s

exploit-only - dual (pure capability-information effect):
  grid-service -0.000027349 s
  SG mileage   +0.000003288 pu
  BESS energy  +0.000369176 pu s
```

Thus the total grid-service improvement came from the control-aligned action,
not from posterior use.  The dynamic estimator succeeded, but the larger
deliverability set did not materially change the rolling MPC allocation.  This
is a retained zero-information-value point, not a positive result.
