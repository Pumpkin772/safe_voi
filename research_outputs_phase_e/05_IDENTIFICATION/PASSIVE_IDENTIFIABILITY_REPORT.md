# E4 passive identifiability report

Three causal baselines were evaluated: multi-step set membership, GLR/CUSUM with global-set reset, and an IMM interval observer. All use only issued commands, POI BESS power, frequency, and past samples. Truth labels are consumed only by evaluation coverage and update-time functions.

G4 result: **FAIL — passive capability set not supported**. Selected passive estimator: **none_qualified**. No estimator was selected merely because all candidates failed. The natural fixed-allocation closed loop provides very small BESS excitation; unhit upper headroom/availability remains structurally confounded, and energy capability remains uninformative at the observed throughput. Alarm time is reported separately from the first control-relevant set change that re-covers the evaluation truth.

Random change-time sensitivity, a retained 1 h no-change trace, 300 s accident traces, 2/4 s sampling, and native Plant B representatives are included. Episodes without a finite matched Tcrit are marked `timing_evaluated=false` and are not counted as method failures.
