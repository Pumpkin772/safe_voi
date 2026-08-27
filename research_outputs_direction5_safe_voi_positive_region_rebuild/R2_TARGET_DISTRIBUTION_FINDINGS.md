# Target-distribution development findings

These are development results.  They locate positive and no-probe regions but
do not support an independent paper claim.

## Removal of late-event censoring

The first target-distribution screen used the originally registered 480 s
episode.  Because the load-event window extends to 390 s and information can
remain valid for 300 s, that duration censors most of the value following a
late event.  Before any validation seed was used, the ordinary episode was
extended to 720 s: latest event 390 s + maximum validity 300 s + 30 s recovery.
Load magnitudes, signs, areas, and event-time distributions were unchanged.

The 480 s seed-8200 results are retained as a truncation sensitivity.  The high
branch could be certified with a 12 s, 0.003--0.005 pu action, but the total
paired values relative to contract MPC were all adverse:

| grid-service value (s) | SG-mileage value (pu) | BESS-throughput value (pu s) |
|---:|---:|---:|
| -0.4322 | -0.0405 | -0.2099 |

This is a Pareto-dominated no-probe point for every nonnegative resource price.

## First complete 720 s point

Seed 8238 used a 4 s control period, a 253.996 s negative both-area event of
0.06471 pu, and 240 s information validity.  The high-capability branch was
certified at 312 s by the 12 s, 0.003--0.005 pu action.  Relative to contract
MPC, total value was again Pareto dominated:

| grid-service value (s) | SG-mileage value (pu) | BESS-throughput value (pu s) |
|---:|---:|---:|
| -0.1576 | -0.0449 | -0.1434 |

Relative to the identical exploit-only action, information use itself had
`+0.00198 s` grid-service value and `+0.00699 pu` SG-mileage value, but required
`0.4091 pu s` additional BESS throughput.  Thus information had a nonzero
resource-substitution effect, while acquisition cost kept the complete action
outside the positive region.  A shorter 8 s action with second amplitude
0.006 pu certified eight seconds earlier and used less request integral, but
the complete strategy remained dominated.

## Observation-rate misspecification

Seed 8256 showed that a true 0.068 pu high-capability branch could be stopped
after a single 0.044812 pu noisy/delayed sample.  Futility now requires at least
two causal samples.  More importantly, the implementation called a temporal
observation model while taking only one to three samples at the 2/4 s MPC
period.  That is not the registered vector actual-POI observation.

The corrected implementation receives a 5 Hz AR(1) actual-POI stream, while
MPC optimization remains at 2/4 s. The primary estimator now compares the full
command-to-actual response of every power/ramp/delay candidate. The first
1.5 s is excluded uniformly, the post-action response is observed for 2 s, and
each completed window produces one AR(1)-whitened likelihood set. The earlier
settled-mean effective-sample statistic remains an ablation. The first corrected dual run was stopped by unrelated
system memory growth before producing a result; its resource record is retained
and it is not counted as a scientific failure.

## Candidate-model statistical calibration

Before a new nonlinear episode, the 8 s, 0.050 pu response design was evaluated
under all eight combinations of power `{0.045, 0.068}`, ramp `{0.025, 0.039}`
and delay `{0.2, 1.5}`. The simulation used 5 Hz AR(1) noise with marginal
standard deviation 0.0015 pu, correlation 0.2, and an additional independent
bounded discrepancy in `[-0.0005, 0.0005]` pu. Each of the four contract-power
truths used 50,000 repetitions. No false high-power decision occurred; the
one-sided 95% binomial upper bound was `5.99e-5`. All four high-power truths
were selected in all 50,000 repetitions. This establishes only candidate-model
separation. The next nonlinear episodes test whether the same residual bound
covers full Plant-A response mismatch.

## Full nonlinear dynamic-evidence pair

Seed 8256 was then rerun with the same eight ordinary-controller candidates,
the full nonlinear Plant A, and matched contract/exploit-only/dual controllers.
For the 0.068 pu truth, the first completed window retained both contract and
high-power candidates. The second window ended at 338.2 s and retained only the
four 0.068 pu candidates. The true 0.068/0.039/1.5 candidate remained present,
the candidate set never became empty, and no optimization failed. For the
matched 0.045 pu truth, the second window retained only the four contract-power
candidates, produced no high-power decision, and stopped further excitation.
All six paired runs were physically safe.

The high-branch values are reported with positive sign meaning that the method
reduced the named cost:

| decomposition | grid-service value (s) | SG-mileage value (pu) | BESS-throughput value (pu s) |
|---|---:|---:|---:|
| contract minus dual | -0.177797 | -0.059861 | +0.112902 |
| exploit-only minus dual (pure information) | -0.003763 | -0.000684 | -0.085603 |
| contract minus exploit-only (action effect) | -0.174035 | -0.059177 | +0.198506 |

In the low branch, dual and exploit-only were numerically identical because no
capability recourse was enabled. Relative to contract their values were
`(-0.020982, -0.023351, +0.091391)`. Frequency peak was unchanged in every arm.
Thus the dynamic estimator fixes the earlier evidence error, but this episode
does not have positive pure information value.

The physical reason is timing rather than non-identifiability: the sole load
event occurred at 286.7 s, created the first binding command, and high power was
identified only at 338.2 s. No later regulation demand existed inside the
episode, so the new information could not improve a future action. Before any
validation seed is used, the next scenario question is whether a registered
continuous-regulation or repeated-independent-event process creates a genuine
future use for information without revealing a future event to the controller.

## Current interpretation

The registered distribution contains genuine no-probe states; automatic
excitation at every binding command is therefore incorrect.  The next
calculation tests whether the corrected temporal observation can reduce
acquisition cost enough to create an interior positive prior--resource-price
region.  If it does, the final controller must use a frozen causal value gate
and abstain on the Pareto-dominated states above.
