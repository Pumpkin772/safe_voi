# A2 passive capability identification

Status: **PASS** with zero repair rounds. Selected estimator:
`FINITE_AB_DELAY_GRID_PLUS_INTERVAL_MHE`.

The identifier is causal and receives only time, requested total BESS power,
and actual BESS POI power. A finite `(a,b,delay)` grid maintains non-falsified
models and supplies abrupt-change reset; an independent window MHE supplies
outer power, ramp, and delay intervals. True capability and true load are
evaluation-side only.

Validation used fresh seeds 250--299. Among 40 independently drawn excited
physical BESS episodes, empirical power, ramp, delay, and joint containment
were each 40/40 (100%). The one-sided exact 95% finite-sample lower bound is
92.784%; this lower bound is reported and is not misrepresented as exceeding
95%. False optimism was 0/40. The registered A2 Gate applies to empirical
coverage and therefore passes.

Ten separate no-excitation episodes retained the full delay width and a wide
power interval, never promoted excitation, and never certified passive surplus.
An incompatible command-to-actual transition triggered the finite-grid reset
and discarded the interval MHE's stale evidence. Energy is not hidden; it will
be calculated from measured SoC. Availability is represented through observed
deliverability, not a latent truth input.

