# CDSR-MPC formulation

Five exact fractional-ZOH BESS delay vertices propagate separate Plant-A and
energy states under one common finite-horizon command sequence.  At every
vertex and stage, the requested total BESS PFR+SFR power, request ramp,
cumulative split-variable energy, SG command and SG mechanical limits are hard.
Frequency, ACE and tie-line envelopes alone use bounded performance slack.
The objective minimizes an epigraph upper bound on the worst vertex L1
frequency/ACE/tie cost plus quadratic deviation from a stable ACE-PI reference.

The transaction is propose -> numerical retry -> lexicographic
performance-slack restoration -> terminal supervisor -> commit actual action.
Neither proposal nor warm start changes physical command history.  The current
terminal box is only an admissibility supervisor until F5 establishes (or
rejects) an invariance certificate.
