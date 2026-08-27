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
