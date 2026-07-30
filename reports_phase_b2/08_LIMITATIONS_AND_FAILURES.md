# Limitations and Failures

- O2 is a local IPOPT solution, never a globally optimal Oracle. Headroom-critical validation retained iteration-limit and rollout-quality failures; validation status is partial.
- The final O2 experiment uses one five-action plan over the registered ten-second event window, initialized at t=2 s. It is not a claim of long-horizon closed-loop optimality.
- 19 of 60 eligible O2 rows failed solver quality. All remain in success-first tables.
- Current Plant-A RLS-MPC and old SD-BMPC were not retuned or falsely ported to Plant B. Their 430 rows each are explicit scientific failures/historical non-applicability records.
- O1 has no model for structural OOD or mixed untrained pairs; 200 such rows are retained.
- Identifiability uses a favorable same-load, same-initial-state counterfactual; ordinary detectors are unlikely to outperform this bound.
- Average-value Plant B is not an EMT or vendor model. Pure delay/dropout is discretized, and O2 predicts expected packet delivery.
- The final run contains 2,150 rows, 1,449 scientific failures, zero missing/deleted rows, and no tuning from final results.
