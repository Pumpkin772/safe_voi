# Mathematics-to-code implementation map

This is a living traceability record. A row is marked verified only after its
named test passes in the current repository. Later phases extend this table.

| Equations | Topic | Production implementation | Primary tests | Status |
|---|---|---|---|---|
| (1), (6)–(8) | Swing power balance and continuous grid state model | `src/d5freq/models/grid_frequency.py`: `continuous_grid_matrices`, `GridFrequencyModel.derivative` | `test_grid_equilibrium.py`, `test_power_balance_signs.py` | Verified Phase 1 |
| (2)–(3) | Turbine, governor, droop, and SG secondary command | `src/d5freq/models/grid_frequency.py`: `GridFrequencyModel.derivative` | `test_grid_equilibrium.py`, `test_power_balance_signs.py` | Verified Phase 1 |
| (4)–(5) | Integral state and load-disturbance state | `src/d5freq/models/grid_frequency.py`; event application in `src/d5freq/simulation/hybrid_simulator.py` | `test_grid_equilibrium.py`, `test_hybrid_simulator.py` | Verified Phase 1 |
| (9)–(10) | Exact zero-order-hold discretization | `src/d5freq/models/discretization.py`: `exact_zoh`; `GridFrequencyModel.discrete_matrices` | `test_zoh_discretization.py` | Verified Phase 1 |
| (11) | Symmetric command deadband | `src/d5freq/models/hidden_mode_ibr.py`: `deadband` | `test_ibr_deadband.py` | Verified Phase 1 |
| (12) | Delayed command/frequency internal reference | `src/d5freq/models/hidden_mode_ibr.py`: `ibr_reference`, `CommandHistory`, `resolve_delay_s` | `test_ibr_delay.py`, `test_hybrid_simulator.py` | Verified Phase 1 |
| (13) | IBR command-filter state | `src/d5freq/models/hidden_mode_ibr.py`: `ibr_derivative` | `test_ibr_second_order.py` | Verified Phase 1 |
| (14) | Asymmetric internal-target saturation | `src/d5freq/models/hidden_mode_ibr.py`: `asymmetric_saturation` | `test_ibr_saturation.py` | Verified Phase 1 |
| (15) | Output lag and asymmetric ramp limit | `src/d5freq/models/hidden_mode_ibr.py`: `ramp_limited_power_derivative`, `ibr_derivative` | `test_ibr_ramp_limit.py`, `test_ibr_saturation.py` | Verified Phase 1 |
| (16) | Hidden-mode parameter set | `src/d5freq/models/hidden_mode_ibr.py`: `IBRModeParams` | `test_ibr_second_order.py`, `test_model_config_files.py` | Verified Phase 1 |
| (17)–(20) | Second-order ARX convention, seven-parameter ordering, regressor, and one-step prediction | `src/d5freq/identification/arx.py`: `build_arx_regression`, `predict_arx_next`, `predict_arx_one_step_series`; persisted by `ARXModeModel` | `test_arx_recovery.py`, `test_offline_mode_discovery_pipeline.py` | Verified Phase 3 |
| (21)–(26) | Five-state ARX realization, command/frequency channels, and output selectors | `src/d5freq/identification/arx.py`: `arx_state_from_history`, `arx_to_state_space`; `src/d5freq/optimization/joint_prediction.py`: `ARX_POWER_OUTPUT`, `GRID_FREQUENCY_OUTPUT` | `test_arx_state_space.py`, `test_hungarian_evaluation_only.py` | Verified Phase 3 |
| (27)–(30) | Ten-state joint grid/ARX predictor and shared two-input control vector | `src/d5freq/optimization/joint_prediction.py`: `JointARXPredictionModel`, `assemble_joint_arx_prediction` | `test_joint_predictor.py`, `test_hungarian_evaluation_only.py` | Verified Phase 3 |
| (31)–(37) | Grid measurement, exact discrete prediction, load-disturbance Kalman update | `src/d5freq/estimation/grid_kalman_filter.py`: `GridKalmanFilter` | `test_grid_kf.py`, `test_grid_kf_validation.py` | Verified Phase 2 |
| (38)–(39) | Pairwise one-step prediction difference and cumulative distinguishability information | `src/d5freq/evaluation/diagnostic_metrics.py`: public diagnostic helpers; `src/d5freq/identification/offline_pipeline.py`: common-validation-set artifact computation | `test_distinguishability.py`, `test_offline_mode_discovery_pipeline.py` | Verified Phase 3 |
| (40)–(41) | Sticky Markov transition and predicted native-component belief | `src/d5freq/estimation/mode_belief_filter.py`: `build_sticky_transition_matrix`, `predict_mode_belief`, `ModeBeliefFilter.predict` | `test_mode_belief_filter.py` | Verified Phase 4 |
| (42)–(45) | Per-component ARX innovation, Gaussian likelihood, and log-sum-exp Bayes posterior | `src/d5freq/estimation/mode_belief_filter.py`: `build_online_arx_regressor`, `update_mode_belief`, `ModeBeliefFilter.step`; history orchestration in `online_diagnostic.py` | `test_mode_belief_filter.py`, `test_online_diagnostic.py` | Verified Phase 4 |
| (46)–(47) | Raw and normalized mode-belief entropy | `src/d5freq/estimation/mode_belief_filter.py`: `ModeBeliefUpdate`; `src/d5freq/estimation/online_diagnostic.py`: `DiagnosticOutput` | `test_mode_belief_filter.py`, `test_online_diagnostic.py` | Verified Phase 4 |
| (48)–(50) | Minimum standardized residual and finite-sample split-conformal OOD p-value | `src/d5freq/estimation/ood_detector.py`: `minimum_standardized_residual_score`, `calibration_scores_from_residuals`, `split_conformal_pvalue` | `test_ood_detector.py`, `test_phase4_pipeline.py` | Verified Phase 4 |
| (51) | Strict-threshold, four-state OOD confirmation and recovery hysteresis | `src/d5freq/estimation/ood_detector.py`: `OODHysteresisStateMachine`, `ConformalOODDetector` | `test_ood_detector.py`, `test_online_diagnostic.py` | Verified Phase 4 |
| (62)–(64) | Shared SG/IBR command bounds and command-rate constraints | `src/d5freq/optimization/linear_mpc.py`: `LinearMPC.solve`, `MPCBounds` | `test_mpc_constraints.py`, `test_fixed_model_mpc.py` | Verified Phase 2 bootstrap |
| (70) | OOD/solver/slack/timeout fallback disjunction | `src/d5freq/controllers/base.py`: `FallbackTrigger`, `fallback_required` | `test_fallback.py` | Verified Phase 2 |
| (71) | Rate-limited IBR withdrawal toward zero | `src/d5freq/controllers/base.py`: `withdraw_toward_zero` | `test_fallback.py`, `test_lqi_fallback.py` | Verified Phase 2 |
| (72)–(75) | Reduced four-state LQI, disturbance-equilibrium translation, saturation and SG rate limiting | `src/d5freq/controllers/lqi_fallback.py`: `reduced_discrete_grid_matrices`, `design_lqi_gain`, `LQIFallbackController` | `test_lqi_fallback.py`, `test_fallback.py` | Verified Phase 2 |
| (76) | Per-episode regression matrix and target construction | `src/d5freq/identification/arx.py`: `build_arx_regression`; `src/d5freq/identification/mode_discovery.py`: `fit_local_episode_models` | `test_arx_recovery.py`, `test_global_arx_refit.py`, `test_offline_mode_discovery_pipeline.py` | Verified Phase 3 |
| (77)–(78) | Local ridge estimate and residual-variance denominator | `src/d5freq/identification/arx.py`: `fit_arx_ridge`, `fit_arx_ridge_from_regression`, `ARXFitResult` | `test_arx_recovery.py`, `test_offline_mode_discovery_pipeline.py` | Verified Phase 3 |
| (79) | Eight-dimensional local feature and training-only standardization | `src/d5freq/identification/mode_discovery.py`: `build_raw_feature`, `FeatureStandardizer`, `fit_local_episode_models`, `assign_episodes_with_frozen_discovery` | `test_feature_standardization.py`, `test_offline_mode_discovery_pipeline.py` | Verified Phase 3 |
| (80)–(82) | GMM density fitting, likelihood/BIC evaluation, and label-free component-count selection | `src/d5freq/identification/mode_discovery.py`: `select_gmm_by_bic`, `GMMCandidateScore`, `GMMSelectionResult`; persistence in `DiscoveryMetadata` | `test_gmm_bic.py`, `test_gmm_sensitivity_audit.py`, `test_offline_mode_discovery_pipeline.py` | Verified Phase 3 |
| (83) | Cluster-wise pooled global ridge refit | `src/d5freq/identification/mode_discovery.py`: `refit_global_cluster_models`; `src/d5freq/identification/arx.py`: `fit_arx_ridge_from_regression` | `test_global_arx_refit.py`, `test_offline_mode_discovery_pipeline.py` | Verified Phase 3 |
| (84) | Robust externally observed power and directional rate capability bounds | `src/d5freq/identification/mode_discovery.py`: `estimate_mode_capability_bounds`, `ModeCapabilityBounds` | `test_mode_capability_bounds.py`, `test_offline_mode_discovery_pipeline.py` | Verified Phase 3 |

## Coupled numerical realization

`HiddenModeFrequencySimulator` integrates the five grid states and two IBR
truth states as a single seven-dimensional RK4 vector. Every RK4 stage uses its
stage frequency in the IBR derivative and its stage IBR power in the swing
equation. Mode, load, and fixed-delay command discontinuities split integration
intervals exactly; the old value is frozen on the left segment closure, and the
new value is applied only to the next segment. Mode switches change parameters
without resetting any physical state or command history.

## Phase 2 estimator qualification

For the configured sampled grid model, the augmented observability matrix for
equations (31)–(37) has rank four, not five. Its sole unobservable direction is
the constant offset of `xi_pu_s`: the integral state does not feed back into the
measured physical dynamics. The dynamic physical subspace including the load
disturbance is observable. Consequently, `xi_pu_s` is initialized by definition
at the episode boundary and then continuously dead-reckoned; a mid-episode
fallback must reuse the continuously propagated estimate through
`LQIFallbackController.action_from_estimate` rather than resetting the filter.
This behavior is pinned by `test_grid_kf_validation.py` and
`test_lqi_fallback.py`.

The calibrated Phase 2 controller construction explicitly reads the covariance
diagonals and `load_random_walk_std_pu_per_s: 1.0e-4` from
`configs/base.yaml`. The class default is only a smoke-run convenience and is
not an experiment configuration.

## Phase 2 MPC scope

`linearize_grid_ibr` is a pre-identification bootstrap predictor used to test
the optimizer, constraints, estimator coupling, and Oracle isolation before a
data-derived library exists. It deliberately omits delay, deadband, saturation,
and ramp nonlinearities, while enforcing declared external IBR power and
power-rate limits in the QP. It is not the final Fixed-ARX scientific baseline.
Phase 3 now supplies the data-derived ARX model library. Phase 5 must wire that
library into the robust controller, and Phase 6 comparisons must not revert to
the physical-parameter bootstrap predictor.

## Phase 3 identification boundaries and qualifications

The identification API is deliberately truth-free. `UnlabeledTrajectory`
exposes only an opaque trajectory identifier and the observable
`p_ibr_pu`, `u_ibr_pu`, and `omega_pu` arrays. The training entry point
`discover_unlabeled_modes` has no truth-label argument, and the strict
`ModeLibrary` schema persists native GMM component identifiers without a
component-to-truth mapping. The same frozen training scaler and GMM are reused
by `assign_episodes_with_frozen_discovery` for held-out episodes.

The main equation-(79)--(82) chain always operates on all eight standardized
features: seven local ARX parameters plus log residual variance. PCA is not an
identification or model-selection transform; it is permitted only for a
two-dimensional diagnostic plot such as `parameter_embedding.png`.

Hungarian alignment and private-label ARI/NMI/macro-F1 reporting live only in
`src/d5freq/evaluation/diagnostic_metrics.py`. They are intentionally absent
from, and not re-exported by, `d5freq.identification`. Discovered component IDs
therefore remain unchanged during global refitting and model-library
persistence. `test_hungarian_evaluation_only.py` pins both the package boundary
and strict-schema rejection of truth-name mappings.

Equation (78) is interpreted literally for a raw trajectory: with seven ARX
parameters, `fit_arx_ridge` divides the residual sum of squares by
`N_e - 7`, where `N_e` is the raw aligned trajectory sample count. It does not
silently substitute `(N_e - 2) - 7`, even though the regression matrix has
`N_e - 2` rows. The lower-level arbitrary-matrix fitter defaults to its
conventional row-count denominator and accepts an explicit denominator so the
trajectory wrapper can preserve the stated equation.

Equation (84) is realized with separate directional magnitudes. Upward
capability is the configured quantile of positive `Delta p_b / T_s`; downward
capability is the same quantile of the magnitude of negative rates. A missing
direction has zero observed capability, and differences are never formed
across trajectory boundaries. This retains asymmetric physical capability
instead of collapsing both directions into one absolute-rate limit.

The complete data-generation-to-artifact discovery pipeline is verified by
`test_offline_mode_discovery_pipeline.py` and the strict Phase 3 regression
run. The canonical BIC result is deliberately retained as six components even
though evaluation-only metadata contains four reference modes: the selected
model reached the configured `K_max=6`, and no private label was used to force
or rename it. The `d5freq.mode_library.v2` schema records separate validation
q95 sequences for IBR power error in pu, propagated frequency error in Hz, and
propagated RoCoF error in Hz/s. Its sticky transition matrix uses the specified
off-diagonal switch probability, so for six components and
`epsilon_sw=0.002` the diagonal is `0.99` and every off-diagonal entry is
`0.002`.

## Phase 4 online-diagnosis boundaries

`OnlineModeDiagnostic` owns exactly two prior controller-visible measurements
and uses the command reported as already applied at the current sample as
`u[k-1]`.  Its first two records are explicitly marked as ARX warm-up; neither
the Bayes filter nor the conformal state machine consumes fabricated residuals
during those records.  Runtime logs retain native six-component probabilities,
residuals, NIS, the log normalization constant, entropy, conformal score and
four-state OOD status.  They contain no simulator metadata.

The OOD reference distribution is built only from complete trajectories in the
authenticated public `ood_calibration` split.  Its strict artifact binds the
scores to the public dataset, split manifest, frozen model library and each
source trajectory hash.  Test and generated OOD trajectory hashes are checked
for disjointness before evaluation.  Any aggregation from six discovered
components to the four simulator reference classes is a many-to-one,
evaluation-only operation performed after the runtime log has been saved and
hashed; it never changes the native component posterior or OOD score.
