# R3 numerical-screen selective V3 panel

V3 replaces the falsified `0.08` local threshold with the preregistered
`1e-6` numerical relevance screen.  All physical, estimation, probe, objective,
continuation, and seed settings are unchanged from V2.  Exact
acquisition-matched weak-Pareto value remains the final information decision.

## High-capability seed 8109

```text
causally eligible states                0
numerical-screen entries                0
exact second-stage evaluations          0
acquisition windows                     0
frequency peak                          0.102435273 Hz
grid-service cost                       48.672952982 s
attempted optimization calls            181
solver failures / fallbacks             0 / 0
hard physical violations                0
```

The trajectory remains a strict contract-MPC abstention.  Lowering the first
stage to numerical relevance does not alter states that fail the causal and
physical eligibility conditions.
