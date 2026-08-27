# Near-boundary exact second-stage diagnostic

The corrected fixed V2 development panel produced no online acquisition:
none of 67 causally eligible public states crossed the frozen `0.08`
first-stage computational screen.  Therefore the panel contains no observation
of the acquisition-matched second-stage value.

Before running another development seed or changing any model, scenario,
probe, objective, horizon, or threshold, two diagnostic states are fixed from
the completed panel by a deterministic rule: the two largest observed
first-stage values.

```text
seed 8110, time 660 s, first-stage value 0.064491678
seed 8112, time 308 s, first-stage value 0.052842445
```

Both states will be evaluated, irrespective of the result at the first state.
The calculation uses the unchanged 12 s rolling common prefix, fixed eight-path
OU-plus-contingency continuation bank, complete low/high capability branches,
and prior-free weak-Pareto information comparison.  The online `0.08` screen is
not changed.  Diagnostic runs are forced to issue no probe even if the exact
second-stage comparison is positive.

These two post-panel calculations answer only whether the computational screen
discarded a positive second-stage state near its boundary.  They cannot be
counted as independent validation, population performance, or evidence for a
new online threshold.  If either exact value is positive, the next development
question is screen approximation error.  If both are non-positive, the result
supports genuine sparsity under the registered event distribution; it does not
authorize selecting more seeds or enlarging the contingency.
