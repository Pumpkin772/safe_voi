# DCSV-CR-MPC formulation

The BESS command is `u_b = u_b^g + u_b^s`. The guaranteed component obeys
contract power/ramp/delay constraints; the surplus component is bounded by the
current revocable performance witness. Both delivered and zero-surplus-loss
branches share the complete stage-0 command. From stage 1 onward SG and slow
reserve are branch-specific. Every delay vertex propagates grid state, actual
BESS power, measured-SoC energy and slow-reserve state.

The objective uses a worst-branch epigraph plus a subordinate delivered-branch
performance term and control effort. Restoration can relax only terminal
frequency/ACE/tie targets. It cannot relax contract power/ramp, physical energy,
delay causality, SG or reserve bounds. A detected contract breach revokes all
surplus and routes causal emergency support; no same-instant guarantee is made.
