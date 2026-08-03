# H7 development/validation report

Development-only best deployable baseline: `nominal_offset_free_mpc`. Validation DCSV
success is 100.000% versus baseline
100.000%; failure-aware mean cost is
72.3419 versus
59.226. Metrics passing the registered
8%/positive paired-CI rule: 0/3.

The 300--600 s rows simulate every event-active controller update for the
registered active window, then propagate the no-new-event physical tail with
the last applied action; active and tail durations are stored separately.
Plant-B evaluation uses the reduced public control layer plus the residual set
calibrated on native ANDES in H4, not a new full native final claim. Normal 1 h
zero-net-load rows are retained separately. Physical-infeasible rows are
preclassified and excluded from ordinary controller success/failure rates.
