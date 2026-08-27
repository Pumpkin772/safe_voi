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
