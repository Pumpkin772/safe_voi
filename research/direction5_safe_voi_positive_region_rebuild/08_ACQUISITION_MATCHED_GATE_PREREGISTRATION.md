# Acquisition-matched causal value gate

This note freezes the second-stage development rule before any nonlinear result
from that rule is generated.  It does not alter the registered load process,
probe amplitude, physical duration, estimator, controller objective, or fixed
development panel.

## Two-stage decision

The existing public-state quantity

\[
\widehat V_H=J^\star(\hat x_k,\Theta_k)
-J^\star(\hat x_k,\Theta_H)
\]

is retained only as a cheap decision-relevance screen.  The value `0.08` is the
pre-existing command-movement scale and is not interpreted as the net value of
information.

When the screen is positive, the controller evaluates the already selected
control-aligned action: `0.006 pu` for `8 s`, at most once per episode.  The
dynamic estimator observes a further `2 s` recovery.  At the registered `4 s`
control period, posterior recourse can therefore first enter after a common
`12 s` predicted prefix: two surplus control intervals followed by one recovery
interval.  The SG command remains the contract-MPC command throughout; only the
BESS request receives the control-aligned surplus.

For every retained power/ramp/delay hypothesis, two predictions start from the
same causal state, actual BESS POI power, measured SoC, applied command history,
and actual-POI MHE load estimate:

1. exploit-only keeps the complete contract candidate set after the common
   acquisition prefix;
2. dual uses the same prefix and then uses the posterior made available by the
   registered estimator.

The current one-window estimator enables the high-power subset only after a
high-power observation.  A low or ambiguous observation retains the complete
contract set.  Ramp and delay remain robust within the retained power branch.
Consequently the predicted pure information value is

\[
\widehat V_{\mathrm{info},\theta}
=\widehat J_{E,\theta}-\widehat J_{D,\theta},
\]

and the acquisition prefix cost cancels exactly between the two arms.

## Prior-free online rule and reported prior boundary

The online controller does not choose a capability prior.  It permits the
acquisition only when the worst prediction inside both the low- and high-power
classes is non-adverse to numerical tolerance and at least one class has
strictly positive predicted information value.  Thus the dual action weakly
dominates exploit-only for every binary prior and is strictly better for every
prior assigning positive mass to a strictly improved class.

The complete low/high branch values and analytic break-even probability remain
reported.  This online weak-dominance rule does not replace the preregistered
paper requirement for a nonempty prior ambiguity interval under independent
closed-loop results.

## Fixed continuation panel

The next `4 s` development trajectories remain the previously fixed sequence:

```text
8109, 8110, 8111, 8112, 8115, 8117, 8118, 8119
```

Seed `8109` was already evaluated with the first-stage screen and abstained.
Seed `8110` has not started a simulation because unrelated system memory use
kept the guarded preflight above its limit.  It remains the next trajectory.
No seed is included or excluded because of capability truth, load realization,
screen result, or realized controller value.

For a trajectory with no admitted acquisition, dual is action-identical to
contract MPC and an exploit-only duplicate is unnecessary.  Every admitted
trajectory receives the paired exploit-only run with the same scenario and
surplus action.  Low-capability paired runs are performed for admitted paths to
measure physical safety and downside.

## Current approximation and interpretation

The online second stage uses the controller's current persistent-load forecast
over the remaining rolling MPC horizon.  The registered 720 s nonlinear paired
episodes remain the measurement of complete closed-loop value under the
independent OU-plus-contingency distribution.  Until the relationship between
predicted and realized pure information value is established on the fixed
development panel, this rule is a development hypothesis rather than a paper
result.
