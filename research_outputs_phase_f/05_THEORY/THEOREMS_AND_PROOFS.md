# Theorem and certificate boundary

## Finite-horizon proposition

For any accepted CDSR optimization result, every registered delay vertex uses
one common command sequence and satisfies the encoded SG command/mechanical,
total BESS PFR+SFR request, ramp, cumulative energy, and terminal constraints
to the reported numerical residual.  Performance constraints include their
explicit slack.  This is a formulation-and-numerical certificate, not a claim
of recursive feasibility.

## Robust SG-backup attempt

For each stable closed-loop design, the script forms the disturbance reachable
zonotope `sum A_cl^i diag(w)` until the omitted generator is below 1e-12.  Exact
linear support functions are compared with every terminal and minimum-reserve
limit.  The invariant/admissibility check **failed for both registered backup designs**.

Consequently recursive feasibility and robust switching safety are **not
claimed** unless the JSON certificate explicitly reports a nonempty admissible
set.  Failure of the two tested SG designs is not a category-level proof that
no possible backup controller can exist.
