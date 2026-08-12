# B1 interim findings

These findings are development evidence only. They do not use validation or final
seeds and do not support a paper claim yet.

## Exact versus predecessor heuristic

Two deliberately difficult pilot points exposed a qualitative mismatch. The old
heuristic proxy was positive (+0.0612 and +0.1580), while the registered-formulation
perfect-information values were numerical zero (-5.8e-10 and -9.1e-9). The best exact
probe values among the evaluated shortlists were -0.02194 and -0.02797. Thus a positive
heuristic label did not establish that information could improve the registered
control problem.

A 24-point Latin-hypercube screen then found one materially nonzero
perfect-information candidate: a 2 s, medium-SG, high-load resource-economy point had

- robust contract cost: 9.025404;
- registered perfect-information value: 0.00104456 (0.0116% of robust cost);
- predecessor heuristic value: +0.06627.

The eight most separable safe probes at this point reduced the mean posterior size by
about 40%--43%, but every exact net value was negative. The best was -0.03223 and its
perfect-post-probe upper value was -0.03217.

All 180 registered safe probes were then evaluated under the deliberately optimistic
assumption that the true capability becomes known immediately after the probe. The
maximum upper value was -0.02282. This required 1,449 optimization calls, with zero
solver failures. The point is therefore a theorem-supported zero-value point: no
causal posterior strategy in the registered class can beat contract MPC there.

## Physical interpretation

The probes can identify capability differences, but identifiability is not the
bottleneck at the confirmed point. Even perfect post-probe information cannot repay
the allocation excursion. The earlier heuristic mainly tracked candidate action
dispersion and load/tie magnitude, so it overvalued information without charging the
same closed-loop recourse problem.

The full 512-point design screen and all-positive-VPI upper confirmation are still in
progress. A nonempty positive region has neither been established nor ruled out over
the complete registered map.

