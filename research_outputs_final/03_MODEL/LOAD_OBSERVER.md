# Load observer

Development selection chose `constrained_mhe_actual_poi` from constrained MHE, unknown-input
filter and augmented Kalman candidates. Validation used the fixed selection.
All candidates construct the causal swing-balance observation from measured
frequency/tie, SG mechanical power, slow reserve and **actual BESS POI power**.
Issued command is present only in an ineligible confusion comparator. Persistent
load is a slow state/parameter, not a fresh disturbance each controller call.
