# CDSR-MPC pseudocode

1. Read public observation, causal state/load estimate, public energy telemetry,
   registered capability envelope, and last actually applied action.
2. Solve one common-control robust horizon over all delay vertices.
3. If the primary numerical solve is unacceptable, retry with the secondary solver.
4. If still unavailable, minimize only performance slack while all resource and
   terminal constraints remain hard, then optimize performance at that slack.
5. Numerically verify terminal membership and hard residuals.
6. Select the proposal or SG-only backup.
7. Commit exactly the selected physical action and update causal energy history.
