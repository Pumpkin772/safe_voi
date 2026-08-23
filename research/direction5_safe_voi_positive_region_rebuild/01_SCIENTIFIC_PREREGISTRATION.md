# Scientific preregistration

## Why the predecessor registered domain was all no-probe

The predecessor result is treated as valid evidence, not as a defect to erase.
Three modelling choices are now explicit scientific hypotheses:

1. the 24 s optimization horizon was also used as the information-value
   horizon, although a capability estimate can remain useful for minutes;
2. the complete actual-POI-power response was compressed into one matched-filter
   scalar, which can merge hypotheses with different ramp and delay signatures;
3. value was dominated by a worst-case short event, whereas operating value is
   accumulated over an independently registered event distribution while safety
   itself must remain robust.

## New hypotheses

- H1: separating a 24 s rolling control horizon from a 180–300 s information
  validity horizon increases registered perfect-information materiality without
  giving the controller future-event truth.
- H2: causal vector observation tubes over actual POI power distinguish
  power/ramp/delay hypotheses with lower probe energy than a scalar statistic.
- H3: a safe allocation-neutral probe can have positive expected closed-loop
  value when capability changes persist and later regulation events are sampled
  independently from a frozen distribution.
- H4: outside that region, exact abstention remains the correct policy.

## Primary estimand

For a state and causal deliverability set, the primary quantity is the paired
absolute difference

```text
registered event-distribution cost(contract MPC)
- registered event-distribution cost(selective VOI-ACCR-MPC).
```

Hard physical safety is evaluated robustly over every retained capability and
non-delivery branch. Expected control value never replaces the hard safety
test. CVaR(0.95) and worst episode are secondary reported quantities.

## Model and scenario changes that are allowed before validation

- information validity horizon: 120, 180, 240, or 300 s;
- 24 or 32 s rolling MPC horizon;
- vector POI observation windows of 4, 8, or 12 s;
- allocation-neutral probe amplitude from 0.0005 to 0.005 pu;
- candidate power/ramp/delay values inside the Plant-A physical realization
  range and the native Plant-B interface range;
- capability persistence and independent load-event hazard within the locked
  480 s episode;
- three fixed, nonzero frequency/ACE/tie objective preferences.

No validation result may be used to choose among these alternatives.

## Required comparisons

1. contract-only rolling MPC;
2. passive vector-tube estimator plus recourse MPC;
3. selective VOI-ACCR-MPC;
4. evaluation-only registered-formulation perfect-information comparator;
5. scalar-observation predecessor ablation;
6. short-value-horizon predecessor ablation.

## Interpretation rule

A positive development point is a hypothesis, not evidence for the paper.
Only a frozen region that reproduces under independent seeds may support a
positive claim.  An empty or non-reproducible region is retained as a negative
result.
