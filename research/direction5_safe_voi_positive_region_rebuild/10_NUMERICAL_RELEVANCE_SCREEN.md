# Numerical relevance screen and fixed-panel rerun

The top-two exact diagnostic falsified the `0.08` local relevance screen: both
states below that threshold had positive acquisition-matched information value
over the registered stochastic continuation.  The value, probe, estimator,
physical model, and event distribution remain unchanged.

The replacement first stage is only a numerical sign screen:

```text
evaluate exact second stage iff local high-posterior value > 1e-6
```

The `1e-6` margin is fixed from numerical accuracy rather than observed
performance.  It equals the fallback conic solver's registered solve tolerance
and is ten times the existing `1e-7` second-stage dominance margin.  Independent
reruns of the two diagnostic states reproduced their local values to the stored
floating-point digits, so this margin is conservative relative to observed
repeatability.  The values `0.064491678` and `0.052842445` are not used to set
the new margin.

The same eight high-capability development seeds are rerun without changing
their order:

```text
8109, 8110, 8111, 8112, 8115, 8117, 8118, 8119
```

The exact acquisition-matched comparison remains the final information gate.
A probe is issued only if all capability branches are non-adverse within the
fixed numerical margin and at least one branch is strictly positive.  The rerun
will report causal states, sign-screen entries, exact-positive states, actual
probe windows, estimator outcome, physical response, and solver behavior.

This rerun corrects a falsified computational shortcut on the already fixed
development panel.  It is not independent validation.  No new seed, larger
event, longer information lifetime, altered objective, or changed probe is
introduced.

## Development outcome and limitation

V3 seed 8110 entered at `520 s`.  Its high-capability paired closed loop showed
`+0.224043875 s` pure information value and `+0.636232895 s` total value.  The
matched low-capability branch had zero pure information value, no false high
certification, and `+0.100830254 s` total value relative to contract MPC.

This establishes a positive development prototype, but it does not prove that
the local sign screen has no false negatives when the current gap is numerical
zero.  Before continuing the remaining old-panel episodes, the final screening
question is therefore moved to the future-lifetime opportunity calculation
registered in `11_OPTIMISTIC_CONTINUATION_SCREEN.md`.  The completed V3 results
are retained and are not reclassified as independent evidence.
