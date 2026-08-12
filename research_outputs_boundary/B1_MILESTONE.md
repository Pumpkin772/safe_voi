# B1 frozen development result

The registered Direction5 VOI boundary development domain is now frozen.
This is a development result, not the independent boundary confirmation.

## Mathematical boundary

- Initial Latin-hypercube points: 512.
- Adaptive boundary points: 1024 (the registered maximum).
- Total retained points: 1536; no point was removed.
- Direct zero-value points in the adaptive design: 297.
- Adaptive points checked with the universal safe-probe upper bound: 727.
- Upper-bound-positive points requiring exact recourse: 0.
- Unclassified fraction: 0.
- Maximum registered perfect-information value: 0.013002320336355844.
- Maximum safe-probe net-value upper bound: -0.014978097885527841.
- Minimum safe-probe net-value upper bound: -0.0628692850639796.
- Boundary/upper-bound solver calls: 14,603; failures: 0.

The development positive-value region is therefore empty.  The selected
policy is no probe: in every classified point the selective policy returns the
same contract-MPC action object without an overlay or second optimization.

## Exact versus predecessor heuristic

Across the combined 1536-point map, the predecessor heuristic labelled 82.03%
of points positive although the registered exact/upper-bound classification
proved every point zero.  Sign agreement was 17.97%.  Its largest value was
0.16664564235627172, whereas the largest registered perfect-information value
was 0.013002320336355844.

## Full nonlinear Plant-A ordering check

The paired 120 s development replay `B1_NONLINEAR_PAIR_001` used the same seed,
load, capability event, and full nonlinear plant for contract MPC and the
evaluation-only perfect-capability comparator.  Both runs had no hard or
command violation, no solver failure, and no fallback.  Perfect information
reduced ACE IAE by 0.019975486986191893 pu s and tie IAE by
0.00913397379531139 pu s; peak frequency improved by only
0.00006101701279026539 Hz.  This preserves the model ordering: capability
information has a small positive value, but its value is below the minimum
closed-loop cost imposed by every registered safe probe.

## Frozen next step

No probe, objective weight, design range, sampling rule, or threshold will be
tuned from validation data.  Independent validation_1, validation_2, and the
one-shot final confirmation use new seeds and test the no-probe boundary on
full nonlinear Plant A and native ANDES Plant B.  At least six genuine 1 h
normal profiles will also be run.
