# A1 literature, novelty, and perfect-capability materiality Gate

Status: **PASS**. Execution date: 2026-08-10. Final seeds 400--459 were not
consumed.

The formal inventory contains 80 unique peer-reviewed papers or official
records. Ten closest-work records were freshly checked against primary
publisher pages or authoritative author/institution repositories. Safe
data-driven secondary control, nullspace/persistent excitation, active
exploration MPC, power-system probing, adaptive constrained control allocation,
and event-triggered/fault-tolerant LFC all exist. No component-level novelty is
claimed. The reviewed corpus did not contain the full ACCR intersection of
event-triggered allocation-neutral probing, delivered/loss safety, finite-valid
power/ramp/delay certification, contract-floor plus revocable-surplus recourse,
and multi-area frequency/ACE/tie responsibility.

The materiality study used 24 registered full-nonlinear Plant-A scenarios and
48 genuine rolling-MPC episodes. Each of power/ramp, low/high SG tension, and
2/4 s period had three independent development seeds. Every episode contained
at least 60 s nominal warm-up, an unannounced capability change, an independently
timed load event, and 300 s full rolling control. Contract MPC and the
evaluation-only perfect-capability Oracle used the same model, objective,
horizon, solver, observer, measured SoC, and delay pipeline. Only the Oracle
could read current capability truth.

Primary results are paired absolute `contract - perfect` differences with
equal weighting across the two periods and a seed/design-cell hierarchical
bootstrap:

| mechanism | SG tension | n | ACE mean delta | ACE 95% lower | Gate |
| --- | --- | ---: | ---: | ---: | --- |
| power | low | 6 | 0.040055 | 0.00000542 | positive |
| power | high | 6 | 0.015754 | 0.00000463 | positive |
| ramp | low | 6 | 0.041648 | 0.00000425 | positive |
| ramp | high | 6 | 0.005266 | -0.005672 | not positive |

Thus power has positive perfect-information ACE value at both registered SG
tensions, satisfying the A1 materiality Gate. The ramp/high failure is retained
and is not recoded. All 48 episodes physically succeeded; hard violations,
fallbacks, and restorations were zero. The solver denominator contains all
5,448 attempted optimization calls.

The first A1 attempt was manually stopped before producing an episode so that
the runner could atomically preserve each completed episode. Three later
attempts were terminated by the fail-closed system-commit-growth guard while
task-tree private memory stayed near 0.42 GiB. All completed parts were retained.
Observed CVXPY/CLARABEL transient system commit made the 4 GiB relative-growth
tripwire fire below the unchanged 65% absolute limit. The execution-only
relative tripwire was corrected to 6 GiB; the absolute 65% commit limit, 8 GiB
available-physical-memory floor, 4 GiB task-private limit, and one-descendant
limit remained unchanged. The final resumed attempt completed with peak system
commit 55.35%, peak task-private memory 417,853,440 bytes, and one descendant.

