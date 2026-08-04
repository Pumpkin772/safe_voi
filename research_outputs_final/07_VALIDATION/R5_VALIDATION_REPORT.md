# R5 corrected full validation

Validation lock SHA256: `d1a9fdd49350053e16dfe5890c1c11836dc98c2620f124e0ed63f7a705428fa2`. Plant A used the full
nonlinear RK4 model; Plant B used native ANDES Kundur RMS/DAE. Every core
episode retained nominal warm-up, unannounced capability transition, an
independently assigned load event and 300 s full rolling control. Normal1h used
six explicitly synthetic 3600 s profiles per method because no public measured
window was registered before the lock.

Decisive status: **DIRECTION5_METHOD_NOT_SUPPORTED_AFTER_FINAL_CORRECTED_VALIDATION**.

No failed episode was deleted, no threshold was relaxed and final seeds remain
unused. See the paired absolute differences, hierarchical bootstrap, complete
control-cycle table, solver denominator and failure ledger for the decision.
