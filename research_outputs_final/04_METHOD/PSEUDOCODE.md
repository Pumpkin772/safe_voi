# DCSV-CR-MPC pseudocode

1. Read public grid measurements, actual BESS POI power and measured SoC.
2. Update slow-load MHE and the causal deliverability feasible set.
3. Classify sustainable, bridge or physically infeasible domain.
4. Detect matured contract underdelivery; revoke surplus if detected.
5. Build delivered and zero-surplus loss branches with a shared current action.
6. Solve the hard rolling epigraph QP; if needed relax terminal performance only.
7. Apply supervisory SG/reserve recourse and commit the action actually applied.
8. Record every attempted optimization call, restoration and fallback.
