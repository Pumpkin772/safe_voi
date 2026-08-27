# Seed 8103 completed paired result

The contract rerun completed after the external memory workload subsided.  The
exploit-only trajectory also completed; the first dual attempt was stopped by
the unchanged system-memory threshold before writing a scientific result.  A
later identical dual rerun completed after external memory was released.

| method | grid-service cost (s) | SG mileage (pu) | BESS throughput (pu s) | probe windows |
| --- | ---: | ---: | ---: | ---: |
| contract | 44.456247777 | 2.414874731 | 22.028386458 | 0 |
| exploit-only | 44.614723139 | 2.417671846 | 22.126866707 | 1 |
| dual | 44.614723139 | 2.417671846 | 22.126866707 | 1 |

Both completed trajectories were physically successful, with frequency peak
`0.084939285 Hz`, 181 optimization attempts, zero solver failures, and zero
fallback calls.  Acquisition alone increased grid-service cost by
`0.158475362 s`.  Only one eligible evidence window occurred and the high
capability truth was not certified.  Exploit-only and dual are exactly equal,
so pure information value is zero.  This path exposes a missing selective-VoI
abstention condition: one causally eligible window is not useful when the
second window required for certification is unlikely to occur.

The dual stop occurred after 131.203 s at total system commit fraction
`0.92020`; its process tree peak was only 460,300,288 bytes.  No controller
threshold or memory limit is changed for the rerun.
