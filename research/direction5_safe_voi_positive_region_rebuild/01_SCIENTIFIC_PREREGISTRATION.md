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
non-delivery branch. Performance value is reported as a complete break-even
boundary over an explicit capability prior and as the worst value over a prior
ambiguity set. No selected uniform prior is a primary result. The pure minimum
over capability hypotheses is retained as a distribution-free no-probe
sensitivity. Expected control value never replaces the hard safety test.
CVaR(0.95) and worst episode are secondary reported quantities.

For a binary high/low capability cell, the primary map reports

```text
V(p) = p Delta_H + (1-p) Delta_L
```

and its analytic break-even `p*`. A positive claim requires a nonempty interval
`Pi` for which the worst value over `Pi` is positive. External fleet data may
later locate an operating prior on this map, but development does not choose a
prior to make the result positive.

## Model and scenario changes that are allowed before validation

- information validity horizon: 120, 180, 240, or 300 s;
- 24 or 32 s rolling MPC horizon;
- vector POI observation windows of 4, 8, or 12 s;
- allocation-neutral probe amplitude from 0.0005 to 0.015 pu, subject to a
  robust all-capability physical-safety calculation before value evaluation;
- candidate power/ramp/delay values inside the Plant-A physical realization
  range and the native Plant-B interface range;
- zero-sum allocation probes and control-aligned surplus probes. A
  control-aligned probe is eligible only when the causal contract-MPC command
  is near the public BESS floor, its direction helps the current regulation
  need, the SG contract-safe command is unchanged, and all capability branches
  remain physically safe;
- capability persistence and independent load-event hazard within the locked
  480 s episode;
- three fixed, nonzero frequency/ACE/tie objective preferences.

No validation result may be used to choose among these alternatives.

Sequential evidence may accumulate over non-overlapping eligible windows while
the capability state remains unchanged. Certificate expiry is enforced at the
registered information-validity time. Correlated-window sensitivity must be
reported; independent-window calculations are development screens only.

## Required comparisons

1. contract-only rolling MPC;
2. passive vector-tube estimator plus recourse MPC;
3. selective VOI-ACCR-MPC;
4. evaluation-only registered-formulation perfect-information comparator;
5. scalar-observation predecessor ablation;
6. short-value-horizon predecessor ablation.

The selective method is additionally decomposed into:

1. contract MPC;
2. exploit-only control-aligned surplus without posterior use;
3. dual control-aligned surplus with causal certification and recourse.

This separates immediate control value from pure information value.

The low-capability branch must remain physically safe. Its performance downside
relative to contract MPC is limited before validation to 0.005 Hz incremental
frequency peak and 1% on primary ACE and tie metrics.

## Interpretation rule

A positive development point is a hypothesis, not evidence for the paper.
Only a frozen region that reproduces under independent seeds may support a
positive claim.  An empty or non-reproducible region is retained as a negative
result.
