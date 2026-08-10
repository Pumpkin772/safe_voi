# M1 selected integrated prototype

Status: `PASS`

Selected run: `VOI_V12_C13_M1_VALUE_REGIONS`.

The selected Direction5 VOI-ACCR-MPC uses a 0.0025 pu two-step zero-mean
biphasic allocation probe around the current contract-MPC optimum, a causal
power/ramp/delay candidate set, and a 4 s conditional certificate.  A missing
certificate is not a trigger.  The ordinary controller receives actual BESS
POI power but no true capability, true load, future event, or future mode.

## Registered M1 outcome

- eight full 300 s nonlinear Plant-A development scenarios;
- four power/ramp × low/high-SG high-value scenarios judged worthwhile;
- four crossed low-value controls judged not worthwhile;
- worthwhile mean tie-IAE improvement: 3.7760%;
- worthwhile mean ACE-IAE improvement: 1.3742%;
- candidate diameter reduction: 50.0%;
- signing-time false optimism: 0/4;
- cumulative probe command L1 cost: 0.08 pu-s;
- hard physical violations: 0;
- fallbacks: 0;
- maximum frequency-peak delta versus contract MPC: 0 Hz;
- not-worthwhile probes: 0/4;
- not-worthwhile maximum action and performance difference: 0;
- maximum unmetered responsibility jump: 2.17e-18 pu.

This is a development result, not independent validation.  M2 must use new
seeds and both full nonlinear Plant A and native Plant B.  No paper-level
positive claim is authorized by M1 alone.
