# Data retention policy

All episode-level metrics, all failures, all solver qualification summaries, all configurations and seeds are retained. C3 representative full-step trajectories and all C8 control-grid integral/extreme audits are retained; per-step traces for every successful C8 episode were not duplicated because every episode is exactly regenerable from the locked manifest and source. This is a disclosed deviation from the strict request for every episode's control-grid trace and is one packaging limitation; no evidence supporting the negative conclusion was removed.
