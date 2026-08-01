# Phase E frozen review correction

Phase E is frozen at `8fd7d4515377996cd9e17809ecd045a835d2916d` and tag
`direction1-phase-e-reviewed`.  The review ZIP SHA256 is `d30be15f1d1a4c0a80339ff3408a50397adc1e98e85a4e673a5b2b7c66b61d9c`.

The old optimizer commits a proposed action before terminal supervision.  All
3 forced rejection/fallback cases reproduced a difference between
the physically applied action and `optimizer.previous_action`; the maximum
observed infinity-norm mismatch was 0.0345413 pu.

The frozen E6 trace can distinguish accepted candidates, terminal rejection
(optimal solver status plus fallback), and a residual solver-failure bucket.
It cannot distinguish primal infeasibility, numerical failure, maximum
iterations, secondary-solver failure, or residual rejection because those
fields were never saved.  It also did not save the optimizer's stored previous
action.  Therefore the reported 1.846% must not be described as mathematical
infeasibility or as evidence against a method class.

The extracted review-package minimal replay returned code 1.
Its script resolves `parents[2]` outside the extracted root, confirming the
package-relative-path defect.  Phase F will use review-root-aware paths.

G0: **PASS**.
