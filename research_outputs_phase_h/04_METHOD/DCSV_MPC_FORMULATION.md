# DCSV-MPC formulation

DCSV-MPC separates the augmented persistent load estimate from the causal
command-to-actual capability set. For every retained delay vertex it creates a
9-state prediction sequence and shares one four-input sequence across all
vertices. Dynamics, SG power, delivered BESS power, ramp, cumulative energy,
frequency, ACE, tie, and SG mechanical constraints are explicit CVXPY
constraints. Sustainable predictions terminate in the H4
load-parameterized local set and drive BESS command toward zero. Bridge
predictions carry remaining time, required bridge power, and energy to the
registered slow-reserve handoff. Physically infeasible cases are classified
before optimization and receive an auditable SG emergency action.

Primary optimization has zero performance and settling slack. Lexicographic
restoration may relax only those two quantities; all physical constraints are
identical. Every solve records predicted states/actions, scenario count,
status, residual, slack, restoration, fallback, applied action, and committed
actual-action history. No recursive-feasibility claim is made at H5.
