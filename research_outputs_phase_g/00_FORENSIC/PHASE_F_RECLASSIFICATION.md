# Phase F G5 reclassification

Phase F is frozen at `d424557f6cd8faf4b703c050b4031c7489281625` and its reviewed ZIP hash is
`675f8982f20b0ffe73a03488e0859da1e45d309e2fe54e7e49a8a7354e1a7544`. The ZIP present during this audit matched: `True`.

All five recomputed one-step frequency/ACE/tie radii exceed their corresponding
zero-state terminal limits. A feedback law cannot make the old terminal box
positively invariant against a disturbance that can leave the box in one step
from its center.

The registered maximum sustained event is 0.080 pu while
the two-area minimum SG reserve is 0.050 pu, leaving a
0.030 pu static shortfall for an SG-only
infinite-horizon backup.

The certificate aggregation has been corrected from the universal `all()` to
the existential `any()` condition. Both evaluate to false for the four frozen
Phase-F attempts, so the historical numerical outcome is unchanged.

The binding interpretation is therefore:

```text
CERTIFICATE_FORMULATION_INCOMPATIBLE
```

This is incompatibility between the global event-contaminated disturbance set,
the old terminal limits, and the SG-only backup contract. It is not evidence
that CDSR-MPC or all backup architectures fail. The Phase-F hard-constraint
audit also confirms that actual delayed BESS power/ramp/energy and consistent
SG/terminal margins require repair in Phase G.
