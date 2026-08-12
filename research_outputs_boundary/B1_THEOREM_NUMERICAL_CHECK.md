# Numerical cross-check of the no-probe upper bounds

The analytical statement is in `B0_FORMULATION_AND_THEOREM.md`. This note records the
development cross-checks between the two computable bounds.

At point `B1_LHS_0089`, which had the largest registered perfect-information value in
the initial 512-point map:

- robust contract cost: 9.2561266;
- perfect-information value: 0.0031913;
- predecessor heuristic proxy: +0.1158080;
- quadratic-recourse safe-probe upper bound over all 180 probes: -0.0204617;
- full perfect-post-probe recourse upper bound over all 180 probes: -0.0227612.

The quadratic bound is correctly looser (less negative) than the full recourse bound,
yet both prove the same no-probe conclusion. The full result used 1,449 optimization
calls; the quadratic bound reused the nine baseline/singleton solves and evaluated all
probe prefixes algebraically.

Across the 27 initial-map points with positive or numerically ambiguous
perfect-information values, the full perfect-post-probe calculation evaluated 180
safe probes per point. All 27 maximum upper values were negative; the range was
-0.06277 to -0.02149. The combined count was 22,803 optimization calls with zero
solver failures.

The quadratic bound is used only to classify a point as no-probe when its maximum is
nonpositive. A positive quadratic bound is inconclusive and must be sent to the full
perfect-post-probe recourse calculation. This one-sided use preserves the theorem.

