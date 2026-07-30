# Required output tables

1. `per_episode_metrics.csv`
   - scenario_id, seed, plant_id, sg_level, method
   - run_completed, scientific_success, failure_type
   - freq_iae, ace_iae, max_abs_freq_hz, max_abs_rocof
   - tie_line_iae, settling_time
   - sg_energy, ibr_energy, sg_mileage, ibr_mileage
   - total_cost for each cost ratio
   - solver metrics

2. `paired_failure_outcomes.csv`
   - method, reference, scenario, seed, sg_level
   - both_success, method_only_failure, reference_only_failure, both_failure

3. `corrected_materiality.csv`
   - scenario-balanced absolute and relative effects
   - bootstrap CI
   - cost-ratio sensitivity
   - gate status and reason

4. `oracle_hierarchy.csv`
   - O0/O1/O2/O3 metrics, pair counts, solve quality

5. `oracle_solver_quality.csv`
   - status, iterations, KKT, max constraint residual, wall time, warm start

6. `prediction_error.csv`
   - plant/regime/method/horizon/metric RMSE, q95, max

7. `control_relevant_regime_distance.csv`
   - regime pair, d_pred, d_act, d_cap, d_ctrl, merge decision

8. `critical_window.csv`
   - event, scenario, seed, Tcritical, threshold cause

9. `identifiability.csv`
   - detection delay, censored, Tcritical, before-critical flag, source confusion

10. `final_decision.json`
    - materiality, triggers, thresholds, active triggers, final decision
    - no fallback ranking when active list is empty
