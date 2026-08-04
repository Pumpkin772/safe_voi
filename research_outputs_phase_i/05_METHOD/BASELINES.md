# Fair baselines

`rolling_contract_mpc` is a true receding-horizon MPC using the same predicted
states/inputs, dynamics, delay vertices, actual-action history, power/ramp/
energy constraints, domain conditions, restoration and solver diagnostics as
DCSV-MPC. Its only difference is that it ignores online surplus performance
information. `fixed_allocation_pi` is retained as a deployable non-MPC baseline
and is never labeled MPC.
