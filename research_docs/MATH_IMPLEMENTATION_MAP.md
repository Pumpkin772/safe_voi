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

## Coupled numerical realization

`HiddenModeFrequencySimulator` integrates the five grid states and two IBR
truth states as a single seven-dimensional RK4 vector. Every RK4 stage uses its
stage frequency in the IBR derivative and its stage IBR power in the swing
equation. Mode, load, and fixed-delay command discontinuities split integration
intervals exactly; the old value is frozen on the left segment closure, and the
new value is applied only to the next segment. Mode switches change parameters
without resetting any physical state or command history.

