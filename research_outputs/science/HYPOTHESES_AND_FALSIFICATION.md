# Hypotheses and Falsification Protocol

All thresholds below are locked before Phase C final seeds.

## H1 — Current capability is materially control-relevant

A rolling O2 Oracle that knows current state and current capability, but no future load or capability event, improves at least two core scene-balanced control metrics by at least 10% with paired-bootstrap 95% lower bounds above zero, lowers failure probability by at least 20 percentage points in a reasonable tight-resource class, or moves the equal-resource Pareto frontier outward, without adding physical violations. The criterion must hold in Plant A and Plant B; Plant-A-only evidence is explicitly downgraded.

Falsifier: no qualifying value in both corrected and validated plants. Consequence: `PROBLEM_NOT_MATERIAL`, skip C5/C6 method development, complete the negative package.

## H2 — A finite control-critical window exists

For at least one single-mechanism capability change, continued use of the nominal capability first exceeds a preregistered physical loss threshold or causes a safety violation at finite `Tcrit` compared with correct-current-capability control.

Falsifier: capability changes do not alter optimal actions, feasible capability sets, or physical performance. Consequence: merge the control-equivalent regimes; do not manufacture a classification task.

## H3 — Some changes are passively detectable before harm

For at least two of headroom, ramp and delay changes, externally measured I/O plus the locked load estimator yield `P(Tdet<Tcrit)>=0.8`, false-alarm probability at most 5%, and load-versus-capability macro-F1 at least 0.8.

Falsifier: thresholds are not met. Consequence: test the preregistered safe-excitation feasibility condition; choose C6-B only if safe excitation gives material information gain, otherwise choose C6-C.

## H4 — Structural ambiguity can still support useful robust control

When labels/capabilities are not distinguishable under allowed inputs, a truth-covering capability set and robust allocation can be safer and less conservative than either nominal control or permanently assuming a global worst case.

Falsifier: structural ambiguity remains and capability-set robust MPC has no control value. Consequence: negative result with no fourth-method substitution.

## H5 — Value comes from the selected problem-matched branch

Exactly one C6 branch is chosen by the C5 Gate. Relative to the best deployable baseline it must not reduce scientific success by more than two percentage points, must improve two primary metrics by at least 8% with scene-balanced 95% confidence support, avoid systematic OOD safety degradation, keep infeasibility at most 1%, and keep P99 online time below half the control period.

Falsifier: after at most two development/validation-driven repairs, the method Gate still fails. Consequence: `METHOD_NOT_SUPPORTED_BY_EVIDENCE`; final seeds are not used to tune or select another branch.

## Negative controls

- No capability change: estimates false-alarm probability.
- No natural excitation: establishes the passive structural-identifiability boundary.
- Same externally feasible capability set but different OEM label: tests control-equivalent merging.
- Load-only change with nominal capability: tests load/capability source confusion without true-load access.
