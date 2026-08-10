# ACCR certificate assumptions

1. The true command-to-actual capability belongs to the registered finite candidate set and contains the contract floor during a certificate validity interval.
2. Measurement/model error is bounded by the registered residual bound; timestamps and actual BESS POI power are causal and correct.
3. A capability certificate expires after 40 s and is revoked on a change-reset; no certificate survives an unannounced loss as a hard floor.
4. The A3 probe safety result covers the full nonlinear Plant A, every registered candidate and the no-surplus branch over the registered finite horizon.
5. Contract-branch replay uses the registered Plant-A prediction model, delay grid, measured SoC and quiescent initial command pipeline.
6. The local terminal RPI result applies only near a load-parameterized Plant-A equilibrium; it is not a native ANDES DAE or global recursive-feasibility theorem.
7. Surplus loss is detected by the next control cycle; only then may SG/slow-reserve future recourse differ by branch.
