# Certificate assumptions

The finite-horizon statement is limited to linear Plant A, five registered
BESS-delay vertices, the locked capability envelope, the development-calibrated
componentwise residual set, a causal point load estimate held over the horizon,
and accepted numerical solutions with residual at most 1e-5.

The SG-backup audit treats the one-step component set as an adversarial additive
box at every supervisory update.  It checks the minimum registered SG reserve
0.025 pu and the exact terminal-supervisor limits.  This is deliberately more
conservative than empirical disturbance sequences; no validation or final data
are used to reduce it.
