# Finite-energy bridge and physical infeasibility model

The registered slow reserve arrives at 60 s and adds 0.08 pu symmetric SG
reserve per area. Pre-arrival BESS dispatch is solved under guaranteed power,
ramp over the delay-adjusted first control interval, availability, tie, and SG
limits. Charge/discharge energy is integrated only until slow-reserve arrival.
A bridge cell must enter a sustainable post-arrival equilibrium. Cells failing
steady-state power, pre-arrival power/ramp/delay, or energy are labeled
`PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY` before any controller run
and cannot be counted as ordinary controller failures.
