# Structured Phase-G uncertainty sets

`W_global_prediction` is an empirical finite-horizon prediction envelope. Load
estimation/rate error is stored separately from state prediction error. Delay
truth is assigned independently by seed before simulation so every registered
vertex contributes residual windows; each trajectory is evaluated against its
pre-registered matching vertex. No per-window best-delay selection is used and
model-vertex spread is not double-counted as additive residual.

`W_terminal_local` is calibrated only from causal-observer-warm, event-free,
near-terminal development windows. Observer/local-model residual and bounded
slow load-estimation/rate error are stored separately; the latter enters through
the physical load matrix rather than as an arbitrary nine-dimensional kick.
New load accidents, capability jumps, saturation transients, and fallback
events are not treated as independently repeatable terminal kicks. The local
model-residual set is nested componentwise within the global prediction envelope.

Both sets are empirical coverage objects, not deterministic all-disturbance
guarantees. Power, ramp, energy, availability, and registered delay contracts
remain deterministic physical bounds handled separately by the controller.
