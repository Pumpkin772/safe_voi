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

## High-capability seed 8110

The first numerically relevant state occurred at `520 s`, before either of the
post-panel diagnostic states was used online.

```text
causally eligible states before probe   7
numerical-screen entries                1
exact second-stage evaluations          1
local high-posterior value              0.039454927
worst high-branch information value    +0.309811946
low-branch information value            0.000000000
continuation paths / steps               8 / 47
internal second-stage solves / failures 3024 / 0
acquisition windows                     1
high-power certification time           530.2 s
frequency peak                          0.203042591 Hz
grid-service cost                       60.197435164 s
attempted optimization calls            3212
solver failures / fallbacks             0 / 0
hard physical violations                0
```

The actual-POI estimator retained all four and only the high-power candidates,
leaving ramp and delay uncertain.  Relative to the identical no-probe contract
trajectory (`60.833668059 s`), total grid-service cost decreased by
`0.636232895 s`.  A matched exploit-only run is required before attributing any
part of this total difference specifically to information.

The matched exploit-only run completed with the same acquisition window and no
certificate use.  The paired decomposition is:

```text
contract cost                          60.833668059 s
exploit-only cost                      60.421479039 s
dual cost                              60.197435164 s
contract minus exploit                +0.412189020 s
exploit minus dual (pure information) +0.224043875 s
contract minus dual (total value)     +0.636232895 s
frequency peak, all arms                0.203042591 Hz
ACE IAE, contract / exploit / dual      7.152914 / 7.109346 / 7.074935 pu s
tie IAE, contract / exploit / dual      2.121784 / 2.107300 / 2.088180 pu s
```

Both the control-aligned acquisition action and subsequent use of the retained
high-power set improved this high-capability trajectory.  This is a single
development pair; replication across independent trajectories remains
unresolved.

### Low-capability branch for seed 8110

The ordinary controller again entered at `520 s` without knowing the true
capability.  The actual-POI estimator retained all four and only the low-power
candidates; it did not issue a high-power certificate and did not report model
inconsistency.

```text
acquisition windows                     1
false high-power certification          0
frequency peak                          0.203042591 Hz
grid-service cost                       60.978767786 s
ACE IAE                                  7.166736747 pu s
tie IAE                                  2.123213852 pu s
attempted optimization calls            3212
solver failures / fallbacks             0 / 0
hard physical violations                0
```

The matched exploit-only and contract references are still required to
quantify low-capability acquisition cost.  The first exploit-only attempt was
terminated by the system-commit guard after an unrelated machine-wide commit
spike; the scientific episode produced no result and will be repeated unchanged
after system memory returns below the preflight limit.

The unchanged repeat and contract reference subsequently completed:

```text
contract cost                          61.079598040 s
exploit-only cost                      60.978767786 s
dual cost                              60.978767786 s
contract minus exploit                +0.100830254 s
exploit minus dual (pure information)  0.000000000 s
contract minus dual (total value)     +0.100830254 s
frequency peak, all arms                0.203042591 Hz
ACE IAE, contract / exploit / dual      7.173886 / 7.166737 / 7.166737 pu s
tie IAE, contract / exploit / dual      2.128790 / 2.123214 / 2.123214 pu s
BESS throughput, contract / acquisition 26.468688 / 26.422087 pu s
SG mileage, contract / acquisition      2.450687 / 2.451028 pu
```

The low-capability dual and exploit-only trajectories are exactly identical in
every reported closed-loop quantity.  Acquisition improves the registered grid
objective and ACE/tie response without changing the frequency peak; its only
adverse resource movement is a `0.000341066 pu` increase in SG mileage.  Thus
this paired state exhibits the intended structure: low capability is not
misclassified and is non-adverse in the physical grid metrics, while high
capability obtains strictly positive incremental information value.
