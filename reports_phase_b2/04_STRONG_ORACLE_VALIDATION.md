# Strong Oracle Validation

The evaluation-only hierarchy is O0 conventional SG-only ACE PI, O1 truth-regime offline-identified linear MPC, O2 exact-current-regime nonlinear NMPC, and O3 clairvoyant nonlinear NMPC. O2 knows current Plant-B state and parameters but rejects varying future-load forecasts and future-regime schedules. O3 accepts those inputs only as an undeployable ceiling and is excluded from the materiality gate.

O2 is a CasADi/IPOPT multiple-shooting problem with 5 independent 2 s control blocks and 20 independent command variables over the selected 10 s horizon. It is not a constant-action search. Every successful result is explicitly a local solution; there is no global-optimality claim.

Validation selected **10 s** using validation seeds 800–802 and the locked rule: choose the shortest candidate with at least two qualified representative cases and within 5% of the best mean independent-rollout frequency IAE. Same-action symbolic and standalone Python Plant-B rollouts are checked to `1e-5`; independent objective agreement is checked to `1e-4`. The short-horizon O2 result was also compared with 81 dense-grid action sequences. Solver qualification requires scaled KKT at most `0.1` and maximum constraint residual at most `1e-4`.

Validation status is **PARTIAL_QUALIFICATION_WITH_RETAINED_SOLVER_FAILURES**. Non-smooth headroom-critical cases that reached the IPOPT iteration limit are retained in the solver table and are treated as Oracle-quality failures, not silently relabelled as successful upper bounds. Materiality may use only rows whose O2 solve passes the registered quality thresholds; this limitation contributes directly to the final Phase-B2 decision.

O1 models were fit only on development seeds 700–745. Recursive 1/5/10/20-step prediction errors on validation seeds 800–804 are retained in `prediction_error.csv`; structural OOD has no truth-regime identified model. O1 therefore quantifies offline identified-model mismatch rather than claiming exact plant knowledge.

Artifacts include `oracle_horizon_validation.csv`, `oracle_solver_quality.csv`, `oracle_dense_grid_crosscheck.csv`, `oracle_hierarchy.csv`, `prediction_error.csv`, and `artifacts_phase_b2/oracle_validation_lock.json`.
