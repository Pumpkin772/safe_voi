# ACCR P1--P7 theorems and bounded proofs

## P1 — command allocation neutrality

For each area, the probe adds `[-q, +q]` to `[SG, BESS]`; therefore `[1,1][-q,+q]^T=0`. This is command-level neutrality only and does not assert zero instantaneous actual-power effect.

## P2 — conditional set containment

Let the true hypothesis be in the prior candidate set and let its prediction residual be bounded by epsilon. The membership update deletes only hypotheses whose residual exceeds epsilon. Hence the true hypothesis remains. If the set becomes empty or a change-reset occurs, the implementation revokes the old certificate instead of asserting containment.

## P3 — registered finite-horizon probe safety

The selected probe was replayed on the full nonlinear Plant A for every registered power/ramp/delay candidate and the no-surplus interpretation. Frequency, ACE, tie and device inequalities were evaluated directly. This certifies only that registered finite experiment, not arbitrary models or infinite time.

## P4 — sufficient distinguishability

For hypotheses h and j with bounded output errors of radius epsilon, `||y_h-y_j||_infinity > 2 epsilon` makes their error tubes disjoint. At most one can remain consistent with a measurement, so the other is excluded. Pairs that do not satisfy this separation are deliberately not claimed distinguishable.

## P5 — finite capability lower bound

When P2 holds over a stationary interval, the minimum power and ramp and maximum delay over the retained set are conservative bounds for the true hypothesis. They are valid only until the registered expiry or earlier reset; energy remains a measured-SoC constraint, not a hidden certificate dimension.

## P6 — unannounced loss boundary

Two worlds can share the complete public history through a decision instant yet differ by an unannounced capability collapse. Causality forces the same command in both; a command feasible in the retained world can be infeasible in the collapsed world. Same-instant unconditional protection is impossible beyond the contract and the method therefore uses next-cycle loss recourse.

## P7 — contract terminal and surplus-loss recourse

The contract branch directly replays guaranteed power/ramp, dense registered delays, predicted physical power/ramp/energy and frequency/ACE/tie inequalities. The local RPI boxes verify `|Acl|z+w<=z` with positive state/input margins around load-dependent equilibria. Both branches share the current action; from the next step, registered SG and slow-reserve headroom dominates the removed certified surplus. These are conditional finite-horizon and local certificates, not global recursive safety.

## Allowed claim

`registered-set finite-horizon safe active capability certification with a separately certified contract fallback and next-cycle surplus-loss recourse`.
