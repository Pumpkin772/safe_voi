# Estimator coverage protocol

Sixty held-out validation episodes (seeds 30--89) independently draw continuous
power, ramp and delay truth. Coverage is checked only evaluation-side. Reports
include sample count, empirical coverage, one-sided exact 95% binomial lower
bound, plant, identification period and horizon. Ten separate no-excitation
episodes verify that the set does not falsely shrink. False optimism means any
claimed hard lower capability exceeds truth. Contract-violation cases are
reported as the causal impossibility boundary, not folded into within-contract
coverage.
