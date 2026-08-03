# Independent command-to-actual capability estimator

The estimator consumes issued BESS SFR command, measured actual POI power,
local frequency/PFR demand, SoC, and causal history. It maintains intervals for
positive/negative power, ramp, delay, accessible energy, and availability.
Delay is updated by a causal command-to-actual model set rather than pairing a
new command with the first subsequent response. Candidate delays are retained
under gain, actuator-lag, noise, jitter, and sample-time uncertainty; when the
public I/O is not identifying, the registered physical delay interval remains
wide. Unannounced mismatch expands stale witnessed lower bounds before new
evidence is accumulated. No-excitation rows deliberately keep wide sets. Truth
enters only the evaluation-side coverage table and is absent from the estimator
API.
