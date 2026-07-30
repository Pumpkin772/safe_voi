# E5 safe active-identification feasibility

The optimized candidate uses a 0.04 pu, zero-mean alternating BESS redistribution with same-area SG compensation. Candidate execution is suppressed whenever public frequency/ACE margin or an explicit SG backup check fails. The information monitor uses high-rate issued command, POI power, and frequency only; capability labels enter only paired evaluation.

G5 result: **FAIL — ACTIVE_IDENTIFICATION_NOT_SAFE**. Timing passes 0/5 mechanisms after excluding only explicitly `timing_evaluated=false` rows from the denominator; information contraction passes 3/5. Frequency IAE change is 261.00%; ACE IAE change is 279.90%. Failed and not-evaluated episodes remain distinct in the raw table. The power-limit response does not claim to distinguish internally confounded headroom from availability. Energy capability remains a recorded failure when the zero-mean safety budget cannot reach its boundary.
