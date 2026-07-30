# O2 current-capability rolling NMPC

O2 is evaluation-only.  At each 2/4 s instant it receives the current physical state and current external capability truth, assumes that capability is held over the horizon, and receives the same causal load estimate used by deployable baselines.  It never receives future load, future switching, or future communication outcomes.

The online real-time iteration contains explicit state and action decision sequences, multiple-shooting dynamics, input/state/terminal constraints, current headroom/ramp/delay/energy/availability bounds, and a terminal SG-backup neighborhood.  The piecewise charge/discharge energy law is converted to a sustainable horizon power bound at the current energy.  One convex SQP subproblem is solved with OSQP, warm-started, and only its first action is executed.  An independent nonlinear SLSQP multiple-shooting transcription with explicit energy nodes is used for multi-start qualification; it is not substituted for episode failures.

Nominal, RLS-adaptive, and worst-case controllers solve the same rolling finite-horizon structure with their deployable information.  SG-only and fixed-allocation PI are named PI, not MPC.  Oracle performance is an upper bound on current-capability information, not exact global optimality.
