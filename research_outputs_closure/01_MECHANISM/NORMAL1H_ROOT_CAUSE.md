# normal1h root-cause analysis

All seven methods fail the registered 1 Hz peak-frequency Gate, including the
evaluation-only perfect-capability Oracle. The synthetic AR(2)+multisine load
profiles are bounded by 0.011105 pu and are not measured public data.
Because the failure crosses PI, contract MPC, model-adaptive MPC, DCSV-CR and
Oracle families, it is not evidence of a DCSV-only solver defect.

The control-cycle audit locates excursions after sustained closed-loop operation,
with no hard plant-state violation. DCSV adds 322 fallback calls in these six
profiles, but even the Oracle's worst peak remains above the registered limit.
The defensible interpretation is a registered profile/secondary-control quality
boundary compounded by energy/slow-mode accumulation and, for DCSV, conservative
fallback. The profiles remain in all results and are not relaxed or relabelled.
