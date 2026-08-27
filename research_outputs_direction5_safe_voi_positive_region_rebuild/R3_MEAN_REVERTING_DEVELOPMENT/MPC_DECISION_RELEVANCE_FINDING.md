# MPC decision-relevance map

The map contains 240 genuine finite-horizon robust MPC comparisons over
control period, horizon, load, and the registered SG/BESS allocation-weight
axis.  Each point compares the first BESS action under the complete candidate
set with the action after all contract-power candidates have been removed.

| allocation condition | first load with action difference > 0.0001 pu | maximum difference (pu) |
| --- | ---: | ---: |
| grid service, neutral allocation | none through 0.070 pu | 0.000000 |
| SG-conserving 4 | 0.060 pu | 0.002339 |
| SG-conserving 16 | 0.050 pu | 0.008801 |
| SG-conserving 64 | 0.050 pu | 0.018050 |

For SG-conserving 16, the 2 s controller becomes decision-relevant at about
0.055 pu and the 4 s controller at about 0.050 pu.  Changing the horizon from
24 to 32 s has negligible influence on these thresholds.  The next nonlinear
mechanism comparison therefore uses SG-conserving 16 and leaves the episode,
event distribution, probe, estimator, and validity time unchanged.

Many CLARABEL solutions were labelled `optimal_inaccurate`; all 240 contract
and posterior solves returned a finite solution, and the retained CSV reports
both statuses.  The nonlinear comparison, rather than this local map, decides
whether the action difference yields physical control value.
