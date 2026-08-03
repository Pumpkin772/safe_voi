# DCSV-MPC pseudocode

1. Validate current public state/load estimates, actual POI power, SoC/energy,
   previous applied action, and the independent capability set.
2. Classify the estimated disturbance/capability pair as sustainable, bridge,
   or physically infeasible.
3. If infeasible, emit the physical certificate and registered SG emergency
   action without solver retry.
4. Otherwise create delay scenarios with one common future input sequence and
   explicit power/ramp/energy constraints.
5. Apply the sustainable terminal condition or bridge handoff condition.
6. Solve the primary QP. If it is not accepted, solve registered restoration
   with only performance/settling slack.
7. If neither solve is accepted, apply SG fallback. Commit exactly the action
   returned to the plant and preserve all diagnostics.
