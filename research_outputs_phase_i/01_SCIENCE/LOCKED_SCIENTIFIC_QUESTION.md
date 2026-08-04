# Direction5 locked scientific question

Execution-date lock: **2026-08-04**. This is the only Phase-I question and it
cannot be broadened after validation or final evidence is seen.

> Can public measurements distinguish net-load change from a reduction in an
> IBR's presently deliverable command-to-actual capability, and can that
> separation improve multi-area frequency and ACE regulation under a contractual
> capability floor, a causal online performance envelope, and measured-SoC energy
> constraints, while explicitly delimiting what cannot be guaranteed after an
> unannounced fall below the contract?

The hidden safety-relevant vector is exactly
`{P+, P-, R+, R-, delay}`. Energy is computed from measured SoC, rated energy,
and registered efficiencies. Availability is not estimated as a latent label; its
effect must appear in the observed deliverability envelope. The load observer uses
**actual BESS POI power**, never an issued-command surrogate.

Hard safety uses only the registered contract floor. A statistically supported
online envelope may allocate performance responsibility, but cannot strengthen a
hard safety claim. A true capability below the contract is a contract violation
and invokes registered SG/slow-reserve emergency behavior.

The evaluated method is only DCSV-MPC. It must be a receding-horizon optimization
with predicted states and inputs, delay pipeline, measured-SoC energy, slow
reserve, physical-domain conditions, restoration, and solver diagnostics. No
AI/RL, hidden truth, future event, or future mode is available to an ordinary
controller.
