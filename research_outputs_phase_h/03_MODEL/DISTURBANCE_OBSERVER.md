# Selected disturbance observer

Selected on development only: `reduced_order_kalman_actual_bess_input`. It treats measured actual BESS POI
power as a known swing-balance input. The BESS issued command is absent from its
API. Persistent load is a filtered augmented state and its bounded rate is the
innovation; it is not re-injected as an independent accident each cycle.

The 2 s and 4 s augmented observability ranks and condition numbers are stored
in `OBSERVABILITY_CONDITIONING.csv`. Validation load/capability confusion is
0.070 times the historical Phase-G observer value on matched
Plant-A capability-only rows. Plant-B rows are retained as a native-model
directional crosscheck, not used for development selection.
