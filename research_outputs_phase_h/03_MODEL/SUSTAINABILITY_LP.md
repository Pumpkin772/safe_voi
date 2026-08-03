# Registered sustainability LP

For every Plant, period, SG tension, load cell, and capability contract, H2
solves the two-area balance with long-run BESS power fixed to zero. The LP
minimizes absolute tie flow subject to SG and tie limits. A cell is sustainable
only when this LP is feasible. The stored state is the load-parameterized
equilibrium `[omega, tie, valve, mechanical, actual BESS]`; valve and mechanical
power equal the SG equilibrium dispatch.

The classification is completed and hash-locked before observer terminal-window
selection or controller design. Evaluation-side known/OOD labels are never
controller inputs.
