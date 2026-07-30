# E2 deployable information audit

Deployable PI/LQI APIs accept `PublicObservationV2` and, for LQI, a causal estimated nine-state vector.  Neither signature accepts capability truth, true load, future events, ANDES internal states, or Oracle data.  `CapabilityTruthV2` appears only in plant/BESS simulation entrypoints.  The public observation contains frequency, ACE, tie-line exchange, measured SG/BESS active power, and previously issued commands.
