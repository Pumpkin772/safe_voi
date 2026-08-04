# Locked H1--H6

These hypotheses were locked before Phase-I validation/final seeds.

| ID | Falsifiable hypothesis | Registered evidence |
|---|---|---|
| H1 | Unannounced changes in power, ramp, or delay capability are materially control-relevant beyond load uncertainty alone. | Factor-separated Plant-A and native-Plant-B episodes; success-first and failure-aware metrics; no seed/factor confounding. |
| H2 | A causal load observer driven by actual BESS POI power separates persistent load error from execution loss better than a command-driven observer. | Load-only, capability-only, simultaneous-event and no-event windows; bias/RMSE/coverage after warm-up. |
| H3 | Causal set-membership/MHE maintains a conservative present deliverability set: delay coverage >=95%, false optimism <=1%, and no-excitation windows remain wide. | Held-out validation with power/ramp/delay events; finite-sample lower bounds and excitation strata. |
| H4 | Contract-floor safety plus online-envelope performance is no less safe than contract-only robust MPC and improves responsibility allocation without treating a contract violation as guaranteed. | True rolling baseline comparison, contract-violation negative controls, hard violations, restoration/fallback accounting. |
| H5 | Locked DCSV-MPC passes I6 against the strongest deployable baseline: success drop <=2 pp, no worse failure-aware score, >=2 of 3 core metrics improve >=8% with positive cluster CI, terminal recovery, and both plants consistent. | Development/validation/final separation; known/OOD, periods, horizons, mechanisms, normal1h and failure ledger. |
| H6 | Sustainable, bridge and infeasible certificates are conditional, recomputable, and match the code objects actually used in prediction. | Equation-code map; RCI/RPI or finite-horizon certificates; bridge energy/slow-reserve certificate; explicit empty/impossible cases. |

H1--H4 are mechanism claims, H5 is the decisive method claim, and H6 is the
theory/implementation-consistency claim. `NOT_EVALUATED` is neither success nor
failure. Failure of I6 after its two permitted evidence-based repair rounds ends
Direction5 with decisive negative evidence.
