# R3 state-selective single-window prototype

The prototype was fixed before its paired nonlinear result:

```text
objective                 sg_conserving_16
probe                     control-aligned surplus
amplitude                 0.006 pu
physical duration         8 s
maximum windows           1
certificate validity      240 s
causal state screen       Vhat_H >= 0.08
evidence                   5 Hz dynamic likelihood set
```

The screen compares the contract candidate set with the high-power posterior
set from the same public state, actual-POI load estimate, measured SoC, applied
action history, horizon, and controller objective.  It does not read realized
capability or future load.  The `0.08` threshold is the incremental BESS
start/return movement term for a smooth baseline,
`2 * 4 * (0.006 / 0.060)^2`; complete closed-loop value is still measured by
the paired controllers rather than inferred from this local term.

## Mechanism path 8256

The screen abstained at `308 s` (`Vhat_H=2.69e-9`) and permitted one window at
`324 s` (`Vhat_H=0.166065`).  The high truth was correctly reduced to the four
high-power candidates at `334.2 s`.

| truth | method | grid cost (s) | SG mileage (pu) | BESS throughput (pu s) | high certified |
| --- | --- | ---: | ---: | ---: | --- |
| high | contract | 70.217300257 | 2.365099399 | 27.701515906 | n/a |
| high | exploit-only | 69.895746759 | 2.379084051 | 27.588505494 | no update allowed |
| high | dual | 69.789239008 | 2.381619237 | 28.638844111 | yes |
| low | contract | 70.437405400 | 2.371089059 | 27.715882222 | n/a |
| low | exploit-only | 70.348365921 | 2.374704418 | 27.631148455 | no update allowed |
| low | dual | 70.348365921 | 2.374704418 | 27.631148455 | no |

For the high truth, total grid value was `+0.428061249 s`, of which
`+0.106507751 s` was pure information value (`exploit-only - dual`).  Pure
information changed SG mileage by `-0.002535186 pu` and BESS throughput by
`-1.050338617 pu s` under the baseline-minus-method sign convention, so the
result remains conditional on an explicit resource-price region.

For the low truth, exploit-only and dual were numerically identical.  Relative
to contract, the frequency peak increment was zero, ACE cost changed by
`-0.0467%`, and tie cost by `-0.4914%`.  Both truth branches were physically
successful with zero solver failures and zero fallback calls.

This is a development mechanism point, not evidence for an independent
positive region.  The next fixed replication paths remain seeds `8103`, `8104`,
and `8105`; no new seed is selected from the result.

## Fixed high-truth replication

| seed | value-screen evaluations | probe windows | high certified | total grid value (s) | pure information grid value (s) |
| ---: | ---: | ---: | --- | ---: | ---: |
| 8103 | 1 | 0 | no | 0 | 0 |
| 8104 | 0 | 0 | no | 0 | 0 |
| 8105 | 7 | 0 | no | 0 | 0 |
| 8256 | 2 | 1 | yes | +0.428061249 | +0.106507751 |

For 8103 the only eligible state had numerical-zero predicted value.  Seed
8104 never reached the basic binding eligibility condition.  Seed 8105 was
screened seven times; its largest predicted value was approximately `0.04`,
below the fixed `0.08` threshold.  Exploit-only and dual were exactly equal to
contract MPC in all three abstention paths.  This removes the former
`-0.104568500 s` information loss on seed 8105 without changing the contract
trajectory.

All four high-truth paths were physically successful with zero solver failures
and zero fallback calls.  The current development evidence is therefore one
observed positive state-region entry and three exact abstentions, not four
positive episode results.  More consecutively fixed development paths are
needed to estimate how often the registered stochastic process enters the
region and whether realized pure information value is consistently positive
conditional on entry.
