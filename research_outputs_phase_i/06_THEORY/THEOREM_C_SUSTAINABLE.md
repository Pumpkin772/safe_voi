# Theorem C — load-parameterized sustainable terminal set

For each registered load strictly inside SG steady capability, the equilibrium
has zero frequency/tie/BESS power and SG valve/mechanical power equal to load.
An SG-only LQR terminal feedback yields a Schur closed-loop error model. With the
explicit registered one-step additive remainder box `W`, the box radius solves
`z = |Acl| z + w`; therefore `|Acl|z+w <= z`. Recomputed certificates at both
periods are nonempty and remain inside valve, mechanical, BESS physical and SG
input margins. Claim level is `CONDITIONAL_LOCAL_LINEAR_RPI`, requiring a
quiescent BESS command pipeline and the stated remainder bound. No native-DAE
recursive-feasibility claim is made.
