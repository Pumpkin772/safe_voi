# Corrected Phase-F claim boundary

## Frozen Phase-E split recovery

The Phase-E manifest mislabeled every seed as development.  F1 recovers the
split actually used by E6: seeds 0--9 select the deployable baseline and seeds
10--19 are held-out legacy validation.  This audit does not run or alter a
controller.  The Phase-F experiments themselves use the separately registered
0--19 / 20--39 / 100--159 split.

The development-only success-first selection chooses `fixed_allocation_pi`.
Validation is never used for selection, weights, thresholds, or Tcrit.

## Corrected hypotheses

- H1: **SUPPORTED**.  Success-rate degradation is a veto, so both-success
  continuous improvements cannot hide additional Oracle failures.
- H2: **TESTED_PASSIVE_ESTIMATORS_NOT_SUPPORTED_UNDER_REGISTERED_EXCITATION**.  This is not a category-level impossibility result.
- H3: **TESTED_ACTIVE_PROBE_NOT_SAFE**.  This applies only to the registered tested probe.
- H4/H5: not evaluated until CDSR-MPC and certificates exist.

All continuous improvements are aggregate-mean ratios with paired
seed-cluster bootstrap intervals.  The paired failure table distinguishes both
success, each one-sided failure, both fail, and not evaluated.  Penalty
sensitivity at 2x/5x/10x the worst successful objective is included but is not
used to erase the success-first table.
