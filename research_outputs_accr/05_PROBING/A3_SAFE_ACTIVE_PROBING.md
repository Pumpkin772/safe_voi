# A3 safe active capability probing

Status: **PASS**, zero scientific repair rounds.

Selected event-triggered policy:

```text
probe: staircase_5
amplitude: 0.0025 pu
normalized sequence: [0.5, 1.0, 0.0, -1.0, -0.5]
control period: 2 s
```

For each probe component `q`, the issued commands satisfy
`u_g = u_g0 - q` and `u_b = u_b0 + q`; their sum is unchanged. This is only
command-level allocation neutrality. BESS delay, ramp, saturation, and a loss
of surplus make actual delivered power non-neutral.

The development screen rejected candidates before considering information if
any extreme branch violated frequency, ACE, tie-line, SoC, SG, or BESS limits.
The selected policy was then replayed against all 36 registered
power/ramp/delay candidates, including the contract-only/no-surplus branch.
All 36 were safe and hard violations were zero. Worst incremental frequency
peak was 0.005516 Hz, normalized incremental ACE cost 0.01950, and normalized
incremental tie cost 0.005960, below 0.02 Hz and 5% registered limits.

Twenty validation episodes from materiality-positive cells retained truth and
had zero false optimism. Candidate count fell from 36 to 3--9. Weighted
power/ramp/delay diameter reduction was 54.29%--80.0% (mean 63.29%); 20/20
episodes exceeded the registered 40% reduction. Certificates have a finite
40 s validity and must be revoked on estimator reset or change evidence.

The first execution attempt was stopped by the Windows startup descendant
count before scientific computation. The process cap was aligned with the
already validated A0 guard: worker plus at most two Windows/runtime descendants,
far below the historical 18-process spawn failure. The completed attempt used
at most two descendants, 198,578,176 bytes task-private memory, and 52.88%
system commit.

