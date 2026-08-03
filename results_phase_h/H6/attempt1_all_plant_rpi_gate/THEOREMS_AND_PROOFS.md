# Phase-H theorem and claim boundary

## Sustainable RPI construction

For the registered SG-only terminal feedback, the augmented closed-loop matrix
is Schur. The minimal disturbance-reachable zonotope is recomputed as
`sum Acl^i diag(w)` until the next generator is below `1e-12`. All
Plant/period rows stable, invariant, admissible in the restricted equilibrium
margin, and contained in the H4 terminal radius: **False**.

The current JSON deliberately remains Level A until an independent replay
confirms that DCSV-MPC enforces this exact zonotope, zero terminal BESS command,
and the applied-action delay pipeline. A box outer approximation is not used as
a substitute. Conditional recursive feasibility may be promoted only by that
code-object replay.

## Bridge and infeasibility

Each of the 58 bridge rows recomputes power, ramp-after-delay,
loss-adjusted energy, conservative frequency/ACE/tie bounds, and entry into the
registered slow-reserve sustainable domain. No bridge row claims recursion.
Each of the 26 infeasible rows records steady, pre-reserve,
ramp-delay, and energy deficits together with H2 binding constraints and is
excluded from ordinary controller-failure counts.
