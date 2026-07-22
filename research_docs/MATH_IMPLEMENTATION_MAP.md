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
| (31)–(37) | Grid measurement, exact discrete prediction, load-disturbance Kalman update | `src/d5freq/estimation/grid_kalman_filter.py`: `GridKalmanFilter` | `test_grid_kf.py`, `test_grid_kf_validation.py` | Verified Phase 2 |
| (62)–(64) | Shared SG/IBR command bounds and command-rate constraints | `src/d5freq/optimization/linear_mpc.py`: `LinearMPC.solve`, `MPCBounds` | `test_mpc_constraints.py`, `test_fixed_model_mpc.py` | Verified Phase 2 bootstrap |
| (70) | OOD/solver/slack/timeout fallback disjunction | `src/d5freq/controllers/base.py`: `FallbackTrigger`, `fallback_required` | `test_fallback.py` | Verified Phase 2 |
| (71) | Rate-limited IBR withdrawal toward zero | `src/d5freq/controllers/base.py`: `withdraw_toward_zero` | `test_fallback.py`, `test_lqi_fallback.py` | Verified Phase 2 |
| (72)–(75) | Reduced four-state LQI, disturbance-equilibrium translation, saturation and SG rate limiting | `src/d5freq/controllers/lqi_fallback.py`: `reduced_discrete_grid_matrices`, `design_lqi_gain`, `LQIFallbackController` | `test_lqi_fallback.py`, `test_fallback.py` | Verified Phase 2 |

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
Phase 3 must replace this physical-parameter bootstrap with the discovered
nominal ARX/model-library representation before Phase 6 comparisons.
