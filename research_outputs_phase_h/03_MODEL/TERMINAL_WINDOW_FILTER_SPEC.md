# Strict Direction5 terminal-window filter

A window is included only when all twelve registered predicates are true:
sustainable H2 domain, full-horizon event separation, proximity to the
load-parameterized equilibrium, inactive SG valve/mechanical boundaries,
inactive GRC, inactive BESS power/ramp/energy limits, unsaturated command,
warmed selected observer, and no solver/fallback anomaly. Every excluded row
stores one ordered primary reason and the complete reason list.

The global prediction set includes observer error, bounded persistent-load
rate, model mismatch, nominal delay interpolation, and measurement effects.
Capability changes remain in the independent command-to-actual set C_k. The
local set uses only physically clean sustainable windows and is indexed by
Plant, control period, and horizon. Persistent load error follows
`dtilde[k+1]=dtilde[k]+nu[k]`; it is never replayed as a new step each cycle.

Coverage is reported on validation with exact one-sided 95% Clopper--Pearson
lower bounds. Final seeds and future values are absent from calibration.
