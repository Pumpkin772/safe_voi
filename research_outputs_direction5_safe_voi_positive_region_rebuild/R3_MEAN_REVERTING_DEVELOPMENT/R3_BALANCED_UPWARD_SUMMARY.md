# R3 balanced upward-demand exploration

Seeds `8143`, `8154`, and `8170` were fixed before this explicitly exploratory
cell was calculated.  Each uses a positive, both-area contingency of at least
0.040 pu.

| seed | windows | high certified | total grid value (s) | pure information grid value (s) |
| ---: | ---: | --- | ---: | ---: |
| 8143 | 2 | no | +0.406063901 | -0.000146452 |
| 8154 | 2 | no | -1.767607740 | 0.000000000 |
| 8170 | 2 | no | -0.479297883 | 0.000000000 |

All nine trajectories were physically successful, with zero solver failures
and zero fallback calls.  None reproduced the positive pure-information value
of mechanism seed 8256.  The direct control-aligned action was beneficial in
8143 and harmful in 8154 and 8170; posterior use added no reproducible value.

The SG-conserving-16 positive point is therefore isolated within the tested
development paths and is not eligible for validation.  No further scenario
subdivision is performed.  The next scientific diagnostic is the
evaluation-only perfect-capability rolling MPC on the same paths: it separates
absence of intrinsic capability-information value from failure of the causal
posterior-recourse implementation.

## Perfect-capability value diagnostic

The evaluation-only Oracle was then run on four already-consumed development
paths.  It used the same causal load observer and rolling objective as contract
MPC, but replaced the capability candidate set by the realized power, ramp,
and delay at each control instant.  It is not an ordinary deployable
controller.

| seed | contract - Oracle grid cost (s) | contract - dual (s) | exploit-only - dual (s) | interpretation |
| ---: | ---: | ---: | ---: | --- |
| 8256 | +0.724216864 | +0.474959590 | +0.031964095 | intrinsic value is material; dual recovers 65.58% of the Oracle gap |
| 8105 | -0.134764740 | -0.378841147 | -0.104568500 | even perfect capability is harmful on this path |
| 8127 | +0.070612592 | +0.011675166 | -0.064443505 | intrinsic value exists, but posterior recourse loses most of it through tie-line cost |
| 8143 | +0.032699000 | +0.406063901 | -0.000146452 | the large total improvement is a probe-control effect, not information value |

All four Oracle trajectories were physically successful, with zero solver
failures and zero fallback calls.  The positive-value region is therefore
nonempty in development, but high capability alone is not sufficient: the
same high-capability branch has both positive and negative perfect-information
value.  The present controller is missing a causal counterfactual-value gate.
It also fails to isolate acquisition from control benefit because the
exploit-only probe overlay can materially change closed-loop cost without
producing a capability certificate.  The next design question is whether a
public-state, candidate-model calculation can predict the sign of the Oracle
gap before probing and abstain exactly when that value is nonpositive.
